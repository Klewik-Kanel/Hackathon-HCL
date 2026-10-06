"""Document ingestion: file -> pages -> clause chunks -> vectors + register row.

The same ``ingest_document`` function is used by the bulk script
(scripts/ingest_all.py) and by the live ``POST /ingest`` endpoint, so a
judge's new document goes through exactly the same steps as ours.

Steps
-----
1. read text page by page (PDF via PyMuPDF; .md/.txt split on form feeds)
2. split into chunks: one chunk per numbered clause ("11.2", "12.3 ...")
   so a citation can name the exact clause and page; long clauses are
   split again with overlap. ``fixed`` chunking exists for comparison.
3. embed every chunk and store it in Chroma with the document's
   Source Register metadata copied onto each chunk
4. upsert the Source Register row in SQLite
5. optionally extract rules (see app/rules.py), each one checked against
   the clause text before it is accepted
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app import db
from app.config import settings
from app.embeddings import get_embedder
from app.models import IngestResponse, SourceMetadata
from app.vectorstore import clean_metadata, get_collection

MAX_CHUNK_CHARS = 1800
OVERLAP_CHARS = 200

# A clause starts a line: "11.2.", "11.2", "12.", "9.4 " followed by text.
CLAUSE_RE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+(\S.*)$")
# Section titles in capitals: "11. ATTENDANCE AND DETENTION"
SECTION_TITLE_RE = re.compile(r"^\s*(\d{1,2})\.\s+([A-Z][A-Z ,&/()'-]{3,})$")
# Table of contents lines end with dot leaders and a page number.
TOC_RE = re.compile(r"\.{5,}\s*\d+\s*$")
# Markdown headings in our synthetic documents: "## 1. Minimum attendance"
MD_HEADING_RE = re.compile(r"^#{1,6}\s+(?:(\d{1,2}(?:\.\d{1,2}){0,2})\.?\s+)?(.*)$")


@dataclass
class Chunk:
    text: str
    page: int
    section: str  # clause number like "11.2", or "p.N" when no clause found
    heading: str  # e.g. "11 ATTENDANCE AND DETENTION"


# ------------------------------------------------------------- reading --
def read_pages(path: Path) -> list[tuple[int, str]]:
    """Return [(page_number, text)], page numbers starting at 1."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import fitz  # PyMuPDF

        with fitz.open(path) as pdf:
            return [(i + 1, page.get_text("text")) for i, page in enumerate(pdf)]
    if suffix in {".md", ".txt"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        # A form feed (\f) marks a page break in our text documents.
        return [(i + 1, page) for i, page in enumerate(text.split("\f"))]
    raise ValueError(f"Unsupported file type: {suffix} (use PDF, .md or .txt)")


# ------------------------------------------------------------ chunking --
def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    parts, start = [], 0
    while start < len(text):
        end = min(len(text), start + MAX_CHUNK_CHARS)
        parts.append(text[start:end])
        if end == len(text):
            break
        start = end - OVERLAP_CHARS
    return parts


def chunk_clauses(pages: list[tuple[int, str]]) -> list[Chunk]:
    """One chunk per numbered clause, keeping the page where it starts."""
    chunks: list[Chunk] = []
    heading = ""
    current: dict | None = None

    def flush() -> None:
        if current and current["lines"]:
            body = "\n".join(current["lines"]).strip()
            if len(body) >= 20:
                for part in _split_long(body):
                    chunks.append(Chunk(part, current["page"], current["section"], heading))

    for page_no, text in pages:
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line.strip() or TOC_RE.search(line):
                continue
            md = MD_HEADING_RE.match(line)
            title = SECTION_TITLE_RE.match(line)
            clause = CLAUSE_RE.match(line)
            if md:
                flush()
                number, words = md.group(1), md.group(2).strip()
                if number:
                    heading = f"{number} {words}"
                    current = {"page": page_no, "section": number, "lines": [line.lstrip("# ")]}
                else:
                    heading = words
                    current = {"page": page_no, "section": f"p.{page_no}", "lines": [words]}
            elif title:
                flush()
                heading = f"{title.group(1)} {title.group(2).strip()}"
                current = {"page": page_no, "section": title.group(1), "lines": [line.strip()]}
            elif clause and "." in clause.group(1):
                flush()
                current = {"page": page_no, "section": clause.group(1), "lines": [line.strip()]}
            else:
                if current is None:
                    current = {"page": page_no, "section": f"p.{page_no}", "lines": []}
                current["lines"].append(line.strip())
    flush()
    return chunks


def chunk_fixed(pages: list[tuple[int, str]], size: int = 1500, overlap: int = 200) -> list[Chunk]:
    """Baseline for the evaluation: fixed-size windows, cited by page only."""
    chunks: list[Chunk] = []
    for page_no, text in pages:
        text = "\n".join(l for l in text.splitlines() if l.strip() and not TOC_RE.search(l))
        start = 0
        while start < len(text):
            piece = text[start:start + size].strip()
            if len(piece) >= 20:
                chunks.append(Chunk(piece, page_no, f"p.{page_no}", ""))
            if start + size >= len(text):
                break
            start += size - overlap
    return chunks


def make_chunks(pages: list[tuple[int, str]], strategy: str | None = None) -> list[Chunk]:
    strategy = strategy or settings.chunking
    chunks = chunk_clauses(pages) if strategy == "clause" else chunk_fixed(pages)
    # If a document has no numbered clauses at all, fall back to pages.
    if strategy == "clause" and not any(not c.section.startswith("p.") for c in chunks):
        chunks = chunk_fixed(pages)
    return chunks


# ------------------------------------------------------------- storing --
def upsert_source(meta: SourceMetadata, file_name: str, chunks_indexed: int) -> None:
    row = meta.model_dump()
    row.update(
        effective_from=str(meta.effective_from),
        effective_to=str(meta.effective_to) if meta.effective_to else None,
        retrieved_on=str(meta.retrieved_on) if meta.retrieved_on else None,
        file_name=file_name,
        chunks_indexed=chunks_indexed,
        ingested_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    cols = ", ".join(row)
    marks = ", ".join(f":{k}" for k in row)
    with db.session() as conn:
        conn.execute(f"INSERT OR REPLACE INTO sources ({cols}) VALUES ({marks})", row)


def ingest_document(
    path: Path,
    meta: SourceMetadata,
    strategy: str | None = None,
    embedding_model: str | None = None,
    extract_rules: bool | None = None,
) -> IngestResponse:
    """Index one document. Re-ingesting the same doc_id replaces its chunks."""
    pages = read_pages(path)
    chunks = make_chunks(pages, strategy)
    if not chunks:
        return IngestResponse(doc_id=meta.doc_id, chunks_indexed=0, status="empty: no text found (scanned PDF?)")

    collection = get_collection(embedding_model, strategy)
    collection.delete(where={"doc_id": meta.doc_id})  # idempotent re-ingest

    embedder = get_embedder(embedding_model)
    texts = [f"{c.heading}\n{c.text}" if c.heading and not c.text.startswith(c.heading[:8]) else c.text
             for c in chunks]
    vectors = embedder.embed_documents(texts)
    doc_meta = meta.model_dump(mode="json")
    ids, metadatas = [], []
    for i, chunk in enumerate(chunks):
        ids.append(f"{meta.doc_id}::{i:04d}")
        metadatas.append(clean_metadata({
            **doc_meta,
            "section": chunk.section,
            "page": chunk.page,
            "heading": chunk.heading,
        }))
    collection.add(ids=ids, embeddings=vectors, documents=texts, metadatas=metadatas)

    upsert_source(meta, path.name, len(chunks))

    rules_added = 0
    do_extract = settings.extract_rules_on_ingest if extract_rules is None else extract_rules
    if do_extract:
        from app import rules  # local import: rules depends on ingest's outputs

        rules_added = rules.extract_rules_for_doc(meta, chunks)

    return IngestResponse(
        doc_id=meta.doc_id, chunks_indexed=len(chunks), status="indexed", rules_added=rules_added
    )
