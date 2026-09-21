"""Split documents into retrieval chunks.

Wikipedia plaintext marks sections with "== Heading ==" lines. Boilerplate
sections (references, external links...) are dropped; each chunk keeps its
section heading so a citation can say where in the article it came from.
Chunks are ~1000 characters with a 150-character overlap on sentence
boundaries, which fits nomic-embed-text comfortably and keeps citations
specific.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

SKIP_SECTIONS = {"references", "external links", "see also", "further reading", "notes",
                 "gallery", "bibliography", "sources", "citations", "footnotes",
                 "notes and references", "literature"}
TARGET_CHARS = 1000
OVERLAP_CHARS = 150
MIN_CHARS = 120
HEADING_RE = re.compile(r"^\s*(=+)\s*(.+?)\s*\1\s*$")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Chunk:
    index: int
    text: str
    section: str
    content_hash: str


def sections(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    current, buf = "Summary", []
    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            if buf:
                out.append((current, "\n".join(buf).strip()))
            current, buf = m.group(2).strip(), []
        else:
            buf.append(line)
    if buf:
        out.append((current, "\n".join(buf).strip()))
    return [(h, b) for h, b in out if b and h.lower() not in SKIP_SECTIONS]


def chunk_text(text: str, title: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for heading, body in sections(text):
        sentences = [s.strip() for s in SENTENCE_RE.split(re.sub(r"\s+", " ", body)) if s.strip()]
        buf = ""
        for s in sentences:
            if len(buf) + len(s) + 1 > TARGET_CHARS and len(buf) >= MIN_CHARS:
                chunks.append(_make(len(chunks), title, heading, buf))
                tail = buf[-OVERLAP_CHARS:]
                buf = tail[tail.find(" ") + 1:] if " " in tail else ""
            buf = f"{buf} {s}".strip()
        if len(buf) >= MIN_CHARS or (buf and not chunks):
            chunks.append(_make(len(chunks), title, heading, buf))
    return chunks


def _make(index: int, title: str, section: str, body: str) -> Chunk:
    prefix = f"{title}" + (f" — {section}" if section != "Summary" else "")
    text = f"{prefix}: {body}"
    return Chunk(index, text, section, hashlib.sha256(text.encode("utf-8")).hexdigest())
