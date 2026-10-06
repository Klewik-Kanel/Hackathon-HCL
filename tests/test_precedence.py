"""Unit tests for the Annex A precedence engine (pure function, no database)."""

from datetime import date

from app.precedence import Candidate, batch_in_scope, programme_in_scope, resolve

REG = Candidate(id="ATT-MIN-01", doc_id="REG", value="75", authority_level=1,
                effective_from=date(2024, 7, 1), section="7.2")
CIRC = Candidate(id="ATT-MIN-02", doc_id="CIRC", value="80", authority_level=2,
                 effective_from=date(2026, 8, 1), supersedes="REG#7.2", section="1")
FAQ = Candidate(id="FAQ-65", doc_id="FAQ", value="65", authority_level=4, effective_from=date(2026, 9, 15))


def test_brief_worked_example_supersession_wins():
    # Annex A.3: the circular explicitly supersedes the regulation clause.
    d = resolve([REG, CIRC, FAQ], date(2026, 10, 6))
    assert d.winner == "ATT-MIN-02"
    steps = {c.discarded: c.step for c in d.discarded}
    assert steps["ATT-MIN-01"] == 2
    assert steps["FAQ-65"] == 3


def test_not_yet_effective_document_is_upcoming_only():
    future = Candidate(**{**CIRC.__dict__, "effective_from": date(2027, 1, 1)})
    d = resolve([REG, future, FAQ], date(2026, 10, 6))
    assert d.winner == "ATT-MIN-01"
    assert d.upcoming == ["ATT-MIN-02"]


def test_higher_authority_beats_newer_lower_authority():
    d = resolve([REG, FAQ], date(2026, 10, 6))
    assert d.winner == "ATT-MIN-01"
    assert d.discarded[0].step == 3


def test_same_authority_later_date_wins():
    old = Candidate(id="A", doc_id="C1", value="10", authority_level=2, effective_from=date(2024, 1, 1))
    new = Candidate(id="B", doc_id="C2", value="12", authority_level=2, effective_from=date(2025, 1, 1))
    d = resolve([old, new], date(2026, 1, 1))
    assert d.winner == "B" and d.discarded[0].step == 4


def test_same_authority_same_date_different_values_is_unresolved():
    a = Candidate(id="A", doc_id="C1", value="10", authority_level=2, effective_from=date(2025, 1, 1))
    b = Candidate(id="B", doc_id="C2", value="12", authority_level=2, effective_from=date(2025, 1, 1))
    d = resolve([a, b], date(2026, 1, 1))
    assert d.unresolved and d.winner is None


def test_level_three_cannot_supersede():
    dept = Candidate(id="D", doc_id="DEPT", value="70", authority_level=3,
                     effective_from=date(2026, 1, 1), supersedes="REG")
    d = resolve([REG, dept], date(2026, 10, 6))
    assert d.winner == "ATT-MIN-01"  # step 3, not step 2


def test_unofficial_never_wins():
    forum = Candidate(id="F", doc_id="FORUM", value="50", authority_level=5, effective_from=date(2026, 9, 1))
    assert resolve([REG, forum], date(2026, 10, 6)).winner == "ATT-MIN-01"


def test_expired_and_out_of_scope_are_dropped():
    expired = Candidate(id="E", doc_id="OLD", value="70", authority_level=1,
                        effective_from=date(2010, 1, 1), effective_to=date(2019, 6, 30))
    ece_only = Candidate(id="X", doc_id="ECE", value="85", authority_level=1,
                         effective_from=date(2025, 1, 1), scope_programmes="B.Tech ECE")
    d = resolve([REG, expired, ece_only], date(2026, 10, 6), programme="B.Tech CSE")
    assert d.winner == "ATT-MIN-01"


def test_scope_helpers():
    assert programme_in_scope("ALL", "B.Tech CSE")
    assert programme_in_scope("B.Tech", "B.Tech CSE")
    assert not programme_in_scope("B.Tech ECE", "B.Tech CSE")
    assert batch_in_scope("2023+", 2024) and not batch_in_scope("2023+", 2022)
    assert batch_in_scope("2021-2023", 2022) and batch_in_scope("ALL", 2020)
