"""Voice notes: storage and the notes packet handed to Claude Code.

A note is one JSON line in <data>/drafts/<slug>/notes.jsonl:
  {id, at, source: "desk"|"shortcut"|"typed", num, text, audio, playback_at}
Notes never edit a draft. The packet pairs each note with the verbatim
paragraph it points at plus the protected spans (quotes, cites) in it.
"""
from __future__ import annotations

import datetime as dt
import json
import secrets
from pathlib import Path

from .config import Config
from .guard import protected_spans
from .speech import parse_anchor


def notes_path(cfg: Config, slug: str) -> Path:
    return cfg.data_dir / "drafts" / slug / "notes.jsonl"


def load_manifest(cfg: Config, slug: str) -> dict:
    return json.loads((cfg.data_dir / "drafts" / slug / "manifest.json").read_text(encoding="utf-8"))


def anchor_text(cfg: Config, slug: str, text: str, playing: int | None) -> tuple[int | None, str, dict]:
    """Decide which paragraph a note belongs to. A number Chris says or types
    ("fourteen: ...") wins over the paragraph that happened to be playing."""
    try:
        m = load_manifest(cfg, slug)
    except FileNotFoundError:
        m = {"paragraphs": [], "version": None}
    said, rest = parse_anchor(text, max_num=len(m["paragraphs"]) or None) if text else (None, text)
    num = said if said is not None else playing
    para = next((p for p in m["paragraphs"] if p["num"] == num), None)
    meta = {"version": m.get("version"), "playing": playing,
            "para_snippet": para["text"][:120] if para else None}
    return num, (rest if said is not None else text), meta


def add_note(cfg: Config, slug: str, text: str = "", num: int | None = None, source: str = "typed",
             audio: str | None = None, playback_at: float | None = None) -> dict:
    num, text, meta = anchor_text(cfg, slug, text, num)
    note = {"id": secrets.token_hex(4), "at": dt.datetime.now().isoformat(timespec="seconds"),
            "source": source, "num": num, "text": text.strip(), "audio": audio,
            "playback_at": playback_at, **meta}
    p = notes_path(cfg, slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(note, ensure_ascii=False) + "\n")
    return note


def read_notes(cfg: Config, slug: str) -> list[dict]:
    p = notes_path(cfg, slug)
    if not p.exists():
        return []
    notes: dict[str, dict] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            n = json.loads(line)
            if n.get("_update"):              # later line patches an earlier note
                notes.get(n["id"], {}).update({k: v for k, v in n.items() if k not in ("_update", "id")})
            elif n.get("_delete"):
                notes.pop(n["id"], None)
            else:
                notes[n["id"]] = n
    return list(notes.values())


def update_note(cfg: Config, slug: str, note_id: str, **fields) -> None:
    with notes_path(cfg, slug).open("a", encoding="utf-8") as f:
        f.write(json.dumps({"_update": True, "id": note_id, **fields}, ensure_ascii=False) + "\n")


def delete_note(cfg: Config, slug: str, note_id: str) -> None:
    with notes_path(cfg, slug).open("a", encoding="utf-8") as f:
        f.write(json.dumps({"_delete": True, "id": note_id}) + "\n")


def build_packet(cfg: Config, slug: str) -> str:
    """Write NOTES_PACKET.md for the draft and return its path."""
    if not slug:
        raise SystemExit("No draft given and no active draft. Run: voice.py list")
    m = load_manifest(cfg, slug)
    paras = {p["num"]: p for p in m["paragraphs"]}
    notes = sorted(read_notes(cfg, slug), key=lambda n: (n.get("num") or 10**6, n["at"]))
    out = [f"# Voice notes packet: {m['title']}", "",
           f"- Source draft: `{m['source']}`",
           f"- Audio version: {m['version']} ({m['rendered_at']})",
           f"- Notes: {len(notes)}  (packet built {dt.datetime.now().isoformat(timespec='minutes')})", "",
           "## Instructions for Claude Code", "",
           "Turn each note into a PROPOSED edit of the paragraph it names. Do not edit the draft until Chris "
           "approves the proposals. Never alter text inside a protected span (quotes, citations, record cites); "
           "if a note asks for that, FLAG it instead of rewriting. After applying approved edits, run "
           "`voice.py guard <original> <revised>` and resolve every failure before calling the draft done. "
           "If the source draft changed after the audio version above, re-check that the paragraph text still "
           "matches before proposing.", ""]
    if not notes:
        out.append("_No notes recorded yet._")
    for n in notes:
        num = n.get("num")
        heading = f"## ¶{num}" if num else "## Unanchored note"
        out += [heading, "", f"**Note** ({n['source']}, {n['at']}): {n.get('text') or '_(no transcript)_'}", ""]
        if n.get("audio"):
            out.append(f"Audio: `{cfg.data_dir / 'drafts' / slug / 'note_audio' / n['audio']}`")
            out.append("")
        p = paras.get(num) if num else None
        if p and n.get("version") and n["version"] != m["version"]:
            out += [f"**WARNING:** this note was made on audio version {n['version']}; paragraph numbers may have "
                    f"shifted. When the note was made, ¶{num} began: \"{n.get('para_snippet')}\". Match by text.", ""]
        if p:
            out += [f"Section: {p['section']}", "", "**Paragraph as rendered (verbatim):**", "",
                    "> " + p["text"], ""]
            spans = protected_spans(p["text"])
            if spans:
                out.append("**Protected spans (do not alter):**")
                out += [f"- `{s}`" for s in spans]
                out.append("")
        elif num:
            out += [f"_No paragraph {num} in this render._", ""]
    path = cfg.data_dir / "drafts" / slug / "NOTES_PACKET.md"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return str(path)
