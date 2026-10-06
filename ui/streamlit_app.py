"""Chat UI for the assistant. It only calls the API over HTTP, never the code
directly, so what the judges see here is exactly what the API returns.

Sidebar: who is logged in (X-Student-Id), the as-of date, system health,
and a document upload box that calls POST /ingest.
"""

from __future__ import annotations

import json
import os
from datetime import date

import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")
TYPE_LABEL = {
    "retrieved_fact": "From the documents",
    "calculated": "Calculated from your records",
    "not_found": "Not in the authorised sources",
    "clarification_needed": "Needs clarification",
    "refused": "Not allowed",
    "conflict_flagged": "Sources conflict",
}

st.set_page_config(page_title="NSUT Student Assistant", page_icon="SSA", layout="wide")
st.title("NSUT Student Services Assistant")
st.caption("Answers come only from official NSUT documents and your own records. Every fact is cited.")

with st.sidebar:
    st.subheader("Session")
    student_id = st.text_input("Logged-in student ID", placeholder="e.g. S1002 (blank = not logged in)")
    as_of = st.date_input("As-of date", value=date.today(), help="Answer as if today were this date")

    st.subheader("System")
    try:
        health = httpx.get(f"{API_URL}/health", timeout=10).json()
        for name in ("api", "vector_store", "sqlite", "llm"):
            ok = health.get(name, {}).get("status") == "ok"
            st.write(("UP" if ok else "DOWN") + name)
        st.caption(f"Model: {health.get('llm', {}).get('model')} · chunks: "
                   f"{health.get('vector_store', {}).get('chunks')} · students: {health.get('sqlite', {}).get('students')}")
    except httpx.HTTPError:
        st.error(f"API not reachable at {API_URL}")

    with st.expander("Add a document (POST /ingest)"):
        upload = st.file_uploader("PDF, .md or .txt", type=["pdf", "md", "txt"])
        default_meta = {
            "doc_id": "NEW-DOC-01", "title": "", "issuer": "", "authority_level": 2, "doc_type": "circular",
            "version": "1", "effective_from": str(date.today()), "effective_to": None, "supersedes": "",
            "scope_programmes": "ALL", "scope_batches": "ALL", "provenance": "", "synthetic": "N",
        }
        meta_text = st.text_area("Metadata (Source Register fields)", json.dumps(default_meta, indent=2), height=260)
        if st.button("Ingest") and upload is not None:
            r = httpx.post(f"{API_URL}/ingest", files={"file": (upload.name, upload.getvalue())},
                           data={"metadata": meta_text}, timeout=300)
            (st.success if r.status_code == 200 else st.error)(r.json())

if "history" not in st.session_state:
    st.session_state.history = []

for turn in st.session_state.history:
    st.chat_message("user").write(turn["question"])
    with st.chat_message("assistant"):
        st.write(turn["answer"])

question = st.chat_input("Ask about attendance, exams, grades, placement…")
if question:
    st.chat_message("user").write(question)
    headers = {"X-Student-Id": student_id.strip()} if student_id.strip() else {}
    body = {"question": question, "as_of_date": as_of.isoformat()}
    with st.chat_message("assistant"):
        try:
            with st.spinner("Checking the sources…"):
                resp = httpx.post(f"{API_URL}/ask", json=body, headers=headers, timeout=300)
        except httpx.HTTPError as exc:
            st.error(f"Request failed: {exc}")
            st.stop()
        if resp.status_code != 200:
            st.warning(f"{resp.status_code}: {resp.text[:300]}")
            st.stop()
        data = resp.json()
        st.caption(f"{TYPE_LABEL.get(data['answer_type'], data['answer_type'])} · trace `{data['trace_id']}`")
        st.write(data["answer"])
        if data.get("explanation"):
            st.info(data["explanation"])
        if data.get("citations"):
            with st.expander(f"Sources ({len(data['citations'])})", expanded=True):
                for c in data["citations"]:
                    st.markdown(f"**{c['title']}** · `{c['doc_id']}` · clause {c.get('section')} · "
                                f"page {c.get('page')} · version {c.get('version')} · in force from {c.get('effective_from')}")
        if data.get("conflicts_detected"):
            with st.expander("Conflicts resolved"):
                for c in data["conflicts_detected"]:
                    st.write(f"Step {c['step']}: {c['reason']}")
        if data.get("upcoming_changes"):
            with st.expander("Upcoming changes"):
                for u in data["upcoming_changes"]:
                    st.write(f"{u['doc_id']} from {u.get('effective_from')}: {u['title']}")
        if data.get("tools_invoked"):
            with st.expander("Tools used"):
                st.json(data["tools_invoked"])
        if data.get("applied_rules"):
            with st.expander("Rules applied"):
                st.table(data["applied_rules"])
        with st.expander("Audit record"):
            st.json(httpx.get(f"{API_URL}/audit/{data['trace_id']}", timeout=30).json())
    st.session_state.history.append({"question": question, "answer": data["answer"]})
