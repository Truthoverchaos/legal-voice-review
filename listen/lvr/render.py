"""Render a draft to podcast episodes: one .m4a per section, a chapter per
paragraph, a spoken number before every paragraph, and a manifest that maps
paragraph number -> episode + start time + verbatim source text.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path

from .config import Config
from .draft import load_draft
from .speech import CUES, block_speech, number_words
from .local_voice import render_many
from .tts import TTS, BYTES_PER_SEC, silence

GAP_AFTER_MARKER = 0.35
GAP_AFTER_PARA = 0.9
GAP_AFTER_INTRO = 0.8


def slugify(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s[:60] or "draft"


def draft_dir(cfg: Config, slug: str) -> Path:
    return cfg.data_dir / "drafts" / slug


def _ffmeta_escape(s: str) -> str:
    return re.sub(r"([=;#\\\n])", r"\\\1", s)


def _encode_m4a(pcm: bytes, out: Path, title: str, album: str, chapters: list[tuple[float, float, str]]):
    meta = [";FFMETADATA1", f"title={_ffmeta_escape(title)}", f"album={_ffmeta_escape(album)}",
            "artist=Voice Review", "genre=Podcast"]
    for start, end, ctitle in chapters:
        meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={int(start * 1000)}",
                 f"END={int(end * 1000)}", f"title={_ffmeta_escape(ctitle)}"]
    meta_path = out.with_suffix(".ffmeta")
    meta_path.write_text("\n".join(meta) + "\n", encoding="utf-8")
    pcm_path = out.with_suffix(".pcm")
    pcm_path.write_bytes(pcm)
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y",
         "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", str(pcm_path),
         "-i", str(meta_path), "-map_metadata", "1", "-map_chapters", "1",
         "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(out)],
        check=True,
    )
    pcm_path.unlink()
    meta_path.unlink()


def _short(text: str, n: int = 7) -> str:
    words = text.split()
    return " ".join(words[:n]) + ("…" if len(words) > n else "")


async def render(source: str | Path, cfg: Config, verify: bool = True, log=print) -> dict:
    d = load_draft(source)
    slug = slugify(Path(source).stem)
    ddir = draft_dir(cfg, slug)
    version = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    adir = ddir / "audio" / version
    adir.mkdir(parents=True, exist_ok=True)

    tts = TTS(cfg)
    tts.on_wait = log
    try:
        total = len(d.paragraphs())
        nsec = len(d.sections)
        log(f"{d.title}: {total} paragraphs in {nsec} part(s). Rendering with {cfg.tts_model} / {cfg.voice} "
            f"(announcer: offline Windows voice)...")

        # Kick off every TTS job at once; the semaphore in TTS throttles them.
        jobs: dict[str, asyncio.Task] = {}

        local_texts: dict[str, str] = {}   # navigation clips: offline announcer voice

        def job(key: str, text: str, ver: bool, local: bool = False):
            if local:
                local_texts[key] = text
                return key
            if key not in jobs:
                jobs[key] = asyncio.create_task(tts.speak(text, verify=ver))
            return key

        plan = []  # per section: list of (kind, num, text, spoken, body_key, marker_key)
        for si, sec in enumerate(d.sections, 1):
            intro = f"Part {number_words(si)} of {number_words(nsec)}. {block_speech('para', sec.title)}." if nsec > 1 \
                else f"{block_speech('para', d.title)}."
            items = [("intro", 0, sec.title, intro, job(f"intro|{intro}", intro, False, local=True), [], [])]
            for b in sec.blocks:
                if b.kind == "heading" and (b.text == sec.title or (si == 1 and b.text == d.title)):
                    continue
                sp = block_speech(b.kind, b.text)
                pre, post = [], []
                if b.num:
                    pre.append(job(f"marker|{b.num}", f"{number_words(b.num).capitalize()}.", False, local=True))
                cue_in, cue_out = CUES.get(b.kind, (None, None))
                if cue_in:
                    pre.append(job(f"cue|{cue_in}", cue_in, False, local=True))
                if cue_out:
                    post.append(job(f"cue|{cue_out}", cue_out, False, local=True))
                items.append((b.kind, b.num, b.text, sp, job(f"body|{sp}", sp, verify), pre, post))
            plan.append((sec.title, items))

        done = 0

        async def progress():
            nonlocal done
            while True:
                await asyncio.sleep(10)
                done = sum(t.done() for t in jobs.values())
                log(f"  ... {done}/{len(jobs)} audio clips ready")

        local_pcm = render_many(list(local_texts.values()), cfg.data_dir / "cache")

        def clip(k: str):
            return (local_pcm[local_texts[k]], {}) if k in local_texts else jobs[k].result()

        prog = asyncio.create_task(progress())
        try:
            await asyncio.gather(*jobs.values())
        finally:
            prog.cancel()

        manifest = {"slug": slug, "title": d.title, "source": str(Path(source).resolve()),
                    "version": version, "rendered_at": dt.datetime.now().isoformat(timespec="seconds"),
                    "model": cfg.tts_model, "voice": cfg.voice, "episodes": [], "paragraphs": []}
        flags = []
        for si, (stitle, items) in enumerate(plan, 1):
            pcm = bytearray()
            chapters = []
            first_num = last_num = None
            for kind, num, text, sp, body_key, pre, post in items:
                start = len(pcm) / BYTES_PER_SEC
                for k in pre:
                    pcm += clip(k)[0] + silence(GAP_AFTER_MARKER)
                body_pcm, info = clip(body_key)
                pcm += body_pcm
                for k in post:
                    pcm += silence(GAP_AFTER_MARKER) + clip(k)[0]
                pcm += silence(GAP_AFTER_INTRO if kind == "intro" else GAP_AFTER_PARA)
                end = len(pcm) / BYTES_PER_SEC
                if kind == "intro":
                    chapters.append((start, end, stitle))
                    continue
                label = f"¶{num} · {_short(text)}" if num else f"Heading · {_short(text)}"
                chapters.append((start, end, label))
                if num:
                    first_num = first_num or num
                    last_num = num
                    rec = {"num": num, "part": si, "kind": kind, "section": stitle, "text": text,
                           "spoken": sp, "start": round(start, 2), "end": round(end, 2)}
                    if "score" in info:
                        rec["verify_score"] = round(info["score"], 3)
                        if info["score"] < cfg.verify_threshold:
                            rec["verify_missing"] = info.get("missing", [])[:8]
                            flags.append(rec)
                    manifest["paragraphs"].append(rec)
            fname = f"{si:02d}.m4a"
            rng = f" (¶{first_num}–{last_num})" if first_num else ""
            ep_title = f"{d.title} · Part {si}/{len(plan)}: {stitle}{rng}" if len(plan) > 1 else f"{d.title}{rng}"
            _encode_m4a(bytes(pcm), adir / fname, ep_title, d.title, chapters)
            dur = len(pcm) / BYTES_PER_SEC
            manifest["episodes"].append({"part": si, "title": ep_title, "section": stitle,
                                         "file": f"{version}/{fname}", "duration": round(dur, 1),
                                         "bytes": (adir / fname).stat().st_size,
                                         "first": first_num, "last": last_num})
        manifest["verify_flags"] = [{"num": f["num"], "score": f["verify_score"], "missing": f.get("verify_missing")}
                                    for f in flags]
    finally:
        await tts.close()

    # Each draft keeps the same podcast "season" across re-renders.
    mpath = ddir / "manifest.json"
    seasons = []
    for other in (cfg.data_dir / "drafts").glob("*/manifest.json"):
        try:
            seasons.append((other.parent.name, json.loads(other.read_text(encoding="utf-8")).get("season", 0)))
        except Exception:
            pass
    mine = dict(seasons).get(slug)
    manifest["season"] = mine or (max([s for _, s in seasons] + [0]) + 1)
    mpath.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    # Keep the newest two audio versions, so a phone mid-episode doesn't 404.
    olds = sorted((p for p in (ddir / "audio").iterdir() if p.is_dir()), key=lambda p: p.name)
    for old in olds[:-2]:
        shutil.rmtree(old, ignore_errors=True)

    cfg.active_draft = slug
    cfg.save()
    mins = sum(e["duration"] for e in manifest["episodes"]) / 60
    log(f"Done: {len(manifest['episodes'])} episode(s), {mins:.0f} min of audio. Active draft is now '{slug}'.")
    if flags:
        log(f"WARNING: {len(flags)} paragraph(s) may not match the text when heard back:")
        for f in flags:
            log(f"  ¶{f['num']} (match {f['verify_score']:.0%}) missing/changed: {f.get('verify_missing')}")
    else:
        log("Audio check: every paragraph matched the text when transcribed back.")
    return manifest
