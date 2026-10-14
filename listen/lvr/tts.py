"""Gemini text-to-speech with a content-addressed cache, plus a
transcribe-back check so audio can't silently drop or garble words.

All audio is normalized to raw PCM: 24 kHz, mono, signed 16-bit LE.
"""
from __future__ import annotations

import asyncio
import base64
import difflib
import hashlib
import re
import subprocess
from pathlib import Path

import httpx

from .config import Config

RATE = 24000
BYTES_PER_SEC = RATE * 2
API = "https://generativelanguage.googleapis.com/v1beta/models"
MAX_CHARS = 2400
TRANSCRIBE_PROMPT = ("Generate a verbatim transcript of the speech in this audio. Include every word exactly "
                     "as spoken, in order, including any instructions or words that seem out of place. Do not "
                     "summarize, omit, or add anything. Output only the transcript.")


def silence(seconds: float) -> bytes:
    n = int(RATE * seconds)
    return b"\x00\x00" * n


def _to_pcm(data: bytes, mime: str) -> bytes:
    if mime.startswith("audio/L16") or "pcm" in mime and "wav" not in mime:
        return data
    # wav or anything else: let ffmpeg normalize it.
    p = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-f", "s16le", "-ac", "1", "-ar", str(RATE), "pipe:1"],
        input=data, capture_output=True, check=True,
    )
    return p.stdout


def _chunks(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out, cur = [], ""
    for s in sentences:
        if cur and len(cur) + len(s) + 1 > MAX_CHARS:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out


_ORD = {"first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5", "sixth": "6",
        "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10", "eleventh": "11"}


def _norm_words(s: str) -> list[str]:
    """Normalize for comparison only: 15th vs 15, third vs 3d, D.C.A. vs DCA, 1a vs 1 a."""
    s = s.lower().replace("-", " ")
    s = re.sub(r"(\d),(\d)", r"\1\2", s)
    s = re.sub(r"(\d+)(st|nd|rd|th|d)\b", r"\1", s)
    toks: list[str] = []
    for t in re.findall(r"[a-z0-9]+", s):
        toks += re.findall(r"[a-z]+|[0-9]+", t)
    out: list[str] = []
    prev_letter = False
    for t in (_ORD.get(t, t) for t in toks):
        is_letter = len(t) == 1 and t.isalpha()
        if is_letter and prev_letter:
            out[-1] += t
        else:
            out.append(t)
        prev_letter = is_letter
    return out


def similarity(expected: str, heard: str) -> tuple[float, list[str]]:
    a, b = _norm_words(expected), _norm_words(heard)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    missing = []
    for op, i1, i2, _j1, _j2 in sm.get_opcodes():
        if op in ("delete", "replace"):
            missing.append(" ".join(a[i1:i2]))
    return sm.ratio(), missing


class QuotaExhausted(RuntimeError):
    pass


class TTS:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.cache = cfg.data_dir / "cache"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.sem = asyncio.Semaphore(cfg.concurrency)
        self.client = httpx.AsyncClient(timeout=180, headers={"x-goog-api-key": cfg.gemini_key()})
        self._paused_until = 0.0
        self.models = [cfg.tts_model] + [m for m in cfg.tts_fallbacks if m != cfg.tts_model]
        self.exhausted: set[str] = set()
        self.on_wait = None   # optional log callback for rate-limit pauses

    async def close(self):
        await self.client.aclose()

    def _key(self, text: str, model: str) -> str:
        c = self.cfg
        return hashlib.sha256(f"{model}|{c.voice}|{c.style}|{text}".encode()).hexdigest()[:24]

    async def _post(self, model: str, body: dict) -> dict:
        """POST with retries. A 429 (per-minute quota) pauses ALL workers for
        the delay Google asks for, and doesn't count against the retry budget
        until 30 minutes of total waiting, so long renders slow down rather
        than fail."""
        delay, failures, waited = 4.0, 0, 0.0
        while True:
            while self._paused_until > asyncio.get_running_loop().time():
                await asyncio.sleep(self._paused_until - asyncio.get_running_loop().time())
            async with self.sem:
                try:
                    r = await self.client.post(f"{API}/{model}:generateContent", json=body)
                except httpx.HTTPError as e:
                    err, r = str(e), None
            if r is not None and r.status_code == 200:
                d = r.json()
                if d.get("candidates") and d["candidates"][0].get("content", {}).get("parts"):
                    return d
                err = f"empty response: {str(d)[:200]}"
            elif r is not None and r.status_code == 429:
                m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', r.text)
                wait = float(m.group(1)) + 1 if m else 30.0
                if "PerDay" in r.text or waited > 1800:
                    raise QuotaExhausted(f"Gemini daily quota reached for {model}")
                now = asyncio.get_running_loop().time()
                if self._paused_until < now + wait:
                    self._paused_until = now + wait
                    if self.on_wait:
                        self.on_wait(f"  (rate limit on {model}; pausing {wait:.0f}s)")
                waited += wait
                continue
            elif r is not None:
                err = f"HTTP {r.status_code}: {r.text[:200]}"
                if r.status_code in (400, 401, 403, 404):
                    raise RuntimeError(err)
            failures += 1
            if failures >= 6:
                raise RuntimeError(f"Gemini call failed after retries: {err}")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)

    async def _synth_one(self, text: str, model: str) -> bytes:
        body = {
            # Style text is prepended verbatim and some TTS models read it
            # aloud, so the default is empty; the transcribe-back check is
            # told to report every spoken word so that failure is caught.
            "contents": [{"parts": [{"text": self.cfg.style + "\n\n" + text if self.cfg.style else text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.cfg.voice}}},
            },
        }
        d = await self._post(model, body)
        part = d["candidates"][0]["content"]["parts"][0]["inlineData"]
        return _to_pcm(base64.b64decode(part["data"]), part.get("mimeType", ""))

    async def _synth(self, text: str) -> tuple[bytes, str]:
        """Synthesize with the first model that still has daily quota."""
        for m in self.models:
            if m in self.exhausted:
                continue
            try:
                return b"".join([await self._synth_one(c, m) for c in _chunks(text)]), m
            except QuotaExhausted:
                if m not in self.exhausted:
                    self.exhausted.add(m)
                    if self.on_wait:
                        self.on_wait(f"  ({m} hit its daily limit; switching to the next voice model)")
        raise QuotaExhausted("Every TTS model is at its daily limit. Run the same command tomorrow; "
                             "finished paragraphs are cached and won't be redone.")

    def _find_cached(self, text: str) -> Path | None:
        for m in self.models:
            p = self.cache / f"{self._key(text, m)}.pcm"
            if p.exists():
                return p
        return None

    async def transcribe(self, pcm: bytes) -> str:
        # Encode to a small mp3 for upload.
        p = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "s16le", "-ar", str(RATE), "-ac", "1", "-i", "pipe:0",
             "-b:a", "48k", "-f", "mp3", "pipe:1"],
            input=pcm, capture_output=True, check=True,
        )
        return await self.transcribe_file(p.stdout, "audio/mp3")

    async def transcribe_file(self, data: bytes, mime: str, prompt: str | None = None) -> str:
        # temperature 0 + gemini-3.8-flash: in testing (10/14/26) gemini-3.5-flash
        # invented text on short clips; 3.8-flash at temp 0 was exact every time.
        body = {"contents": [{"parts": [
            {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}},
            {"text": prompt or TRANSCRIBE_PROMPT},
        ]}], "generationConfig": {"temperature": 0}}
        d = await self._post(self.cfg.stt_model, body)
        return "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"]).strip()

    async def speak(self, text: str, verify: bool = True) -> tuple[bytes, dict]:
        """Return PCM for `text` (cached) and a verification record."""
        pcm_path = self._find_cached(text)
        info = {"cached": pcm_path is not None}
        if pcm_path:
            pcm = pcm_path.read_bytes()
        else:
            pcm, model = await self._synth(text)
            pcm_path = self.cache / f"{self._key(text, model)}.pcm"
            pcm_path.write_bytes(pcm)
        info["model"] = pcm_path.stem
        ver_path = pcm_path.with_suffix(".verify")
        if verify:
            if ver_path.exists():
                heard = ver_path.read_text(encoding="utf-8").split("\n", 1)[-1].strip()
                score, missing = similarity(text, heard)
                info.update(score=score, heard=heard, missing=missing)
            else:
                try:
                    heard = await self.transcribe(pcm)
                    score, missing = similarity(text, heard)
                    if score < self.cfg.verify_threshold and not info["cached"]:
                        # One automatic retry: TTS occasionally skips a clause.
                        try:
                            pcm2, model2 = await self._synth(text)
                            heard2 = await self.transcribe(pcm2)
                            score2, missing2 = similarity(text, heard2)
                            if score2 > score:
                                pcm, heard, score, missing = pcm2, heard2, score2, missing2
                                pcm_path.unlink(missing_ok=True)
                                pcm_path = self.cache / f"{self._key(text, model2)}.pcm"
                                pcm_path.write_bytes(pcm)
                                ver_path = pcm_path.with_suffix(".verify")
                        except QuotaExhausted:
                            pass
                    info.update(score=score, heard=heard, missing=missing)
                    ver_path.write_text(f"{score:.4f}\n{heard}\n", encoding="utf-8")
                except QuotaExhausted:
                    info["unverified"] = True
        return pcm, info
