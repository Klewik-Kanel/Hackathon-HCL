"""Load the hand-checked rule registry seed into SQLite.

    python scripts/load_rules.py                       # data/rule_registry.csv
    python scripts/load_rules.py --file other.csv

Every row links a threshold to the clause it came from. Before the demo,
open each cited clause in the PDF and confirm the value (see the
"verify" rows for the placement policy).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db, rules  # noqa: E402
from app.config import settings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, default=settings.data_dir / "rule_registry.csv")
    args = parser.parse_args(argv)
    db.init_db()
    count = rules.load_rules_csv(args.file)
    print(f"Loaded {count} rules from {args.file}")
    with db.session() as conn:
        orphans = [r[0] for r in conn.execute(
            "SELECT rule_id FROM rule_registry WHERE source_doc_id NOT IN (SELECT doc_id FROM sources)")]
    if orphans:
        print("Warning: rules whose source document is not ingested yet: " + ", ".join(orphans))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
