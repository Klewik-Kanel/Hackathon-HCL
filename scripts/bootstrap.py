"""Set up everything from scratch in one command.

    python scripts/bootstrap.py

1. create the SQLite tables
2. register + index every document in data/source_register.csv
3. load the rule registry seed (data/rule_registry.csv)
4. load the student data (data/students/)

Run it once after downloading the documents, and again whenever the
documents, rules or students change. It is safe to re-run.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.config import settings  # noqa: E402
from scripts import ingest_all, load_rules, load_students  # noqa: E402


def main() -> int:
    db.init_db()
    print("1/3 Documents")
    ingest_all.main([])
    print("2/3 Rule registry")
    load_rules.main([])
    print("3/3 Students")
    report = load_students.load_dir(settings.data_dir / "students")
    print(f"    loaded {report['loaded']}, problems: {len(report['rejected'])}")
    print("Done. Start the API: uvicorn app.main:app --reload")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
