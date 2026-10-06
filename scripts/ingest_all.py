"""Index every document listed in data/source_register.csv.

    python scripts/ingest_all.py                 # default chunking/embeddings from .env
    python scripts/ingest_all.py --chunking fixed --embedding-model sentence-transformers/all-MiniLM-L6-v2

Files are looked up in data/docs/ by the ``file_name`` column. Missing
files are reported and skipped (download them first: docs/DATA_SOURCES.md).
Safe to re-run: each document's old chunks are replaced.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.config import settings  # noqa: E402
from app.ingest import ingest_document, upsert_source  # noqa: E402
from app.models import SourceMetadata  # noqa: E402


def read_register(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--register", type=Path, default=settings.data_dir / "source_register.csv")
    parser.add_argument("--docs", type=Path, default=settings.docs_dir)
    parser.add_argument("--chunking", default=None, help="clause (default) or fixed")
    parser.add_argument("--embedding-model", default=None)
    parser.add_argument("--extract", action="store_true",
                        help="also ask the LLM for rules (off by default: the seed registry has them)")
    args = parser.parse_args(argv)

    db.init_db()
    total, missing = 0, []
    for row in read_register(args.register):
        file_name = row.pop("file_name", "")
        path = args.docs / file_name
        meta = SourceMetadata.model_validate({k: (v or None) if k in {"effective_to", "retrieved_on"} else v
                                              for k, v in row.items()})
        if not file_name or not path.exists():
            # Register it anyway, so rule precedence knows its authority level.
            upsert_source(meta, file_name, 0)
            missing.append(f"{row['doc_id']} ({file_name or 'no file_name'})")
            continue
        result = ingest_document(path, meta, strategy=args.chunking, embedding_model=args.embedding_model,
                                 extract_rules=args.extract)
        total += result.chunks_indexed
        print(f"  {meta.doc_id:<26} {result.chunks_indexed:>4} chunks  {result.status}")
    print(f"Indexed {total} chunks.")
    if missing:
        print("Missing files (skipped): " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
