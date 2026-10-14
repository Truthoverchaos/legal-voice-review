"""Voice Review server (runs on the PC).

Everything lives under /<token>/ so the feed and notes endpoint are private
even when exposed through a tunnel. Wrong token -> 404.

  /<t>/feed.xml                 private podcast feed (Apple Podcasts / Overcast)
  /<t>/audio/<slug>/<ver>/<f>   episode audio (range requests supported)
  /<t>/desk                     desk page: listen + record notes, keyboard driven
  /<t>/api/drafts               list rendered drafts
  /<t>/api/drafts/<slug>        manifest + notes
  /<t>/api/note                 POST a note (JSON: text | audio_b64, slug?, num?)
  /<t>/api/shortcut-note        POST {"text": ...} from the iPhone Shortcut; replies with speakable text
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hmac
import json
import re
import secrets
import subprocess
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response

from .config import Config
from .notes import add_note, anchor_text, delete_note, load_manifest, read_notes, update_note
from .speech import number_words
from .tts import TTS

HERE = Path(__file__).parent
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}")   # slugs, versions, file names: no slashes or ..


def _manifests(cfg: Config) -> list[dict]:
    out = []
    for p in (cfg.data_dir / "drafts").glob("*/manifest.json"):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return sorted(out, key=lambda m: m["rendered_at"])


def _artwork(cfg: Config) -> Path:
    p = cfg.data_dir / "artwork.png"
    if not p.exists():
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x1d3557:s=1400x1400",
                        "-frames:v", "1", str(p)], check=False)
    return p


def build_feed(cfg: Config) -> str:
    base = cfg.base_url()
    items = []
    for i, m in enumerate(_manifests(cfg), 1):
        season = m.get("season") or i
        rendered = dt.datetime.fromisoformat(m["rendered_at"]).astimezone()
        for ep in m["episodes"]:
            pub = rendered + dt.timedelta(seconds=ep["part"])
            url = f"{base}/audio/{m['slug']}/{ep['file']}"
            desc = f"Paragraphs {ep['first']} to {ep['last']}. Source: {Path(m['source']).name}. Rendered {m['rendered_at']}."
            items.append(f"""    <item>
      <title>{escape(ep['title'])}</title>
      <guid isPermaLink="false">{escape(m['slug'])}-{m['version']}-{ep['part']}</guid>
      <pubDate>{format_datetime(pub)}</pubDate>
      <enclosure url="{escape(url)}" length="{ep['bytes']}" type="audio/x-m4a"/>
      <itunes:duration>{int(ep['duration'])}</itunes:duration>
      <itunes:season>{season}</itunes:season>
      <itunes:episode>{ep['part']}</itunes:episode>
      <itunes:episodeType>full</itunes:episodeType>
      <description>{escape(desc)}</description>
    </item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Voice Review (private)</title>
    <link>{escape(base)}/desk</link>
    <description>Private draft read-backs. Do not share this feed.</description>
    <language>en-us</language>
    <itunes:type>serial</itunes:type>
    <itunes:author>Voice Review</itunes:author>
    <itunes:block>Yes</itunes:block>
    <itunes:explicit>false</itunes:explicit>
    <itunes:image href="{escape(base)}/artwork.png"/>
{chr(10).join(reversed(items))}
  </channel>
</rss>
"""


def create_app(cfg: Config) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    drafts_dir = cfg.data_dir / "drafts"

    def check(token: str):
        if not hmac.compare_digest(token.encode(), cfg.token.encode()):
            raise HTTPException(404)

    tasks: set[asyncio.Task] = set()   # keep references so transcriptions aren't garbage-collected

    def slug_or_active(slug: str | None) -> str:
        s = slug or Config.load().active_draft
        if not isinstance(s, str) or not SAFE_NAME.fullmatch(s) or not (drafts_dir / s / "manifest.json").exists():
            raise HTTPException(400, "No such draft; render one first.")
        return s

    def safe_file(base: Path, *parts: str) -> Path:
        if not all(isinstance(x, str) and SAFE_NAME.fullmatch(x) for x in parts):
            raise HTTPException(404)
        p = base.joinpath(*parts).resolve()
        if not p.is_relative_to(base.resolve()) or not p.is_file():
            raise HTTPException(404)
        return p

    async def transcribe_note(slug: str, note_id: str, audio_path: Path, mime: str):
        tts = TTS(cfg)
        try:
            text = await tts.transcribe_file(audio_path.read_bytes(), mime)
        except Exception as e:  # keep the audio; transcript can be redone
            text = f"(transcription failed: {e})"
        finally:
            await tts.close()
        note = next((n for n in read_notes(cfg, slug) if n["id"] == note_id), {})
        # A number spoken at the start of the note overrides the paragraph that was playing.
        num, rest, _meta = anchor_text(cfg, slug, text, note.get("playing", note.get("num")))
        update_note(cfg, slug, note_id, text=rest, raw=text, num=num, transcribed=True)

    @app.get("/{token}/feed.xml")
    async def feed(token: str):
        check(token)
        return Response(build_feed(cfg), media_type="application/rss+xml")

    @app.get("/{token}/artwork.png")
    async def artwork(token: str):
        check(token)
        return FileResponse(_artwork(cfg), media_type="image/png")

    @app.get("/{token}/audio/{slug}/{version}/{fname}")
    async def audio(token: str, slug: str, version: str, fname: str):
        check(token)
        return FileResponse(safe_file(drafts_dir, slug, "audio", version, fname), media_type="audio/x-m4a")

    @app.get("/{token}/desk")
    async def desk(token: str):
        check(token)
        html = (HERE / "desk.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("__BASE__", f"/{cfg.token}"))

    @app.get("/{token}/api/drafts")
    async def drafts(token: str):
        check(token)
        active = Config.load().active_draft
        return [{"slug": m["slug"], "title": m["title"], "rendered_at": m["rendered_at"],
                 "paragraphs": len(m["paragraphs"]), "active": m["slug"] == active,
                 "minutes": round(sum(e["duration"] for e in m["episodes"]) / 60)}
                for m in reversed(_manifests(cfg))]

    @app.get("/{token}/api/drafts/{slug}")
    async def draft(token: str, slug: str):
        check(token)
        slug = slug_or_active(slug)
        return {"manifest": load_manifest(cfg, slug), "notes": read_notes(cfg, slug)}

    @app.post("/{token}/api/active")
    async def set_active(token: str, req: Request):
        check(token)
        body = await req.json()
        slug = slug_or_active(body.get("slug"))
        c = Config.load(); c.active_draft = slug; c.save()
        return {"active": slug}

    @app.post("/{token}/api/note")
    async def note(token: str, req: Request):
        check(token)
        body = await req.json()
        slug = slug_or_active(body.get("slug"))
        audio_name = None
        if not isinstance(body.get("text", ""), str) or len(body.get("audio_b64") or "") > 40_000_000:
            raise HTTPException(400, "Bad note.")
        if body.get("audio_b64"):
            mime = str(body.get("mime") or "audio/webm")
            ext = {"audio/mp4": "m4a", "audio/webm": "webm", "audio/ogg": "ogg", "audio/mpeg": "mp3"}.get(
                mime.split(";")[0], "bin")
            adir = drafts_dir / slug / "note_audio"
            adir.mkdir(parents=True, exist_ok=True)
            audio_name = f"{dt.datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}.{ext}"
            (adir / audio_name).write_bytes(base64.b64decode(body["audio_b64"]))
        try:
            num = int(body["num"]) if body.get("num") not in (None, "") else None
        except (TypeError, ValueError):
            num = None
        n = add_note(cfg, slug, text=body.get("text", ""), num=num,
                     source=str(body.get("source", "desk"))[:20], audio=audio_name, playback_at=body.get("playback_at"))
        if audio_name:
            t = asyncio.create_task(transcribe_note(slug, n["id"], drafts_dir / slug / "note_audio" / audio_name,
                                                    mime.split(";")[0]))
            tasks.add(t)
            t.add_done_callback(tasks.discard)
        return n

    @app.post("/{token}/api/shortcut-note")
    async def shortcut_note(token: str, req: Request):
        check(token)
        try:
            body = await req.json()
            text = body.get("text", "") if isinstance(body, dict) else str(body)
        except Exception:
            text = (await req.body()).decode("utf-8", "replace")
        text = str(text or "").strip()[:5000]
        if not text:
            return PlainTextResponse("I didn't catch a note. Nothing saved.")
        slug = slug_or_active(None)
        n = add_note(cfg, slug, text=text, source="shortcut")
        where = f"paragraph {number_words(n['num'])}" if n.get("num") else "no paragraph number"
        return PlainTextResponse(f"Saved, {where}.")

    @app.post("/{token}/api/notes/{slug}/{note_id}/delete")
    async def del_note(token: str, slug: str, note_id: str):
        check(token)
        delete_note(cfg, slug_or_active(slug), note_id)
        return {"ok": True}

    @app.get("/{token}/api/notes/{slug}/audio/{fname}")
    async def note_audio(token: str, slug: str, fname: str):
        check(token)
        return FileResponse(safe_file(drafts_dir, slug, "note_audio", fname))

    @app.get("/")
    async def root():
        return PlainTextResponse("Voice Review")

    return app
