"""Voice Review command line.

  py -3.13 voice.py render <draft.md|.docx|.txt> [--no-verify]
  py -3.13 voice.py serve
  py -3.13 voice.py notes [<slug>]          # build the notes packet for Claude Code
  py -3.13 voice.py guard <original> <revised>
  py -3.13 voice.py list
  py -3.13 voice.py activate <slug>
  py -3.13 voice.py urls
  py -3.13 voice.py set <key> <value>        # e.g. set public_url https://...
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lvr.config import Config  # noqa: E402


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Voice Review")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render"); r.add_argument("source"); r.add_argument("--no-verify", action="store_true")
    sub.add_parser("serve")
    n = sub.add_parser("notes"); n.add_argument("slug", nargs="?")
    g = sub.add_parser("guard"); g.add_argument("original"); g.add_argument("revised")
    sub.add_parser("list")
    a = sub.add_parser("activate"); a.add_argument("slug")
    sub.add_parser("urls")
    s = sub.add_parser("set"); s.add_argument("key"); s.add_argument("value")
    ad = sub.add_parser("add"); ad.add_argument("text"); ad.add_argument("--slug")
    args = ap.parse_args()
    cfg = Config.load()

    if args.cmd == "render":
        from lvr.render import render
        asyncio.run(render(args.source, cfg, verify=not args.no_verify))
        print(f"\nDesk page: {cfg.base_url()}/desk")
    elif args.cmd == "serve":
        import uvicorn
        from lvr.server import create_app
        print(f"Voice Review serving on port {cfg.port}")
        print(f"  Desk page:    {cfg.base_url()}/desk")
        print(f"  Podcast feed: {cfg.base_url()}/feed.xml")
        uvicorn.run(create_app(cfg), host="127.0.0.1", port=cfg.port, log_level="warning")
    elif args.cmd == "notes":
        from lvr.notes import build_packet
        print(build_packet(cfg, args.slug or cfg.active_draft))
    elif args.cmd == "guard":
        from lvr.guard import guard_files
        ok = guard_files(args.original, args.revised)
        sys.exit(0 if ok else 1)
    elif args.cmd == "list":
        for m in sorted((cfg.data_dir / "drafts").glob("*/manifest.json")):
            d = json.loads(m.read_text(encoding="utf-8"))
            mark = "*" if d["slug"] == cfg.active_draft else " "
            mins = sum(e["duration"] for e in d["episodes"]) / 60
            print(f"{mark} {d['slug']:<45} {len(d['paragraphs']):>4} paras  {mins:>5.0f} min  {d['rendered_at']}")
    elif args.cmd == "activate":
        cfg.active_draft = args.slug; cfg.save(); print(f"Active draft: {args.slug}")
    elif args.cmd == "urls":
        print(f"Desk page:      {cfg.base_url()}/desk")
        print(f"Podcast feed:   {cfg.base_url()}/feed.xml")
        print(f"Shortcut POST:  {cfg.base_url()}/api/shortcut-note")
    elif args.cmd == "add":
        from lvr.notes import add_note
        n = add_note(cfg, args.slug or cfg.active_draft, text=args.text, source="imported")
        print(f"Saved note for ¶{n['num']}: {n['text']}" if n["num"] else f"Saved unanchored note: {n['text']}")
    elif args.cmd == "set":
        val = args.value
        cur = getattr(cfg, args.key)
        if isinstance(cur, bool): val = val.lower() in ("1", "true", "yes")
        elif isinstance(cur, int): val = int(val)
        elif isinstance(cur, float): val = float(val)
        setattr(cfg, args.key, val); cfg.save(); print(f"{args.key} = {val}")


if __name__ == "__main__":
    main()
