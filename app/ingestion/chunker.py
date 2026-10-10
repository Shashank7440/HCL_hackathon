"""Heading/clause-aware chunking. Never splits a table; keeps a section label per chunk."""
from __future__ import annotations
import re
from ..config import settings

SECTION_RE = re.compile(r"^\s*(?:(\d+(?:\.\d+)*)\s+\S|Section\s+\S+|Clause\s+\S+|Article\s+\S+|(#{1,4})\s+\S)", re.I)
NUM_RE = re.compile(r"((?:\d+(?:\.\d+)*)|Q\d+)")

def section_label(line: str) -> str:
    """'### 3.1 Windows by category' -> '3.1'; '## Q3 How long...' -> 'Q3'.
    Supersession tokens (DOC#3.1) and rule source_sections must match this label."""
    rest = line.lstrip("#").strip()
    m = NUM_RE.match(rest)
    if m: return m.group(1)
    return rest[:40]

def chunk_pages(doc_id: str, title: str, pages) -> list[dict]:
    chunks, section, buf, idx = [], "", [], 0
    def flush(page):
        nonlocal idx, buf
        # heading-only buffers (the document title, empty sections) are not evidence:
        # a chunk that contains no body text must not be indexed
        if not any(l.strip() and not l.lstrip().startswith("#") for l in buf):
            buf = []; return
        text = "\n".join(buf).strip()
        while text:                                     # split long sections to CHUNK_TOKENS
            words = text.split()
            if len(words) <= settings.CHUNK_TOKENS:
                pieces = [words]
            else:
                pieces = []
                for i in range(0, len(words), settings.CHUNK_TOKENS - settings.CHUNK_OVERLAP):
                    pieces.append(words[i:i + settings.CHUNK_TOKENS])
                    if i + settings.CHUNK_TOKENS >= len(words): break
            for p in pieces:
                chunks.append({"chunk_id": f"{doc_id}::p{page}::c{idx}",
                               "doc_id": doc_id, "title": title, "section": section,
                               "page": page, "text": " ".join(p)})
                idx += 1
            text = ""
        buf = []
    for pg in pages:
        for line in (pg.text or "").splitlines():
            if "|" in line and len(line.split("|")) >= 3:     # table row: never split
                buf.append(line); continue
            m = SECTION_RE.match(line)
            if m and buf:
                flush(pg.page)
                section = section_label(line)
                buf = [line]
            else:
                if m: section = section_label(line)
                buf.append(line)
        flush(pg.page)
    return [c for c in chunks if c["text"].strip()]
