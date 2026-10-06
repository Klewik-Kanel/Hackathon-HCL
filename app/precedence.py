"""Source Precedence Policy (brief Annex A) as one pure function.

``resolve`` takes the candidate values for ONE question (for example every
rule-registry row for ``min_attendance_pct``) and decides which applies on
``as_of``. It never calls the LLM, never reads the database, and returns
a reason for every candidate it drops, so the decision can be unit-tested
and explained step by step:

1. Applicability  in force on as_of and in the student's scope; documents
                  not yet in force go to ``upcoming``
2. Supersession   an explicit "supersedes" from a level-1/2 document wins
3. Authority      lower authority_level number wins, regardless of date
4. Recency        same authority: later effective_from wins
5. Unresolved     still more than one distinct value -> ``unresolved``

Level 5 (unofficial) content can never win.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.models import Conflict, Decision


@dataclass
class Candidate:
    id: str                     # rule_id (or doc_id for document-level checks)
    doc_id: str
    value: str
    authority_level: int
    effective_from: date
    effective_to: date | None = None
    supersedes: str = ""        # "DOC" or "DOC#11.2", ';'-separated
    section: str = ""
    scope_programmes: str = "ALL"
    scope_batches: str = "ALL"
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- scope --
def programme_in_scope(scope: str, programme: str | None) -> bool:
    """'ALL' covers everyone; 'B.Tech' covers 'B.Tech CSE'; lists use ; or ,."""
    if not scope or scope.strip().upper() == "ALL" or programme is None:
        return True
    items = [s.strip().lower() for s in re.split(r"[;,]", scope) if s.strip()]
    prog = programme.lower()
    return any(item in prog or prog in item for item in items)


def batch_in_scope(scope: str, batch: int | None) -> bool:
    """'ALL', '2023', '2023+' (2023 and later), '2021-2023', or a ; list."""
    if not scope or scope.strip().upper() == "ALL" or batch is None:
        return True
    for item in re.split(r"[;,]", scope):
        item = item.strip()
        if not item:
            continue
        if item.endswith("+") and item[:-1].isdigit() and batch >= int(item[:-1]):
            return True
        if "-" in item:
            lo, _, hi = item.partition("-")
            if lo.isdigit() and hi.isdigit() and int(lo) <= batch <= int(hi):
                return True
        if item.isdigit() and int(item) == batch:
            return True
    return False


def supersedes_targets(supersedes: str) -> list[tuple[str, str | None]]:
    """'A;B#11.2' -> [('A', None), ('B', '11.2')]."""
    out = []
    for item in (supersedes or "").split(";"):
        item = item.strip()
        if not item:
            continue
        doc, _, clause = item.partition("#")
        out.append((doc.strip(), clause.strip() or None))
    return out


def _supersedes(a: Candidate, b: Candidate) -> bool:
    if a.authority_level > 2:
        return False  # only level 1-2 documents may supersede (Annex A.2 step 2)
    for doc, clause in supersedes_targets(a.supersedes):
        if doc != b.doc_id:
            continue
        if clause is None or not b.section or b.section.startswith(clause):
            return True
    return False


# -------------------------------------------------------------- resolve --
def resolve(candidates: list[Candidate], as_of: date, programme: str | None = None,
            batch: int | None = None) -> Decision:
    decision = Decision()
    live: list[Candidate] = []

    # Step 1: applicability
    for c in candidates:
        if c.effective_from > as_of:
            decision.upcoming.append(c.id)
        elif c.effective_to and c.effective_to < as_of:
            decision.discarded.append(Conflict(kept="", discarded=c.id, step=1,
                                               reason=f"{c.id} expired on {c.effective_to}"))
        elif not programme_in_scope(c.scope_programmes, programme) or \
                not batch_in_scope(c.scope_batches, batch):
            decision.discarded.append(Conflict(kept="", discarded=c.id, step=1,
                                               reason=f"{c.id} does not cover this student's programme/batch"))
        else:
            live.append(c)

    # Level 5 never wins: drop it if anything better exists.
    if any(c.authority_level < 5 for c in live):
        for c in [c for c in live if c.authority_level == 5]:
            live.remove(c)
            decision.discarded.append(Conflict(kept="", discarded=c.id, step=3,
                                               reason=f"{c.id} is unofficial (level 5) and cannot override"))

    # Step 2: explicit supersession
    for a in list(live):
        for b in list(live):
            if a is not b and b in live and _supersedes(a, b):
                live.remove(b)
                decision.discarded.append(Conflict(kept=a.id, discarded=b.id, step=2,
                                                   reason=f"{a.doc_id} explicitly supersedes {b.doc_id}"
                                                          + (f"#{b.section}" if b.section else "")))

    if not live:
        return decision

    # Step 3: authority (lower number = higher authority)
    best_level = min(c.authority_level for c in live)
    for c in [c for c in live if c.authority_level > best_level]:
        live.remove(c)
        keeper = next(x for x in live if x.authority_level == best_level)
        decision.discarded.append(Conflict(
            kept=keeper.id, discarded=c.id, step=3,
            reason=f"{keeper.doc_id} (level {best_level}) outranks {c.doc_id} (level {c.authority_level})"))

    # Step 4: recency within the same authority level
    latest = max(c.effective_from for c in live)
    for c in [c for c in live if c.effective_from < latest]:
        # Only a real conflict if the value differs; same value = agreement.
        live.remove(c)
        keeper = next(x for x in live if x.effective_from == latest)
        if c.value != keeper.value:
            decision.discarded.append(Conflict(
                kept=keeper.id, discarded=c.id, step=4,
                reason=f"{keeper.doc_id} (from {keeper.effective_from}) is newer than "
                       f"{c.doc_id} (from {c.effective_from}) at the same authority"))

    # Step 5: unresolved if values still disagree
    values = {c.value for c in live}
    if len(values) > 1:
        decision.unresolved = True
        decision.winner = None
        decision.discarded.append(Conflict(
            kept="", discarded=";".join(c.id for c in live), step=5,
            reason="Same authority and same date with different values: "
                   + ", ".join(f"{c.doc_id}={c.value}" for c in live)))
        return decision

    decision.winner = sorted(live, key=lambda c: c.id)[0].id
    return decision
