"""Compare retrieval configurations on the labelled questions (no LLM needed).

    python eval/compare_retrieval.py
    python eval/compare_retrieval.py --models BAAI/bge-small-en-v1.5 sentence-transformers/all-MiniLM-L6-v2

For every (chunking strategy x embedding model) it indexes the documents
into its own Chroma collection, then measures retrieval hit rate at top-4
and top-8: does the labelled (doc_id, section) come back? Fixed-size chunks
have no section, so for them a hit means the right document AND the page
containing the labelled clause.

Writes eval/retrieval_comparison.md. Use the numbers to justify the final
configuration in the README.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.config import settings  # noqa: E402
from app.ingest import chunk_clauses, ingest_document, read_pages  # noqa: E402
from app.models import SourceMetadata  # noqa: E402
from app.retrieval import search  # noqa: E402


def load_register(docs_dir: Path) -> list[tuple[Path, SourceMetadata]]:
    out = []
    with (settings.data_dir / "source_register.csv").open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            path = docs_dir / row.pop("file_name")
            if path.exists():
                meta = SourceMetadata.model_validate(
                    {k: (v or None) if k in {"effective_to", "retrieved_on"} else v for k, v in row.items()})
                out.append((path, meta))
    return out


def clause_pages(docs: list[tuple[Path, SourceMetadata]]) -> dict[tuple[str, str], int]:
    """(doc_id, clause) -> page, used to score fixed-size chunks fairly."""
    pages = {}
    for path, meta in docs:
        for c in chunk_clauses(read_pages(path)):
            pages.setdefault((meta.doc_id, c.section), c.page)
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+",
                        default=["BAAI/bge-small-en-v1.5", "sentence-transformers/all-MiniLM-L6-v2"])
    parser.add_argument("--chunking", nargs="+", default=["clause", "fixed"])
    parser.add_argument("--docs", type=Path, default=settings.docs_dir)
    parser.add_argument("--out", type=Path, default=ROOT / "eval" / "retrieval_comparison.md")
    args = parser.parse_args(argv)

    db.init_db()
    docs = load_register(args.docs)
    if not docs:
        print("No documents found; download them first.")
        return 1
    pages = clause_pages(docs)
    questions = [json.loads(line) for line in (ROOT / "eval" / "questions.jsonl").read_text().splitlines()
                 if line.strip()]
    labelled = [q for q in questions if q.get("expected_doc")]

    results = []
    for model in args.models:
        for chunking in args.chunking:
            for path, meta in docs:
                ingest_document(path, meta, strategy=chunking, embedding_model=model, extract_rules=False)
            scores = {}
            for k in (4, 8):
                hits_found = 0
                for q in labelled:
                    hits = search(q["question"], date.fromisoformat(q["as_of_date"]), k=k,
                                  embedding_model=model, chunking=chunking)
                    want_doc, want_sec = q["expected_doc"], q.get("expected_section")
                    want_page = pages.get((want_doc, want_sec))
                    ok = any(h.doc_id == want_doc and (h.section == want_sec if chunking == "clause"
                                                       else h.page == want_page) for h in hits)
                    hits_found += ok
                scores[k] = hits_found
            results.append((model, chunking, scores[4], scores[8]))
            print(f"{model:<45} {chunking:<7} hit@4 {scores[4]}/{len(labelled)}  hit@8 {scores[8]}/{len(labelled)}")

    lines = ["# Retrieval comparison", "",
             f"{len(labelled)} labelled questions; a hit = the labelled clause (or its page, for fixed chunks) "
             "is retrieved.", "",
             "| Embedding model | Chunking | Hit rate @4 | Hit rate @8 |", "| --- | --- | --- | --- |"]
    lines += [f"| {m} | {c} | {h4}/{len(labelled)} ({100 * h4 / len(labelled):.0f}%) | "
              f"{h8}/{len(labelled)} ({100 * h8 / len(labelled):.0f}%) |" for m, c, h4, h8 in results]
    best = max(results, key=lambda r: (r[2], r[3]))
    lines += ["", f"Best: **{best[0]}** with **{best[1]}** chunking."]
    args.out.write_text("\n".join(lines) + "\n")
    print(f"Written {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
