"""Find the document clauses that match a question, and label each one.

``search`` returns hits sorted by similarity, each with a ``status``:

- applicable       in force on as_of_date and in the student's scope
- upcoming         not yet in force (mentioned as an upcoming change only)
- expired          effective_to is before as_of_date
- out_of_scope     for another programme or batch
- superseded       explicitly replaced by a level-1/2 document (Annex A step 2)

Only ``applicable`` hits may be used as evidence for the answer. This is
the document-level half of the precedence policy; the rule-level half
(which threshold wins) lives in app/precedence.py.
"""

from __future__ import annotations

import re
from datetime import date

from app import db
from app.config import settings
from app.embeddings import get_embedder
from app.models import Hit
from app.precedence import batch_in_scope, programme_in_scope, supersedes_targets
from app.vectorstore import get_collection

CLAUSE_IN_QUESTION = re.compile(r"\b(\d{1,2}\.\d{1,2})\b")


def _sources_by_id() -> dict[str, dict]:
    with db.session() as conn:
        return {r["doc_id"]: dict(r) for r in conn.execute("SELECT * FROM sources")}


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def label_hit(hit: Hit, as_of: date, programme: str | None, batch: int | None,
              sources: dict[str, dict]) -> Hit:
    m = hit.metadata
    start, end = _parse_date(m.get("effective_from")), _parse_date(m.get("effective_to"))
    if start and start > as_of:
        hit.status = "upcoming"
        return hit
    if end and end < as_of:
        hit.status = "expired"
        return hit
    if not programme_in_scope(m.get("scope_programmes", "ALL"), programme) or \
            not batch_in_scope(m.get("scope_batches", "ALL"), batch):
        hit.status = "out_of_scope"
        return hit
    # Step 2: is this document (or this clause) explicitly superseded by
    # another document that is itself in force and issued at level 1 or 2?
    for other in sources.values():
        if other["doc_id"] == hit.doc_id or other["authority_level"] > 2:
            continue
        o_start, o_end = _parse_date(other["effective_from"]), _parse_date(other["effective_to"])
        if (o_start and o_start > as_of) or (o_end and o_end < as_of):
            continue
        for doc_id, clause in supersedes_targets(other["supersedes"]):
            if doc_id != hit.doc_id:
                continue
            if clause is None or (hit.section or "").startswith(clause):
                hit.status = "superseded"
                hit.metadata = {**m, "superseded_by": other["doc_id"]}
                return hit
    hit.status = "applicable"
    return hit


def get_clause(doc_id: str, section: str, as_of: date, programme: str | None = None,
               batch: int | None = None) -> Hit | None:
    """Fetch the chunk for one clause directly, e.g. the source of a winning rule."""
    collection = get_collection()
    res = collection.get(where={"$and": [{"doc_id": doc_id}, {"section": section}]}, limit=1)
    if not res["ids"]:
        return None
    meta = res["metadatas"][0]
    hit = Hit(chunk_id=res["ids"][0], doc_id=doc_id, text=res["documents"][0], score=1.0,
              section=section, page=int(meta["page"]) if meta.get("page") else None, metadata=meta)
    return label_hit(hit, as_of, programme, batch, _sources_by_id())


def search(question: str, as_of: date, programme: str | None = None, batch: int | None = None,
           k: int | None = None, embedding_model: str | None = None,
           chunking: str | None = None) -> list[Hit]:
    """Vector search plus a small boost for exact clause numbers in the question."""
    collection = get_collection(embedding_model, chunking)
    if collection.count() == 0:
        return []
    k = k or settings.top_k
    vector = get_embedder(embedding_model).embed_query(question)
    res = collection.query(query_embeddings=[vector], n_results=min(k * 2, collection.count()))

    wanted_clauses = set(CLAUSE_IN_QUESTION.findall(question))
    sources = _sources_by_id()
    hits: list[Hit] = []
    for cid, text, meta, dist in zip(res["ids"][0], res["documents"][0],
                                     res["metadatas"][0], res["distances"][0]):
        score = 1.0 - float(dist)
        if meta.get("section") in wanted_clauses:
            score += 0.15  # the student named this clause explicitly
        hit = Hit(
            chunk_id=cid, doc_id=meta["doc_id"], text=text, score=round(score, 4),
            section=meta.get("section") or None, page=int(meta["page"]) if meta.get("page") else None,
            metadata=meta,
        )
        hits.append(label_hit(hit, as_of, programme, batch, sources))
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]
