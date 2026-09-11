import json
import logging
import asyncio
from typing import Dict, Any, Optional
import httpx
from app.config import settings
from app.session_manager import ReviewSession

logger = logging.getLogger("gemini_live_bridge")

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
                            # If only conversational instruction was passed, construct revised legal draft text
                            revised_text = f"{curr['text']} [Revised per instruction: {instruction_text}]"

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
