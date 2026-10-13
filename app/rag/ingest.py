"""Ingest the guidance documents into guidance_chunks: one chunk per ## section.

    uv run python -m app.rag.ingest

Front matter gives doc_id and typology; chunk_id is CHK-<doc_id>-<nn>, numbered from 01 in
document order. Re-running replaces each document's chunks, so it is idempotent. Writes go
through the admin connection: neither copilot role may change the guidance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from app import llm
from app.db import session

GUIDANCE = Path(__file__).resolve().parent / "guidance"
_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    typology: str
    section: str
    content: str

    def embed_text(self, title: str) -> str:
        return f"{title}: {self.section}\n{self.content}"


def parse_doc(path: Path) -> tuple[str, list[Chunk]]:
    """(title, chunks) for one guidance document."""
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = _FRONT.match(raw)
    if not m:
        raise ValueError(f"{path.name}: no front matter")
    meta = dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    body = raw[m.end():]
    parts = re.split(r"^## +(.+?)\s*$", body, flags=re.M)
    # parts = [preamble, heading1, body1, heading2, body2, ...]
    chunks = [
        Chunk(chunk_id=f"CHK-{meta['doc_id']}-{i:02d}", doc_id=meta["doc_id"],
              typology=meta["typology"], section=heading, content=content.strip())
        for i, (heading, content) in enumerate(zip(parts[1::2], parts[2::2], strict=True), 1)
    ]
    if not chunks:
        raise ValueError(f"{path.name}: no ## sections")
    return meta["title"], chunks


def load_corpus(folder: Path = GUIDANCE) -> list[tuple[str, list[Chunk]]]:
    return [parse_doc(p) for p in sorted(folder.glob("*.md"))]


_UPSERT = text("""
INSERT INTO guidance_chunks (chunk_id, doc_id, typology, section, content, embedding)
VALUES (:chunk_id, :doc_id, :typology, :section, :content, CAST(:embedding AS vector))
ON CONFLICT (chunk_id) DO UPDATE
SET doc_id = EXCLUDED.doc_id, typology = EXCLUDED.typology, section = EXCLUDED.section,
    content = EXCLUDED.content, embedding = EXCLUDED.embedding
""")


def vector_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def ingest(folder: Path = GUIDANCE) -> int:
    corpus = load_corpus(folder)
    rows = [(title, c) for title, chunks in corpus for c in chunks]
    vectors = llm.embed([c.embed_text(title) for title, c in rows])
    with session("admin") as s:
        for (_, c), v in zip(rows, vectors, strict=True):
            s.execute(_UPSERT, {**c.__dict__, "embedding": vector_literal(v)})
        # drop chunks of these documents that no longer exist (a section was removed)
        for _, chunks in corpus:
            s.execute(text("DELETE FROM guidance_chunks WHERE doc_id = :d "
                           "AND NOT (chunk_id = ANY(:keep))"),
                      {"d": chunks[0].doc_id, "keep": [c.chunk_id for c in chunks]})
    return len(rows)


if __name__ == "__main__":
    n = ingest()
    print(f"ingested {n} chunks from {len(load_corpus())} documents")
