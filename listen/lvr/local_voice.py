"""Offline Windows voice (SAPI) for navigation clips: paragraph numbers and
cue words ("Quote.", "End quote."). Free, unlimited, and a different voice
from the narrator, which makes navigation easy to tell apart by ear.
"""
from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path

from .tts import RATE

VOICE = "Microsoft Zira Desktop"


def _key(text: str) -> str:
    return "local-" + hashlib.sha256(f"{VOICE}|{text}".encode()).hexdigest()[:20]


def render_many(texts: list[str], cache: Path) -> dict[str, bytes]:
    """Return {text: pcm} for every text, synthesizing missing ones in one PowerShell call."""
    cache.mkdir(parents=True, exist_ok=True)
    out, missing = {}, []
    for t in dict.fromkeys(texts):
        p = cache / f"{_key(t)}.pcm"
        if p.exists():
            out[t] = p.read_bytes()
        else:
            missing.append(t)
    if missing:
        with tempfile.TemporaryDirectory() as td:
            lines = ["Add-Type -AssemblyName System.Speech",
                     "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
                     f"$s.SelectVoice('{VOICE}')", "$s.Rate = 1"]
            # Text goes through UTF-8 files, never into the script itself, so
            # curly quotes or other characters in a heading can't break or
            # inject into the PowerShell code.
            for i, t in enumerate(missing):
                wav = Path(td) / f"{i}.wav"
                txt = Path(td) / f"{i}.txt"
                txt.write_text(t, encoding="utf-8")
                lines += [f"$s.SetOutputToWaveFile('{wav}')",
                          f"$s.Speak((Get-Content -Raw -Encoding UTF8 -LiteralPath '{txt}'))"]
            lines.append("$s.Dispose()")
            ps = Path(td) / "speak.ps1"
            ps.write_text("\n".join(lines), encoding="utf-8-sig")
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)],
                           check=True, capture_output=True)
            for i, t in enumerate(missing):
                pcm = subprocess.run(
                    ["ffmpeg", "-loglevel", "error", "-i", str(Path(td) / f"{i}.wav"),
                     "-af", "silenceremove=start_periods=1:start_threshold=-50dB:stop_periods=-1:stop_threshold=-50dB:stop_duration=0.2",
                     "-f", "s16le", "-ac", "1", "-ar", str(RATE), "pipe:1"],
                    capture_output=True, check=True).stdout
                (cache / f"{_key(t)}.pcm").write_bytes(pcm)
                out[t] = pcm
    return out
