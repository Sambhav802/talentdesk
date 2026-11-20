"""Split documents into overlapping chunks on paragraph / sentence boundaries.

Markdown headings are tracked so every chunk knows which section it came from (used in citations).
"""
import re
from dataclasses import dataclass

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")


@dataclass
class Chunk:
    index: int
    text: str
    section: str = ""


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_sentences(paragraph: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_END.split(paragraph) if p.strip()]
    return parts or [paragraph.strip()]


def _hard_wrap(text: str, size: int) -> list[str]:
    """Last resort for a single 'sentence' longer than the chunk size: cut on whitespace."""
    out, cur = [], ""
    for word in text.split(" "):
        if cur and len(cur) + 1 + len(word) > size:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        out.append(cur)
    return out


def _tail(text: str, overlap: int) -> str:
    """The last whole sentences of `text` that fit in `overlap` characters (may be empty)."""
    if overlap <= 0:
        return ""
    tail = ""
    for sent in reversed(split_sentences(text)):
        candidate = f"{sent} {tail}".strip()
        if len(candidate) > overlap:
            break
        tail = candidate
    return tail


def chunk_text(text: str, size: int = 800, overlap: int = 120) -> list[Chunk]:
    """Greedy packing of paragraphs (then sentences) into chunks of at most ~`size` characters.

    Consecutive chunks of the same section share up to `overlap` characters of whole sentences.
    """
    text = normalize(text)
    if not text:
        return []
    units: list[tuple[str, str]] = []           # (section, piece)
    section = ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        lines = para.split("\n")
        m = _HEADING.match(lines[0])
        if m:
            section = m.group(1).strip()
            para = "\n".join(lines[1:]).strip()
            if not para:
                continue
        para = re.sub(r"\s*\n\s*", " ", para)
        if len(para) <= size:
            units.append((section, para))
            continue
        for sent in split_sentences(para):
            if len(sent) <= size:
                units.append((section, sent))
            else:
                units.extend((section, piece) for piece in _hard_wrap(sent, size))

    chunks: list[Chunk] = []
    cur, cur_section = "", None
    for sec, piece in units:
        if cur and (sec != cur_section or len(cur) + 2 + len(piece) > size):
            chunks.append(Chunk(len(chunks), cur, cur_section or ""))
            carry = _tail(cur, overlap) if sec == cur_section else ""
            cur = f"{carry} {piece}".strip() if carry and len(carry) + 1 + len(piece) <= size else piece
        else:
            cur = f"{cur}\n\n{piece}".strip() if cur else piece
        cur_section = sec
    if cur:
        chunks.append(Chunk(len(chunks), cur, cur_section or ""))
    return chunks
