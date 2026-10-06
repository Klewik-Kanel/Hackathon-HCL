"""Rule registry: every threshold a tool uses, each linked to its clause.

Tools never contain numbers like 75 or 30. They call ``get_rule`` with a
parameter name and the date, and get back the rule that applies, decided
by the precedence engine. So when a new circular changes a threshold,
behaviour changes with no code change.

How a rule gets into the registry
---------------------------------
1. Seed: data/rule_registry.csv, typed in by us and checked against the
   PDF pages (scripts/load_rules.py).
2. Live: when a document is ingested, ``extract_rules_for_doc`` asks the
   LLM for candidate rules, limited to parameters we already know. A
   candidate is accepted ONLY if its value appears verbatim in the clause
   it cites. Nothing is overwritten: the old row stays and precedence
   decides at question time.
3. Explicit: /ingest metadata may carry ``rules`` rows directly, which
   skips the LLM entirely.
"""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from app import db, llm
from app.config import settings
from app.models import Decision, Rule, SourceMetadata
from app.precedence import Candidate, resolve

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


class RuleNotFound(LookupError):
    pass


# ------------------------------------------------------------- reading --
def _candidates(parameter: str) -> list[Candidate]:
    sql = """
        SELECT r.*, COALESCE(s.authority_level, 3) AS authority_level,
               COALESCE(s.supersedes, '') AS doc_supersedes
        FROM rule_registry r LEFT JOIN sources s ON s.doc_id = r.source_doc_id
        WHERE r.parameter = ?
    """
    with db.session() as conn:
        rows = conn.execute(sql, (parameter,)).fetchall()
    return [
        Candidate(
            id=r["rule_id"], doc_id=r["source_doc_id"], value=r["value"],
            authority_level=int(r["authority_level"]),
            effective_from=date.fromisoformat(r["effective_from"]),
            effective_to=date.fromisoformat(r["effective_to"]) if r["effective_to"] else None,
            supersedes=r["doc_supersedes"], section=r["source_section"],
            scope_programmes=r["scope_programmes"], scope_batches=r["scope_batches"],
        )
        for r in rows
    ]


def get_rule_by_id(rule_id: str) -> Rule | None:
    with db.session() as conn:
        row = conn.execute("SELECT * FROM rule_registry WHERE rule_id = ?", (rule_id,)).fetchone()
    return Rule(**dict(row)) if row else None


def resolve_parameter(parameter: str, as_of: date, programme: str | None = None,
                      batch: int | None = None) -> tuple[Rule | None, Decision]:
    """Return (winning rule or None, the precedence decision with reasons)."""
    decision = resolve(_candidates(parameter), as_of, programme, batch)
    winner = get_rule_by_id(decision.winner) if decision.winner else None
    return winner, decision


def get_rule(parameter: str, as_of: date, programme: str | None = None,
             batch: int | None = None) -> Rule:
    """The single rule a tool should use. Raises if missing or unresolved."""
    rule, decision = resolve_parameter(parameter, as_of, programme, batch)
    if rule is None:
        why = "conflicting sources" if decision.unresolved else "no rule in force"
        raise RuleNotFound(f"{parameter}: {why}")
    return rule


def rule_number(rule: Rule) -> float:
    return float(rule.value)


def rule_bool(rule: Rule) -> bool:
    return rule.value.strip().lower() in {"true", "yes", "1"}


def known_parameters() -> list[str]:
    with db.session() as conn:
        return [r[0] for r in conn.execute("SELECT DISTINCT parameter FROM rule_registry ORDER BY 1")]


# ------------------------------------------------------------- writing --
RULE_COLUMNS = ["rule_id", "description", "parameter", "operator", "value", "scope_programmes",
                "scope_batches", "effective_from", "effective_to", "source_doc_id", "source_section"]


def upsert_rule(rule: Rule) -> None:
    row = rule.model_dump(mode="json")
    with db.session() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO rule_registry ({', '.join(RULE_COLUMNS)}) "
            f"VALUES ({', '.join(':' + c for c in RULE_COLUMNS)})",
            row,
        )


def load_rules_csv(path: Path) -> int:
    count = 0
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            row = {k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
            row["effective_to"] = row.get("effective_to") or None
            upsert_rule(Rule(**row))
            count += 1
    return count


# ---------------------------------------------- extraction from new docs --
class ExtractedRule(BaseModel):
    parameter: str
    operator: str
    value: str
    section: str
    quote: str = Field(description="exact words from the clause containing the value")


class ExtractedRules(BaseModel):
    rules: list[ExtractedRule] = Field(default_factory=list)


def _value_in_text(value: str, text: str) -> bool:
    """The number must literally appear in the clause (e.g. '80' in '80%')."""
    v = value.strip().rstrip("%")
    return bool(v) and re.search(rf"(?<![\d.]){re.escape(v)}(?![\d])", text) is not None


def extract_rules_for_doc(meta: SourceMetadata, chunks: list) -> int:
    """Ask the LLM which known thresholds this document sets; keep only verified ones."""
    params = known_parameters()
    if not params:
        return 0
    numbered = [c for c in chunks if not c.section.startswith("p.") and re.search(r"\d", c.text)]
    if not numbered:
        return 0
    evidence = "\n\n".join(f"[section {c.section}]\n{c.text[:1200]}" for c in numbered[:12])
    system = (PROMPTS_DIR / "extract_rules_v1.txt").read_text(encoding="utf-8")
    user = f"Known parameters: {', '.join(params)}\n\n<document>\n{evidence}\n</document>"
    try:
        if settings.mock_llm:
            from app import fallback

            found = ExtractedRules.model_validate(fallback.extract_rules(params, numbered))
        else:
            found = llm.complete_json(system, user, ExtractedRules)
    except llm.LLMError:
        return 0

    by_section = {c.section: c.text for c in numbered}
    added = 0
    for i, cand in enumerate(found.rules):
        clause_text = by_section.get(cand.section, "")
        if cand.parameter not in params or not _value_in_text(cand.value, clause_text):
            continue  # unknown parameter or value not in the cited clause: reject
        upsert_rule(Rule(
            rule_id=f"{meta.doc_id}-R{i + 1}",
            description=f"Extracted from {meta.doc_id} {cand.section}: {cand.quote[:150]}",
            parameter=cand.parameter, operator=cand.operator, value=cand.value.strip().rstrip("%"),
            scope_programmes=meta.scope_programmes, scope_batches=meta.scope_batches,
            effective_from=meta.effective_from, effective_to=meta.effective_to,
            source_doc_id=meta.doc_id, source_section=cand.section,
        ))
        added += 1
    return added


def add_rules_from_metadata(meta: SourceMetadata, rows: list[dict]) -> int:
    """Rules passed explicitly in /ingest metadata (no LLM involved)."""
    added = 0
    for i, row in enumerate(rows):
        upsert_rule(Rule(
            rule_id=row.get("rule_id") or f"{meta.doc_id}-M{i + 1}",
            description=row.get("description", f"From {meta.doc_id}"),
            parameter=row["parameter"], operator=row.get("operator", ">="), value=str(row["value"]),
            scope_programmes=row.get("scope_programmes", meta.scope_programmes),
            scope_batches=row.get("scope_batches", meta.scope_batches),
            effective_from=row.get("effective_from", meta.effective_from),
            effective_to=row.get("effective_to", meta.effective_to),
            source_doc_id=meta.doc_id, source_section=row.get("source_section", ""),
        ))
        added += 1
    return added
