"""Protected-span guard: quotes and citations must survive a revision
byte-for-byte. This is a deterministic gate, not a prompt instruction.

  voice.py guard original.md revised.md   -> exit 1 if any span changed or vanished
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

_PATTERNS = [
    r"“[^”]{3,}”",                                   # curly quotes
    r"\"[^\"\n]{3,}\"",                              # straight quotes
    r"\b\d+\s+(?:So\.\s*[23]d|F\.\s*(?:Supp\.\s*)?[234](?:d|th)|U\.S\.|S\.\s*Ct\.|L\.\s*Ed\.\s*2d)\s+\d+(?:,\s*\d+)?",
    r"§§?\s*[\d.]+(?:\([\w]+\))*(?:,\s*Fla\.\s*Stat\.(?:\s*\(\d{4}\))?)?",   # § 119.07(1)(a), Fla. Stat.
    r"\b\d+\s+U\.\s?S\.\s?C\.\s*(?:§§?\s*)?\d+[\w\-]*(?:\([\w]+\))*",          # 42 U.S.C. § 1983
    r"\b\d+(?:\.\d+)+(?:\([\w]+\))*,\s*Fla\.\s*Stat\.",                         # 119.07(1), Fla. Stat.
    r"\b(?:Doc|DIN|Ex|Exhibit)s?\.?\s*(?:No\.\s*)?(?:[A-Z]{1,2}\b|[A-Z]?\d+[A-Za-z]?)(?:\s*(?:at|p\.|pp\.)\s*[\d\-–]+)?",
    r"\bArt\.\s*[IVX]+,\s*(?:s|§)\.?\s*\d+(?:\([a-z]\))?",
    r"\b(?:Fla\.|Fed\.)\s*R\.[^,;)]{2,40}?\d+(?:\.\d+)*(?:\([\w]+\))*",
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",                  # dates
    r"\$\s?\d[\d,]*(?:\.\d{2})?",                    # money
    r"\b\d{1,2}[A-Z]?\d{2,4}-\d{3,6}\b",             # case numbers like 1D26-0728
]
_RX = [re.compile(p) for p in _PATTERNS]


def protected_spans(text: str) -> list[str]:
    spans: list[str] = []
    for rx in _RX:
        for m in rx.finditer(text):
            s = m.group(0).strip()
            if s not in spans:
                spans.append(s)
    # Drop spans wholly contained in a longer span.
    return [s for s in spans if not any(s != o and s in o for o in spans)]


def check(original: str, revised: str) -> list[str]:
    """Spans present in the original that are missing (or fewer) in the revision."""
    orig = Counter()
    for s in protected_spans(original):
        orig[s] = original.count(s)
    problems = []
    for s, n in orig.items():
        have = revised.count(s)
        if have < n:
            problems.append(f"{s!r}: {n} in original, {have} in revision")
    return problems


def _read(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() == ".docx":
        import docx
        return "\n".join(par.text for par in docx.Document(str(p)).paragraphs)
    return p.read_text(encoding="utf-8", errors="replace")


def guard_files(original: str, revised: str) -> bool:
    problems = check(_read(original), _read(revised))
    if problems:
        print(f"GUARD FAIL: {len(problems)} protected span(s) changed or removed:")
        for p in problems:
            print("  - " + p)
        print("Each must be restored verbatim, or Chris must approve the change explicitly.")
        return False
    print("GUARD PASS: every quote and citation in the original survives verbatim.")
    return True
