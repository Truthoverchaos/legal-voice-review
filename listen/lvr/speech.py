"""Turn legal-draft text into text a TTS voice reads naturally.

Only the SPOKEN copy is changed. The source text in the manifest stays
verbatim, so notes and proposals always refer back to the real words.
"""
from __future__ import annotations

import re

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_MONTHS = "January February March April May June July August September October November December".split()


def number_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _TENS[t] + ("-" + _ONES[o] if o else "")
    if n < 1000:
        h, r = divmod(n, 100)
        return _ONES[h] + " hundred" + (" " + number_words(r) if r else "")
    th, r = divmod(n, 1000)
    return number_words(th) + " thousand" + (" " + number_words(r) if r else "")


# Ordered: longer / more specific patterns first.
_SUBS: list[tuple[str, str]] = [
    (r"\bFla\.\s*R\.\s*App\.\s*P\.", "Florida Rule of Appellate Procedure"),
    (r"\bFla\.\s*R\.\s*Civ\.\s*P\.", "Florida Rule of Civil Procedure"),
    (r"\bFla\.\s*R\.\s*Gen\.\s*Prac\.\s*&\s*Jud\.\s*Admin\.", "Florida Rule of General Practice and Judicial Administration"),
    (r"\bFla\.\s*R\.\s*Jud\.\s*Admin\.", "Florida Rule of Judicial Administration"),
    (r"\bR\.\s*Regulating\s*Fla\.\s*Bar", "Rules Regulating The Florida Bar"),
    (r"\bFla\.\s*Stat\.", "Florida Statutes"),
    (r"\bFla\.\s*Const\.", "Florida Constitution"),
    (r"\bU\.\s*S\.\s*C\.", "U.S. Code"),
    (r"\bFla\.(?=\s*(?:\d|App|Dist|Cir|\)))", "Florida"),
    (r"\bFed\.\s*R\.\s*Civ\.\s*P\.", "Federal Rule of Civil Procedure"),
    (r"\bSo\.\s*3d\b", "Southern Third"),
    (r"\bSo\.\s*2d\b", "Southern Second"),
    (r"\bF\.\s*Supp\.\s*3d\b", "F. Supp. Third"),
    (r"\bF\.\s*Supp\.\s*2d\b", "F. Supp. Second"),
    (r"\bF\.\s*4th\b", "F. Fourth"),
    (r"\bF\.\s*3d\b", "F. Third"),
    (r"\bF\.\s*2d\b", "F. Second"),
    (r"\bL\.\s*Ed\.\s*2d\b", "L. Ed. Second"),
    (r"\bS\.\s*Ct\.", "S. Ct."),
    (r"\bet\s+seq\.", "and following"),
    (r"\bsupra\b", "supra"),
    (r"§§\s*", "sections "),
    (r"§\s*", "section "),
    (r"¶¶\s*", "paragraphs "),
    (r"¶\s*", "paragraph "),
    (r"\bss\.\s*(?=\d)", "sections "),
    (r"\bs\.\s*(?=\d)", "section "),
    (r"\bArt\.\s*", "Article "),
    (r"\bpp\.\s*(?=\d)", "pages "),
    (r"\bp\.\s*(?=\d)", "page "),
    (r"\bDocs?\.\s*(?=\d)", "Document "),
    (r"\bEx\.\s*(?=[A-Z0-9]{1,3}\b)", "Exhibit "),
    (r"(?<!\w)/s/\s*", "Signed, "),
    (r"\bExs\.\s*(?=[A-Z0-9])", "Exhibits "),
    (r"\bNo\.\s*(?=\d)", "Number "),
    (r"\bv\.\s+", "versus "),
    (r"\bvs\.\s+", "versus "),
    (r"\bIn\s+re\b", "In ray"),
    (r"\be\.g\.,?", "for example,"),
    (r"\bi\.e\.,?", "that is,"),
    (r"\bcf\.\s+", "compare "),
    (r"\bDCA\b", "D.C.A."),
    (r"→|->", " to "),
    (r"&", " and "),
    (r"\s+—\s+|—", ", "),
    (r"\s+–\s+", " to "),
]
_COMPILED = [(re.compile(p), r) for p, r in _SUBS]

_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\b")
_URL = re.compile(r"https?://\S+|\bwww\.\S+")


def _date(m: re.Match) -> str:
    mo, d, y = int(m.group(1)), int(m.group(2)), m.group(3)
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return m.group(0)
    year = int(y) + 2000 if len(y) == 2 else int(y)
    return f"{_MONTHS[mo - 1]} {d}, {year}"


def spoken(text: str) -> str:
    s = _URL.sub("(link)", text)
    s = _DATE.sub(_date, s)
    for rx, rep in _COMPILED:
        s = rx.sub(rep, s)
    return re.sub(r"\s+", " ", s).strip()


# Fixed cue clips, rendered separately so the voice can never drop them.
CUES = {"quote": ("Quote.", "End quote."), "heading": ("Heading.", None)}


def block_speech(kind: str, text: str) -> str:
    return spoken(text)


_WORDNUM = {number_words(i): i for i in range(1, 1000)}


_WORDNUM_SPACED = {k.replace("-", " "): v for k, v in _WORDNUM.items()}
# A bare number with no "paragraph" keyword and no punctuation after it only
# counts as an anchor when an editing verb follows: "14 cut the date" yes,
# "two issues here" / "ten percent" / "one more thing" no.
_EDIT_STARTERS = set("""cut change delete add move fix tighten replace say make strike rewrite reword
check insert remove flag use split merge combine shorten expand clarify put drop keep verify consider
swap restore soften strengthen lead open close start end trim lose kill mention note quote cite name""".split())
_KEYWORD = r"(?:paragraph|para|number|no\.?)"


def parse_anchor(note: str, max_num: int | None = None) -> tuple[int | None, str]:
    """'fourteen: cut the second sentence' -> (14, 'cut the second sentence').

    Accepts digits ('14', 'paragraph 14') or spoken numbers ('fourteen',
    'one hundred and twelve', 'twenty three'). Returns (None, note) unchanged
    when the leading number isn't clearly a paragraph reference.
    """
    s = note.strip()
    m = re.match(rf"^({_KEYWORD}\s+)?", s, re.I)
    keyword = bool(m.group(1))
    body = s[m.end():]

    num, end = None, 0
    dm = re.match(r"(\d{1,4})\b", body)
    if dm:
        num, end = int(dm.group(1)), dm.end()
    else:
        # Longest run of number words (up to 6 tokens, "and" allowed inside).
        toks = list(re.finditer(r"[A-Za-z]+(?:-[A-Za-z]+)?", body))
        if toks and toks[0].start() == 0:
            for k in range(min(6, len(toks)), 0, -1):
                gap_ok = all(re.fullmatch(r"\s+", body[toks[i].end():toks[i + 1].start()])
                             for i in range(k - 1))
                if not gap_ok:
                    continue
                words = [t.group(0).lower().replace("-", " ") for t in toks[:k]]
                if words[-1] == "and":
                    continue
                key = " ".join(w for w in words if w != "and")
                if key in _WORDNUM_SPACED:
                    num, end = _WORDNUM_SPACED[key], toks[k - 1].end()
                    break
    if num is None or num < 1:
        return None, s
    if max_num is not None and num > max_num:
        return None, s
    after = body[end:]
    delim = re.match(r"\s*[:,.;\-–—]\s*", after)
    if delim:
        return num, after[delim.end():].strip()
    nxt = re.match(r"\s+([A-Za-z]+)", after)
    if keyword or (nxt and nxt.group(1).lower() in _EDIT_STARTERS):
        return num, after.strip()
    return None, s
