"""Settings live in <data_dir>/config.json (outside the public repo).

data_dir defaults to C:\\Users\\<you>\\VoiceReview, override with LVR_DATA.
The Gemini key is read from GEMINI_API_KEY or from the .env file named by
`gemini_env_file`; it is never copied into config.json.
"""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, asdict, field
from pathlib import Path

DEFAULT_DATA = Path(os.environ.get("LVR_DATA", Path.home() / "VoiceReview"))


@dataclass
class Config:
    data_dir: Path = DEFAULT_DATA
    token: str = ""
    public_url: str = ""          # e.g. https://yourpc.tail1234.ts.net
    port: int = 8790
    tts_model: str = "gemini-3.8-flash-tts"
    # Tier-1 Gemini keys allow ~100 TTS requests per model per day; when one
    # model runs out, rendering continues on the next (same voice name).
    tts_fallbacks: list = field(default_factory=lambda: [
        "gemini-3.8-flash-lite-tts", "gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"])
    stt_model: str = "gemini-3.8-flash"
    voice: str = "Charon"
    style: str = ""              # optional voice direction; some models read it aloud
    concurrency: int = 4
    verify_threshold: float = 0.93
    gemini_env_file: str = str(Path.home() / "OneDrive/Desktop/from claude/x_agent/.env")
    active_draft: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return self.data_dir / "config.json"

    @classmethod
    def load(cls) -> "Config":
        p = DEFAULT_DATA / "config.json"
        cfg = cls()
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            for k, v in raw.items():
                if k == "data_dir":
                    continue
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
        if not cfg.token:
            cfg.token = secrets.token_urlsafe(18)
            cfg.save()
        return cfg

    def save(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        d = asdict(self)
        d.pop("data_dir")
        self.path.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def gemini_key(self) -> str:
        k = os.environ.get("GEMINI_API_KEY", "").strip()
        if k:
            return k
        p = Path(self.gemini_env_file)
        if p.exists():
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith("GEMINI_API_KEY"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        raise RuntimeError("No Gemini key: set GEMINI_API_KEY or gemini_env_file in config.json")

    def base_url(self) -> str:
        root = (self.public_url or f"http://localhost:{self.port}").rstrip("/")
        return f"{root}/{self.token}"
