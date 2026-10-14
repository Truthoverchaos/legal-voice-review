"""Load a draft (.md / .txt / .docx) into numbered, sectioned paragraphs.

Every spoken paragraph gets a global number (1..N) that never depends on
sections, so a voice note that starts "fourteen: ..." anchors to exactly one
paragraph. Headings are not numbered; they start a new section and are read
as "Section: <title>".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Block:
    kind: str            # "heading" | "para" | "quote" | "item"
    text: str            # source text, verbatim (minus markup)
    level: int = 0       # heading level
    num: int = 0         # global paragraph number (0 for headings)


@dataclass
class Section:
    title: str
    blocks: list[Block] = field(default_factory=list)

    @property
    def paras(self) -> list[Block]:
        return [b for b in self.blocks if b.kind != "heading"]


@dataclass
class Draft:
    title: str
    source: str
    sections: list[Section]

    def paragraphs(self) -> list[Block]:
        return [b for s in self.sections for b in s.paras]

    def to_dict(self) -> dict:
        return asdict(self)


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_MD_ITEM = re.compile(r"^\s*(?:[-*+]\s+(.*)|(\d+[.)]\s+.*))$")   # ordered items keep their own number
_MD_RULE = re.compile(r"^\s*([-*_])\s*(\1\s*){2,}$")


def _strip_md_inline(s: str) -> str:
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)                 # images
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)             # links -> text
    s = re.sub(r"\[\^[^\]]+\]", "", s)                         # footnote refs
    s = re.sub(r"<[^>]+>", "", s)                              # html tags
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)                  # bold
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", s)  # italics
    s = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"\1", s)
    s = s.replace("`", "")
    return re.sub(r"\s+", " ", s).strip()


def _parse_md(text: str) -> list[Block]:
    blocks: list[Block] = []
    buf: list[str] = []
    buf_kind = "para"
    in_fence = False

    def flush():
        nonlocal buf, buf_kind
        t = _strip_md_inline(" ".join(buf))
        if t:
            blocks.append(Block(buf_kind, t))
        buf, buf_kind = [], "para"

    lines = text.splitlines()
    if lines and lines[0].strip() == "---":                  # YAML front matter
        for i in range(1, len(lines)):
            if lines[i].strip() in ("---", "..."):
                lines = lines[i + 1:]
                break
    for idx, raw in enumerate(lines):
        line = raw.rstrip()
        nxt = lines[idx + 1].strip() if idx + 1 < len(lines) else ""
        if line.strip() and not buf and re.fullmatch(r"=+|-{2,}", nxt or "x") and not line.lstrip().startswith(("|", ">", "-", "*")):
            t = _strip_md_inline(line)                       # setext heading (underlined)
            if t:
                blocks.append(Block("heading", t, level=1 if nxt.startswith("=") else 2))
            lines[idx + 1] = ""
            continue
        if line.strip().startswith("```"):
            flush()
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not line.strip() or _MD_RULE.match(line):
            flush()
            continue
        m = _MD_HEADING.match(line)
        if m:
            flush()
            t = _strip_md_inline(m.group(2))
            if t:
                blocks.append(Block("heading", t, level=len(m.group(1))))
            continue
        if line.lstrip().startswith("|"):          # table row: read cells
            flush()
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            t = _strip_md_inline(", ".join(c for c in cells if c))
            if t:
                blocks.append(Block("item", t))
            continue
        if line.lstrip().startswith(">"):
            if buf_kind != "quote":
                flush()
                buf_kind = "quote"
            buf.append(line.lstrip().lstrip(">").strip())
            continue
        m = _MD_ITEM.match(line)
        if m:
            flush()
            buf_kind = "item"
            buf.append(m.group(1) or m.group(2))
            continue
        if buf_kind == "quote":
            flush()
        buf.append(line.strip())
    flush()
    return blocks


def _parse_txt(text: str) -> list[Block]:
    blocks: list[Block] = []
    for chunk in re.split(r"\n\s*\n", text):
        t = re.sub(r"\s+", " ", chunk).strip()
        if not t:
            continue
        letters = re.sub(r"[^A-Za-z]", "", t)
        if len(t) < 90 and letters and letters.isupper():
            blocks.append(Block("heading", t, level=1))
        else:
            blocks.append(Block("para", t))
    return blocks


def _parse_docx(path: Path) -> list[Block]:
    import docx  # python-docx

    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))
    blocks: list[Block] = []
    # Walk the body in document order so tables land where they appear.
    for child in d.element.body.iterchildren():
        if child.tag.endswith("}tbl"):
            for row in Table(child, d).rows:
                cells = []
                for c in row.cells:
                    ct = re.sub(r"\s+", " ", c.text).strip()
                    if ct and ct not in cells:
                        cells.append(ct)
                if cells:
                    blocks.append(Block("item", ", ".join(cells)))
            continue
        if not child.tag.endswith("}p"):
            continue
        p = Paragraph(child, d)
        t = re.sub(r"\s+", " ", p.text).strip()
        if not t:
            continue
        style = (p.style.name or "").lower() if p.style is not None else ""
        m = re.match(r"heading\s*(\d)", style)
        if m or style == "title":
            blocks.append(Block("heading", t, level=int(m.group(1)) if m else 1))
        elif "quote" in style or "block" in style:
            blocks.append(Block("quote", t))
        elif "list" in style:
            blocks.append(Block("item", t))
        else:
            blocks.append(Block("para", t))
    return blocks


def load_draft(path: str | Path) -> Draft:
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".docx":
        blocks = _parse_docx(path)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        blocks = _parse_md(text) if ext in (".md", ".markdown") else _parse_txt(text)

    # Title: first H1 if present, else the file name.
    title = path.stem.replace("_", " ")
    for b in blocks:
        if b.kind == "heading":
            title = b.text
            break

    # Sections break at the shallowest heading level that occurs at least
    # twice (so a single document title doesn't swallow everything).
    levels = [b.level for b in blocks if b.kind == "heading"]
    split_level = None
    for lvl in sorted(set(levels)):
        if levels.count(lvl) >= 2:
            split_level = lvl
            break

    sections: list[Section] = [Section(title="Opening")]
    n = 0
    for b in blocks:
        if b.kind == "heading" and split_level is not None and b.level <= split_level:
            sections.append(Section(title=b.text))
            sections[-1].blocks.append(b)
            continue
        if b.kind != "heading":
            n += 1
            b.num = n
        sections[-1].blocks.append(b)

    sections = [s for s in sections if s.paras]
    return Draft(title=title, source=str(path), sections=sections)
