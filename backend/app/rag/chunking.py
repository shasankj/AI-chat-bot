"""Clean PDF page text and split it into overlapping, sentence-aligned chunks.

Design choices (each is a tunable trade-off, covered in the workbook):
  * Chunks never cross a page boundary  -> every chunk has an exact page number to cite.
  * Split on sentence boundaries        -> we never cut a sentence in half.
  * Overlap is whole sentences          -> chunks start at a sentence start, and a fact that
                                           straddles two chunks still appears whole in one.
  * ~1000 characters (~170 words)       -> big enough for context, small enough to be ONE idea.
  * "Furniture" is removed              -> page numbers and repeated revision stamps are noise
                                           that would pollute the embeddings.
"""
import re

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200     # max characters of trailing sentences repeated at the next chunk's start
MIN_CHUNK_CHARS = 80    # drop near-empty fragments
EDGE_LINES = 3          # page numbers only live in the first/last few lines of a page

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_PAGE_NUMBER_LINE = re.compile(r"^\s*(?:page\s+)?\d{1,3}\s*$", re.IGNORECASE)
_REVISION_STAMP = re.compile(r"\(Rev\. \d+,[^)]*\)")   # "(Rev. 18, Issued: 01-15-16, Effective: ...)"


def strip_page_furniture(raw: str) -> str:
    """Remove lines that are only a page number, but ONLY near the page's top/bottom,
    so a legitimate line like '2026' in the middle of a table is left alone."""
    lines = raw.split("\n")
    n = len(lines)
    kept = [ln for i, ln in enumerate(lines)
            if not (_PAGE_NUMBER_LINE.match(ln) and (i < EDGE_LINES or i >= n - EDGE_LINES))]
    return "\n".join(kept)


def is_mostly_non_latin(text: str, threshold: float = 0.2) -> bool:
    """Language-assistance pages repeat the same notice in Arabic, Armenian, Chinese...
    The English embedding model can't represent them, and they'd match random queries."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    return sum(ord(ch) > 0x24F for ch in letters) / len(letters) > threshold  # > Latin Extended-B


def clean_text(raw: str) -> str:
    text = raw.replace("\x00", " ")                  # NUL bytes are illegal in Postgres TEXT
    # A hyphen at a line end is almost always a REAL hyphen (non-formulary, cost-sharing, a URL),
    # so keep it and just drop the newline. Never glue words together.
    text = re.sub(r"-[ \t]*\n[ \t]*", "-", text)
    text = _REVISION_STAMP.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()         # collapse all whitespace runs


def _split_long(sentence: str, size: int) -> list[str]:
    """A 'sentence' longer than a chunk (tables, lists, URLs) is cut at word boundaries."""
    parts, cur = [], ""
    for w in sentence.split(" "):
        if cur and len(cur) + 1 + len(w) > size:
            parts.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        parts.append(cur)
    return parts


def chunk_page(page_text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = clean_text(strip_page_furniture(page_text))
    if len(text) < MIN_CHUNK_CHARS or is_mostly_non_latin(text):
        return []

    sentences: list[str] = []
    for s in _SENTENCE_END.split(text):
        sentences.extend(_split_long(s, size) if len(s) > size else [s])

    chunks: list[str] = []
    cur: list[str] = []          # sentences in the chunk being built
    cur_len = 0
    for s in sentences:
        if cur and cur_len + 1 + len(s) > size:
            chunks.append(" ".join(cur))
            # Overlap: carry trailing WHOLE sentences (up to `overlap` chars) into the next chunk.
            carry, carry_len = [], 0
            for prev in reversed(cur):
                if carry_len + len(prev) > overlap:
                    break
                carry.insert(0, prev)
                carry_len += len(prev) + 1
            cur, cur_len = carry, carry_len
        cur.append(s)
        cur_len += len(s) + 1
    if cur:
        chunks.append(" ".join(cur))

    # Second, stricter pass per chunk: mixed-language pages slip under the page-level threshold,
    # but even ~2% non-Latin letters never occurs in genuine English policy text.
    return [c for c in chunks if len(c) >= MIN_CHUNK_CHARS and not is_mostly_non_latin(c, 0.02)]
