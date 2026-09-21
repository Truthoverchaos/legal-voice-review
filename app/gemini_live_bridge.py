import base64
import io
import json
import logging
import asyncio
import wave
from typing import Dict, Any, Optional
import httpx
from app.config import settings
from app.session_manager import ReviewSession

logger = logging.getLogger("gemini_live_bridge")

# Model used for one-shot audio transcription + revision drafting (a plain
# generateContent call, not the Multimodal Live streaming API). Any
# gemini-2.x model that accepts audio input works; this is deliberately
# independent of GEMINI_LIVE_MODEL, which names a Live-API-flavored model id
# that generateContent doesn't necessarily accept.
AUDIO_INSTRUCTION_MODEL = "gemini-2.0-flash"

AUDIO_INSTRUCTION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "transcript": {
            "type": "STRING",
            "description": "Verbatim best-effort transcript of what the attorney said."
        },
        "intent": {
            "type": "STRING",
            "enum": ["revise", "next", "repeat", "previous", "unclear"],
            "description": (
                "revise: the attorney described or dictated a change to the current paragraph. "
                "next/previous: attorney wants to move to another paragraph. "
                "repeat: attorney wants the current paragraph read again, unchanged. "
                "unclear: audio was silent, unintelligible, or off-topic."
            )
        },
        "revised_paragraph": {
            "type": "STRING",
            "description": (
                "Required when intent is 'revise'. The FULL corrected paragraph text, "
                "incorporating the attorney's spoken instruction, in the same legal "
                "drafting style and voice as the original paragraph. Not a description "
                "of the change -- the actual replacement text, ready to save verbatim."
            )
        }
    },
    "required": ["transcript", "intent"]
}

SYSTEM_INSTRUCTION = """You are an expert legal drafting and review assistant assisting Florida litigation attorney Christopher Hanson.
Your job is to read legal drafts aloud paragraph-by-paragraph for verbal review, listen for verbal interruptions and edit requests, execute revisions, and read back the changes before continuing.

Operational Rules:
1. When asked to read a document, read the active paragraph clearly, deliberately, and with proper legal cadence (e.g. proper citation pronunciation).
2. When the user interrupts with a verbal change (e.g., "Change the statutory reference to...", "Add a paragraph stating..."):
   - Acknowledge the instruction immediately.
   - Formulate the precise revised text for the active paragraph.
   - Call the tool `update_paragraph` with the paragraph_id and the revised_text.
   - Read back the exact revised text to the attorney.
   - Ask: "Does this look good, or should we continue to the next paragraph?"
3. Never introduce conversational filler or unnecessary explanations. Keep confirmations crisp, professional, and grounded in active voice.
4. If the user says "Next" or "Continue", call `advance_to_next_paragraph` and read the next paragraph aloud.
"""

TOOL_DECLARATIONS = [
    {
        "functionDeclarations": [
            {
                "name": "update_paragraph",
                "description": "Applies a verbal revision to the legal document paragraph directly in-line.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "paragraph_id": {
                            "type": "INTEGER",
                            "description": "The numeric ID of the paragraph being revised."
                        },
                        "revised_text": {
                            "type": "STRING",
                            "description": "The exact updated text of the entire paragraph incorporating the requested legal revisions."
                        }
                    },
                    "required": ["paragraph_id", "revised_text"]
                }
            },
            {
                "name": "advance_to_next_paragraph",
                "description": "Advances reading pointer to the subsequent paragraph in the draft.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {}
                }
            },
            {
                "name": "repeat_paragraph",
                "description": "Repeats reading the current paragraph from the beginning.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {}
                }
            }
        ]
    }
]

class GeminiLiveBridge:
    def __init__(self, session: ReviewSession, client_ws):
        self.session = session
        self.client_ws = client_ws
        self.gemini_ws = None
        self.is_running = False

    def build_setup_message(self) -> Dict[str, Any]:
        """
        Builds the initial setup frame for Gemini Multimodal Live API.
        """
        return {
            "setup": {
                "model": settings.GEMINI_LIVE_MODEL,
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {
                        "voiceConfig": {
                            "prebuiltVoiceConfig": {
                                "voiceName": settings.GEMINI_VOICE_NAME
                            }
                        }
                    }
                },
                "systemInstruction": {
                    "parts": [{"text": SYSTEM_INSTRUCTION}]
                },
                "tools": TOOL_DECLARATIONS
            }
        }

    async def handle_tool_call(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes functions requested by Gemini Live against the active legal draft.
        """
        function_calls = tool_call.get("functionCalls", [])
        responses = []

        for call in function_calls:
            name = call.get("name")
            args = call.get("args", {})
            call_id = call.get("id", "call_0")

            if name == "update_paragraph":
                para_id = args.get("paragraph_id")
                revised_text = args.get("revised_text")
                record = await self.session.revise_current_paragraph(revised_text)
                
                # Notify iPhone PWA of the update diff
                await self.client_ws.send_text(json.dumps({
                    "type": "paragraph_updated",
                    "edit": record,
                    "session_state": self.session.get_state()
                }))

                responses.append({
                    "name": name,
                    "id": call_id,
                    "response": {"result": "ok", "updated_record": record}
                })

            elif name == "advance_to_next_paragraph":
                next_para = self.session.advance_paragraph()
                await self.client_ws.send_text(json.dumps({
                    "type": "paragraph_advanced",
                    "current_paragraph": next_para,
                    "current_index": self.session.current_paragraph_idx
                }))
                responses.append({
                    "name": name,
                    "id": call_id,
                    "response": {"result": "advanced", "current_paragraph": next_para}
                })

            elif name == "repeat_paragraph":
                current_para = self.session.get_current_paragraph()
                responses.append({
                    "name": name,
                    "id": call_id,
                    "response": {"result": "repeating", "current_paragraph": current_para}
                })

        return {"toolResponse": {"functionResponses": responses}}

    @staticmethod
    def _pcm16_to_wav_bytes(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
        """Wraps headerless 16-bit mono PCM (what AudioEngine.finalizeUtterance()
        produces) in a minimal WAV container, since Gemini's audio input expects
        a real audio file, not raw samples."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        return buf.getvalue()

    async def transcribe_and_interpret_audio(self, audio_b64: str) -> Dict[str, Any]:
        """
        Sends a recorded spoken instruction to Gemini for transcription AND
        interpretation in one call: Gemini both hears what was said and, if it
        was a revision request, drafts the actual replacement paragraph text.

        Returns a dict shaped like AUDIO_INSTRUCTION_SCHEMA, or
        {"intent": "error", "transcript": "", "error": "..."} if the call
        failed for any reason (missing API key, network error, bad response).
        """
        if not settings.GEMINI_API_KEY:
            return {"intent": "error", "transcript": "", "error": "GEMINI_API_KEY is not configured."}

        try:
            pcm_bytes = base64.b64decode(audio_b64)
            wav_bytes = self._pcm16_to_wav_bytes(pcm_bytes)
            wav_b64 = base64.b64encode(wav_bytes).decode("ascii")
        except Exception as e:
            logger.error(f"Failed to decode/wrap incoming audio: {e}")
            return {"intent": "error", "transcript": "", "error": f"Bad audio payload: {e}"}

        curr = self.session.get_current_paragraph()
        current_text = curr["text"] if curr else "(no active paragraph)"

        prompt = (
            f"{SYSTEM_INSTRUCTION}\n\n"
            f"The current paragraph being reviewed is:\n\"\"\"\n{current_text}\n\"\"\"\n\n"
            "Listen to the attached audio: the attorney speaking a review instruction. "
            "Respond with the structured JSON described by the response schema."
        )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{AUDIO_INSTRUCTION_MODEL}:generateContent"
        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "audio/wav", "data": wav_b64}}
                ]
            }],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": AUDIO_INSTRUCTION_SCHEMA
            }
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    url,
                    params={"key": settings.GEMINI_API_KEY},
                    json=payload
                )
                resp.raise_for_status()
                data = resp.json()

            text_out = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text_out)
            logger.info(f"Audio instruction transcribed: intent={parsed.get('intent')} transcript={parsed.get('transcript')!r}")
            return parsed
        except Exception as e:
            logger.error(f"Gemini audio transcription call failed: {e}")
            return {"intent": "error", "transcript": "", "error": str(e)}

    async def run_fallback_simulation(self):
        """
        Runs full conversational review loop for offline testing or prior to API key entry.
        Supports verbal simulation directly through the iPhone PWA interface.
        """
        logger.info("Running simulated voice review loop (Fallback / Demo mode)")
        
        # Greet user and start reading first paragraph
        curr = self.session.get_current_paragraph()
        if curr:
            await self.client_ws.send_text(json.dumps({
                "type": "assistant_message",
                "text": f"Ready to review '{self.session.title}'. I have created a clean pre-review backup in Google Drive. Starting with paragraph 1: \"{curr['text']}\"",
                "speak_text": f"Ready to review. I created a clean pre-review backup copy. Starting paragraph one. {curr['text']}",
                "current_paragraph": curr,
                "current_index": self.session.current_paragraph_idx
            }))

        while True:
            try:
                msg_raw = await self.client_ws.receive_text()
                msg = json.loads(msg_raw)
                msg_type = msg.get("type")

                if msg_type == "audio_input":
                    # Audio chunk received from iPhone mic
                    continue

                elif msg_type == "audio_instruction":
                    audio_b64 = msg.get("audio_base64", "")
                    await self.client_ws.send_text(json.dumps({"type": "transcribing"}))

                    result = await self.transcribe_and_interpret_audio(audio_b64)
                    intent = result.get("intent")
                    transcript = result.get("transcript", "")

                    if intent == "error":
                        await self.client_ws.send_text(json.dumps({
                            "type": "assistant_message",
                            "text": f"Voice transcription failed: {result.get('error')}. Use the text box instead for now.",
                            "speak_text": "Sorry, I couldn't process that. Please try again, or type your instruction instead."
                        }))

                    elif intent == "unclear":
                        await self.client_ws.send_text(json.dumps({
                            "type": "assistant_message",
                            "text": f"Didn't catch a clear instruction (heard: \"{transcript}\").",
                            "speak_text": "Sorry, I didn't catch that clearly. Please try again."
                        }))

                    elif intent in ("next", "continue"):
                        next_p = self.session.advance_paragraph()
                        if next_p:
                            await self.client_ws.send_text(json.dumps({
                                "type": "assistant_message",
                                "text": f"Heard: \"{transcript}\". Moving to paragraph {self.session.current_paragraph_idx + 1}: \"{next_p['text']}\"",
                                "speak_text": f"Paragraph {self.session.current_paragraph_idx + 1}. {next_p['text']}",
                                "current_paragraph": next_p,
                                "current_index": self.session.current_paragraph_idx
                            }))
                        else:
                            await self.client_ws.send_text(json.dumps({
                                "type": "assistant_message",
                                "text": "You have reached the end of the document. All changes have been saved cleanly to Google Docs.",
                                "speak_text": "Review complete. All revisions are saved."
                            }))

                    elif intent == "previous":
                        prev_idx = max(0, self.session.current_paragraph_idx - 1)
                        prev_p = self.session.seek_paragraph(prev_idx)
                        await self.client_ws.send_text(json.dumps({
                            "type": "assistant_message",
                            "text": f"Heard: \"{transcript}\". Back to paragraph {self.session.current_paragraph_idx + 1}: \"{prev_p['text']}\"" if prev_p else "Already at the first paragraph.",
                            "speak_text": f"Paragraph {self.session.current_paragraph_idx + 1}. {prev_p['text']}" if prev_p else "Already at the first paragraph.",
                            "current_paragraph": prev_p,
                            "current_index": self.session.current_paragraph_idx
                        }))

                    elif intent == "repeat":
                        curr = self.session.get_current_paragraph()
                        await self.client_ws.send_text(json.dumps({
                            "type": "assistant_message",
                            "text": f"Repeating paragraph {self.session.current_paragraph_idx + 1}: \"{curr['text']}\"",
                            "speak_text": curr['text'],
                            "current_paragraph": curr,
                            "current_index": self.session.current_paragraph_idx
                        }))

                    elif intent == "revise":
                        revised_text = result.get("revised_paragraph")
                        if not revised_text:
                            await self.client_ws.send_text(json.dumps({
                                "type": "assistant_message",
                                "text": f"Heard: \"{transcript}\", but couldn't draft a revision from it. Try rephrasing.",
                                "speak_text": "I heard you, but couldn't draft a revision from that. Please try rephrasing."
                            }))
                        else:
                            edit_rec = await self.session.revise_current_paragraph(revised_text)
                            await self.client_ws.send_text(json.dumps({
                                "type": "paragraph_updated",
                                "edit": edit_rec,
                                "session_state": self.session.get_state()
                            }))
                            await self.client_ws.send_text(json.dumps({
                                "type": "assistant_message",
                                "text": f"Heard: \"{transcript}\". Updated paragraph {self.session.current_paragraph_idx + 1}: \"{revised_text}\"",
                                "speak_text": f"Updated. {revised_text}. Say 'next' when ready, or the red button again to make another change.",
                                "current_paragraph": self.session.get_current_paragraph(),
                                "current_index": self.session.current_paragraph_idx
                            }))

                elif msg_type == "barge_in":
                    # Interruption signal from iPhone
                    logger.info("Barge-in received: interrupting assistant playback")
                    await self.client_ws.send_text(json.dumps({
                        "type": "interrupted",
                        "note": "Playback silenced immediately."
                    }))

                elif msg_type == "instruction":
                    # User provided a verbal revision instruction
                    instruction_text = msg.get("text", "").strip()
                    logger.info(f"Processing revision instruction: {instruction_text}")

                    if any(w in instruction_text.lower() for w in ["next", "continue", "move on"]):
                        next_p = self.session.advance_paragraph()
                        if next_p:
                            await self.client_ws.send_text(json.dumps({
                                "type": "assistant_message",
                                "text": f"Moving to paragraph {self.session.current_paragraph_idx + 1}: \"{next_p['text']}\"",
                                "speak_text": f"Paragraph {self.session.current_paragraph_idx + 1}. {next_p['text']}",
                                "current_paragraph": next_p,
                                "current_index": self.session.current_paragraph_idx
                            }))
                        else:
                            await self.client_ws.send_text(json.dumps({
                                "type": "assistant_message",
                                "text": "You have reached the end of the document. All changes have been saved cleanly to Google Docs.",
                                "speak_text": "Review complete. All revisions are saved."
                            }))
                    elif any(w in instruction_text.lower() for w in ["repeat", "read again"]):
                        curr = self.session.get_current_paragraph()
                        await self.client_ws.send_text(json.dumps({
                            "type": "assistant_message",
                            "text": f"Repeating paragraph {self.session.current_paragraph_idx + 1}: \"{curr['text']}\"",
                            "speak_text": curr['text'],
                            "current_paragraph": curr,
                            "current_index": self.session.current_paragraph_idx
                        }))
                    else:
                        # Apply revision
                        curr = self.session.get_current_paragraph()
                        revised_text = msg.get("revised_text")
                        if not revised_text:
                            # No AI rewriting step exists yet (see USER_GUIDE.md item 3).
                            # Treat the typed/spoken text as the literal replacement for
                            # the paragraph -- matching the REST /edit endpoint's behavior
                            # -- rather than silently appending a bracketed note onto the
                            # original text, which corrupted the saved document.
                            revised_text = instruction_text

                        edit_rec = await self.session.revise_current_paragraph(revised_text)
                        await self.client_ws.send_text(json.dumps({
                            "type": "paragraph_updated",
                            "edit": edit_rec,
                            "session_state": self.session.get_state()
                        }))
                        await self.client_ws.send_text(json.dumps({
                            "type": "assistant_message",
                            "text": f"Updated Paragraph {self.session.current_paragraph_idx + 1}: \"{revised_text}\"",
                            "speak_text": f"Updated. {revised_text}. Say 'Continue' when ready.",
                            "current_paragraph": self.session.get_current_paragraph(),
                            "current_index": self.session.current_paragraph_idx
                        }))

            except Exception as e:
                logger.error(f"WebSocket session error: {e}")
                break
