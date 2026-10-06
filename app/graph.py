"""The /ask workflow as a LangGraph state machine.

    guard -> plan -> retrieve -> run_tools -> compose -> finalize
      |        |                      |
      +--------+---- early exits -----+-------> finalize

Only ``plan`` and ``compose`` call the LLM. Everything that decides an
outcome (identity, which document wins, eligibility, answer type,
citations) is plain code, so it is repeatable and testable.

Why one workflow and not several agents: routing is one classification
and the rest is deterministic; extra agents would add LLM calls (slow on
a laptop, more JSON that can break) without adding capability.
"""

from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app import audit, fallback, guard, llm, retrieval, rules
from app.config import settings
from app.text import content_words
from app.models import AnswerType, AppliedRule, AskResponse, Citation, Conflict, Hit, ToolCall
from app.tools import TOOL_DESCRIPTIONS, ToolContext, run_tool

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
NOT_FOUND = "I could not find this information in the authorised university sources."

# Rule parameters each tool depends on: their precedence is checked too.
TOOL_PARAMS: dict[str, list[str]] = {
    "check_exam_eligibility": ["min_attendance_pct"],
    "get_attendance": ["min_attendance_pct"],
    "check_backlog_path": ["supplementary_exam_available"],
    "check_placement_eligibility": ["max_active_backlogs_placement"],
    "check_degree_status": ["min_cgpa_degree"],
}

# Which rule-registry parameters a question touches, for conflict checks.
PARAM_TRIGGERS: dict[str, str] = {
    "min_attendance_pct": r"attendance",
    "supplementary_exam_available": r"supplementary|re-?appear",
    "top_category_threshold_tech_lpa": r"dream|a\+|categor|lpa|package",
    "max_active_backlogs_placement": r"placement",
    "min_cgpa_degree": r"\bdegree\b",
    "min_registrations_summer_semester": r"summer",
}


class State(TypedDict, total=False):
    question: str
    student_id: str | None
    as_of: date
    trace_id: str
    student: dict | None
    usage: llm.LLMUsage
    plan: fallback.Plan
    hits: list[Hit]
    evidence: list[dict]
    rule_decisions: list[dict]
    tool_results: list[dict]
    composed: fallback.Composed
    exit_type: AnswerType | None
    exit_message: str
    timings: dict[str, int]
    errors: list[str]


def _timed(name: str):
    def wrap(fn):
        def inner(state: State) -> State:
            started = time.perf_counter()
            out = fn(state)
            timings = dict(state.get("timings", {}))
            timings[name] = int((time.perf_counter() - started) * 1000)
            out["timings"] = timings
            return out
        return inner
    return wrap


# ----------------------------------------------------------------- nodes --
@_timed("guard")
def node_guard(state: State) -> State:
    result = guard.check(state["question"], state.get("student_id"))
    if not result.allowed:
        return {"exit_type": AnswerType.refused, "exit_message": result.reason, "student": result.student}
    return {"student": result.student}


def _llm_plan(state: State) -> fallback.Plan:
    tools = "\n".join(f"- {n}: {d}" for n, d in TOOL_DESCRIPTIONS.items())
    system = (PROMPTS / "plan_v1.txt").read_text(encoding="utf-8").replace("{tools}", tools)
    student = state.get("student")
    context = (f"Student programme: {student['programme']}, batch {student['batch_year']}"
               if student else "No student is logged in.")
    user = f"{context}\nQUESTION: {state['question']}"
    return llm.complete_json(system, user, fallback.Plan, state["usage"])


@_timed("plan")
def node_plan(state: State) -> State:
    errors = list(state.get("errors", []))
    student = state.get("student")
    if settings.mock_llm:
        plan = fallback.plan(state["question"], student)
    else:
        try:
            plan = _llm_plan(state)
        except llm.LLMError as exc:
            errors.append(f"plan: {exc}; used keyword fallback")
            plan = fallback.plan(state["question"], student)

    # Keep only real tools, and give tools the course the student named.
    plan.tools = [t for t in plan.tools if t.name in TOOL_DESCRIPTIONS]
    course = plan.course or fallback.find_course(state["question"], student["programme"] if student else None)
    for t in plan.tools:
        if t.name in {"get_attendance", "check_exam_eligibility", "get_results",
                      "check_course_pass", "check_backlog_path"} and not t.args.get("course_code") and course:
            t.args["course_code"] = course

    personal = bool(plan.tools) or plan.category.startswith("personal") or \
        (guard.looks_personal(state["question"]) and plan.category == "multi_step")
    if personal and not student:
        return {"plan": plan, "errors": errors, "exit_type": AnswerType.refused,
                "exit_message": "Please log in (X-Student-Id) to ask about your own records."}
    if plan.ambiguous:
        return {"plan": plan, "errors": errors, "exit_type": AnswerType.clarification_needed,
                "exit_message": plan.clarification_question or "Which course do you mean?"}
    if plan.category == "out_of_scope":
        return {"plan": plan, "errors": errors, "exit_type": AnswerType.not_found, "exit_message": NOT_FOUND}
    return {"plan": plan, "errors": errors}


def _citation_meta(hit: Hit) -> dict:
    m = hit.metadata
    return {"id": hit.chunk_id, "doc_id": hit.doc_id, "title": m.get("title", hit.doc_id),
            "section": hit.section, "page": hit.page, "version": m.get("version"),
            "effective_from": m.get("effective_from") or None, "text": hit.text,
            "score": hit.score, "status": hit.status}


@_timed("retrieve")
def node_retrieve(state: State) -> State:
    plan = state["plan"]
    student = state.get("student")
    programme = student["programme"] if student else None
    batch = student["batch_year"] if student else None
    as_of = state["as_of"]

    hits: list[Hit] = []
    if plan.needs_docs or not plan.tools:
        hits = retrieval.search(state["question"], as_of, programme, batch)

    # Rule-level precedence for any parameter this question touches.
    decisions = []
    q = state["question"].lower()
    params = _params_for_question(q)
    for t in plan.tools:
        params += [p for p in TOOL_PARAMS.get(t.name, []) if p not in params]
    for param in params:
        winner, decision = rules.resolve_parameter(param, as_of, programme, batch)
        if not decision.discarded and not decision.upcoming and winner is None:
            continue
        decisions.append({"parameter": param, "winner": winner, "decision": decision})
        # Clauses that lost on precedence must not be used as evidence.
        for lost in decision.discarded:
            for rid in lost.discarded.split(";"):
                r = rules.get_rule_by_id(rid)
                if r and not decision.unresolved:
                    for h in hits:
                        if h.doc_id == r.source_doc_id and h.status == "applicable":
                            h.status = "overridden"
        # Make sure the winning rule's own clause is in the evidence.
        if winner and not any(h.doc_id == winner.source_doc_id and h.section == winner.source_section
                              for h in hits):
            clause = retrieval.get_clause(winner.source_doc_id, winner.source_section, as_of, programme, batch)
            if clause:
                hits.insert(0, clause)

    # Clauses of the winning rules go first: they are the authoritative evidence.
    winners = {(d["winner"].source_doc_id, d["winner"].source_section) for d in decisions if d["winner"]}
    hits.sort(key=lambda h: ((h.doc_id, h.section) not in winners, -h.score))
    words = _content_words(state["question"])
    evidence = [{**_citation_meta(h), "winner": (h.doc_id, h.section) in winners} for h in hits
                if h.status == "applicable" and h.score >= settings.abstain_threshold
                and ((h.doc_id, h.section) in winners or _supports(words, h.text))][: settings.evidence_k]
    return {"hits": hits, "evidence": evidence, "rule_decisions": decisions}


def _params_for_question(q: str) -> list[str]:
    """Rule parameters a question is about: fixed triggers, plus a word match for any
    parameter in the registry (so rules added from a judge's new circular are checked too)."""
    found = [p for p, pattern in PARAM_TRIGGERS.items() if re.search(pattern, q)]
    words = _content_words(q)
    for param in rules.known_parameters():
        if param in found:
            continue
        tokens = {t[:6] for t in param.split("_") if len(t) > 3 and t not in {"pct", "marks"}}
        if len(tokens & words) >= 2:
            found.append(param)
    return found


def _content_words(text: str) -> set[str]:
    return content_words(text)


def _supports(question_words: set[str], text: str) -> bool:
    """Cheap lexical check: the chunk must share at least one content word with the question.

    Embeddings always return *something*; this stops a clause about grading
    being used to answer a question about Antarctic scholarships.
    """
    return bool(question_words & _content_words(text))


@_timed("run_tools")
def node_tools(state: State) -> State:
    plan = state["plan"]
    student = state.get("student")
    if not plan.tools or not student:
        return {"tool_results": []}
    ctx = ToolContext(student_id=student["student_id"], as_of=state["as_of"])
    results = []
    for t in plan.tools:
        started = time.perf_counter()
        res = run_tool(t.name, ctx, t.args)
        results.append({**res.model_dump(), "input": t.args,
                        "ms": int((time.perf_counter() - started) * 1000)})
    return {"tool_results": results}


def _rules_text(state: State) -> list[str]:
    out = []
    for d in state.get("rule_decisions", []):
        w = d["winner"]
        if w:
            unit = "%" if w.parameter.endswith("_pct") else ""
            out.append(f"{w.description} ({w.operator} {w.value}{unit}), per {w.source_doc_id} "
                       f"clause {w.source_section}, in force from {w.effective_from} [rule {w.rule_id}]")
    return out


def _numbers_ok(answer: str, state: State) -> bool:
    """Every number in the answer must appear in the evidence, tools or rules."""
    pool = " ".join(e["text"] for e in state.get("evidence", []))
    pool += json.dumps(state.get("tool_results", []), default=str) + " ".join(_rules_text(state))
    pool += state["question"] + str(state["as_of"])
    allowed = {float(n) for n in re.findall(r"\d+(?:\.\d+)?", pool)}
    for n in re.findall(r"\d+(?:\.\d+)?", answer):
        if float(n) not in allowed and float(n) > 2:  # tiny integers like "1 sentence" are fine
            return False
    return True


def _llm_compose(state: State, extra: str = "") -> fallback.Composed:
    ev = "\n".join(f'<evidence id="{e["id"]}" source="{e["title"]}" section="{e["section"]}" '
                   f'page="{e["page"]}">\n{e["text"]}\n</evidence>' for e in state["evidence"])
    tools = json.dumps([{k: t[k] for k in ("tool", "ok", "data", "assumptions", "error")}
                        for t in state.get("tool_results", [])], default=str)
    upcoming = [h.metadata.get("title", h.doc_id) + f" (from {h.metadata.get('effective_from')})"
                for h in state.get("hits", []) if h.status == "upcoming"]
    user = (f"QUESTION: {state['question']}\nAS-OF DATE: {state['as_of']}\n\n{ev}\n\n"
            f"<tool_results>{tools}</tool_results>\n<rules>{_rules_text(state)}</rules>\n"
            f"<upcoming>{upcoming}</upcoming>\nASSUMPTIONS: {state['plan'].assumptions}{extra}")
    system = (PROMPTS / "compose_v1.txt").read_text(encoding="utf-8")
    return llm.complete_json(system, user, fallback.Composed, state["usage"])


@_timed("compose")
def node_compose(state: State) -> State:
    evidence = state.get("evidence", [])
    ok_tools = [t for t in state.get("tool_results", []) if t["ok"]]
    decisions = state.get("rule_decisions", [])

    if any(d["decision"].unresolved for d in decisions):
        return {"exit_type": AnswerType.conflict_flagged}
    if not evidence and not ok_tools:
        return {"exit_type": AnswerType.not_found, "exit_message": NOT_FOUND}

    args = (state["question"], evidence, ok_tools, _rules_text(state), state["plan"].assumptions)
    errors = list(state.get("errors", []))
    if settings.mock_llm:
        composed = fallback.compose(*args)
    else:
        try:
            composed = _llm_compose(state)
            ids = {e["id"] for e in evidence}
            if not composed.insufficient and (not set(composed.cited_ids) <= ids
                                              or not _numbers_ok(composed.answer, state)):
                composed = _llm_compose(state, "\nYour previous answer cited unknown ids or a number "
                                               "not in the evidence. Use only the given ids and numbers.")
                if not set(composed.cited_ids) <= ids or not _numbers_ok(composed.answer, state):
                    errors.append("compose: failed grounding checks twice; used template answer")
                    composed = fallback.compose(*args)
        except llm.LLMError as exc:
            errors.append(f"compose: {exc}; used template answer")
            composed = fallback.compose(*args)
    if composed.insufficient and not ok_tools:
        return {"composed": composed, "errors": errors,
                "exit_type": AnswerType.not_found, "exit_message": NOT_FOUND}
    if composed.insufficient:
        composed = fallback.compose(*args)
    return {"composed": composed, "errors": errors}


def _to_citation(e: dict) -> Citation:
    return Citation(doc_id=e["doc_id"], title=e["title"], section=e["section"], page=e["page"],
                    version=e["version"], effective_from=e["effective_from"] or None)


@_timed("finalize")
def node_finalize(state: State) -> State:
    return {}


# ----------------------------------------------------------------- graph --
def _after(state: State) -> str:
    return "finalize" if state.get("exit_type") else "next"


def build_graph():
    g = StateGraph(State)
    g.add_node("guard", node_guard)
    g.add_node("plan", node_plan)
    g.add_node("retrieve", node_retrieve)
    g.add_node("run_tools", node_tools)
    g.add_node("compose", node_compose)
    g.add_node("finalize", node_finalize)
    g.set_entry_point("guard")
    g.add_conditional_edges("guard", _after, {"finalize": "finalize", "next": "plan"})
    g.add_conditional_edges("plan", _after, {"finalize": "finalize", "next": "retrieve"})
    g.add_edge("retrieve", "run_tools")
    g.add_edge("run_tools", "compose")
    g.add_edge("compose", "finalize")
    g.add_edge("finalize", END)
    return g.compile()


GRAPH = build_graph()


# --------------------------------------------------------------- respond --
def _build_response(state: State) -> AskResponse:
    exit_type = state.get("exit_type")
    evidence = state.get("evidence", [])
    tool_results = state.get("tool_results", [])
    decisions = state.get("rule_decisions", [])
    composed: fallback.Composed | None = state.get("composed")

    conflicts: list[Conflict] = []
    applied: list[AppliedRule] = []
    upcoming: list[Citation] = []
    seen_rules: set[str] = set()
    for d in decisions:
        conflicts += [c for c in d["decision"].discarded if c.step in (2, 3, 4, 5)]
        w = d["winner"]
        if w and w.rule_id not in seen_rules:
            applied.append(AppliedRule(rule_id=w.rule_id, value=f"{w.operator} {w.value}",
                                       source_doc_id=w.source_doc_id))
            seen_rules.add(w.rule_id)
        for rid in d["decision"].upcoming:
            r = rules.get_rule_by_id(rid)
            if r:
                upcoming.append(Citation(doc_id=r.source_doc_id, title=r.description,
                                         section=r.source_section, effective_from=r.effective_from))
    for t in tool_results:
        for rid in t.get("rule_ids", []):
            r = rules.get_rule_by_id(rid)
            if r and rid not in seen_rules:
                applied.append(AppliedRule(rule_id=rid, value=f"{r.operator} {r.value}",
                                           source_doc_id=r.source_doc_id))
                seen_rules.add(rid)
    words = _content_words(state["question"])
    for h in state.get("hits", []):
        if h.status == "upcoming" and h.score >= settings.abstain_threshold and _supports(words, h.text) \
                and not any(u.doc_id == h.doc_id for u in upcoming):
            upcoming.append(_to_citation(_citation_meta(h)))

    tools_invoked = [ToolCall(tool=t["tool"], input=t.get("input", {}),
                              output=t["data"] if t["ok"] else {"error": t["error"]}) for t in tool_results]
    citations: list[Citation] = []
    explanation = ""

    if exit_type == AnswerType.conflict_flagged:
        d = next(d for d in decisions if d["decision"].unresolved)
        last = d["decision"].discarded[-1]
        for rid in last.discarded.split(";"):
            r = rules.get_rule_by_id(rid)
            if r:
                hit = retrieval.get_clause(r.source_doc_id, r.source_section, state["as_of"])
                citations.append(_to_citation(_citation_meta(hit)) if hit else
                                 Citation(doc_id=r.source_doc_id, title=r.source_doc_id,
                                          section=r.source_section, effective_from=r.effective_from))
        answer = ("The authorised sources conflict on this point and the precedence policy cannot decide "
                  f"between them: {last.reason}. Please contact the issuing office for a ruling.")
        answer_type = AnswerType.conflict_flagged
    elif exit_type:
        answer, answer_type = state.get("exit_message", NOT_FOUND), exit_type
    else:
        ids = set(composed.cited_ids) if composed else set()
        cited = [e for e in evidence if e["id"] in ids] or evidence[:1]
        seen: set[tuple] = set()
        for e in cited:
            key = (e["doc_id"], e["section"])
            if key not in seen:
                citations.append(_to_citation(e))
                seen.add(key)
        answer = composed.answer if composed else NOT_FOUND
        explanation = composed.explanation if composed else ""
        answer_type = AnswerType.calculated if any(t["ok"] for t in tool_results) else AnswerType.retrieved_fact
        if upcoming and "upcoming" not in answer.lower():
            answer += " Upcoming change: " + "; ".join(
                f"{u.doc_id} takes effect on {u.effective_from}" for u in upcoming) + "."

    assumptions = [a for t in tool_results for a in t.get("assumptions", [])] + \
        (state["plan"].assumptions if state.get("plan") else [])
    if assumptions:
        explanation = (explanation + " Assumptions: " + "; ".join(dict.fromkeys(assumptions)) + ".").strip()

    return AskResponse(
        trace_id=state["trace_id"], answer=answer, answer_type=answer_type, citations=citations,
        tools_invoked=tools_invoked, applied_rules=applied, conflicts_detected=conflicts,
        explanation=explanation, as_of_date=state["as_of"], upcoming_changes=upcoming,
    )


def answer_question(question: str, student_id: str | None, as_of: date) -> AskResponse:
    """Entry point used by the API."""
    started = time.perf_counter()
    usage = llm.LLMUsage()
    state: State = {"question": question, "student_id": student_id, "as_of": as_of,
                    "trace_id": audit.new_trace_id(), "usage": usage, "timings": {}, "errors": []}
    final = GRAPH.invoke(state)
    response = _build_response(final)

    plan = final.get("plan")
    audit.write({
        "trace_id": response.trace_id,
        "student_id": final.get("student", {}).get("student_id") if final.get("student") else None,
        "question": guard.redact(question),
        "as_of_date": str(as_of),
        "question_category": plan.category if plan else None,
        "plan": plan.model_dump() if plan else None,
        "sources_retrieved": [{"doc_id": h.doc_id, "section": h.section, "page": h.page,
                               "score": h.score, "status": h.status} for h in final.get("hits", [])],
        "precedence_decision": [
            {"parameter": d["parameter"], "winner": d["winner"].rule_id if d["winner"] else None,
             "reasons": [c.reason for c in d["decision"].discarded],
             "upcoming": d["decision"].upcoming, "unresolved": d["decision"].unresolved}
            for d in final.get("rule_decisions", [])],
        "tools_invoked": [{"tool": t["tool"], "input": t.get("input"), "status": "ok" if t["ok"] else "error",
                           "output": t["data"] if t["ok"] else t["error"], "ms": t.get("ms")}
                          for t in final.get("tool_results", [])],
        "rules_applied": [r.model_dump() for r in response.applied_rules],
        "conflicts_detected": [c.model_dump() for c in response.conflicts_detected],
        "answer_type": response.answer_type.value,
        "model": settings.model_label,
        "prompt_versions": {"plan": "plan_v1", "compose": "compose_v1"},
        "llm_calls": usage.calls, "tokens_in": usage.tokens_in, "tokens_out": usage.tokens_out,
        "node_ms": final.get("timings", {}),
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "errors": final.get("errors", []),
    })
    return response

