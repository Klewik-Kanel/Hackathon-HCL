"""Chat UI for the assistant. It only calls the API over HTTP, never the code
directly, so what the judges see here is exactly what the API returns.

Sidebar: student login (POST /login -> token sent as "Authorization: Bearer"),
first-login password change, the as-of date, system health, and a document
upload box that calls POST /ingest. Passwords are never kept in the UI, only
the token, and only for this browser tab.
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
# Plain icons instead of emoji (Material Symbols, built into Streamlit).
USER_ICON = ":material/person:"
BOT_ICON = ":material/school:"

st.set_page_config(page_title="NSUT Student Assistant", layout="wide")
st.title("NSUT Student Services Assistant")
st.caption("Answers come only from official NSUT documents and your own records. Every fact is cited.")

for key, default in (("token", None), ("me", None), ("history", [])):
    st.session_state.setdefault(key, default)


def _err(r: httpx.Response) -> str:
    try:
        return r.json().get("detail", r.text)
    except ValueError:
        return r.text


with st.sidebar:
    st.subheader("Student login")
    me = st.session_state.me
    if me is None:
        with st.form("login"):
            sid = st.text_input("Student ID", placeholder="e.g. S1002")
            pw = st.text_input("Password", type="password")
            if st.form_submit_button("Log in", use_container_width=True):
                try:
                    r = httpx.post(f"{API_URL}/login", json={"student_id": sid, "password": pw}, timeout=30)
                except httpx.HTTPError as exc:
                    st.error(f"API not reachable: {exc}")
                else:
                    if r.status_code == 200:
                        st.session_state.token, st.session_state.me = r.json()["token"], r.json()
                        st.session_state.history = []
                        st.rerun()
                    st.error(_err(r))
        st.caption("Not logged in: you can still ask general policy questions.")
    else:
        st.success(f"Logged in as **{me['full_name']}** ({me['student_id']})")
        if me.get("must_change_password"):
            st.warning("You are using the starting password. Please set your own.")
        with st.expander("Change password", expanded=bool(me.get("must_change_password"))):
            with st.form("change_pw", clear_on_submit=True):
                cur = st.text_input("Current password", type="password")
                new = st.text_input("New password (min 8 characters)", type="password")
                new2 = st.text_input("Repeat new password", type="password")
                if st.form_submit_button("Update password"):
                    if new != new2:
                        st.error("The new passwords do not match.")
                    else:
                        r = httpx.post(f"{API_URL}/change-password", timeout=30, json={
                            "student_id": me["student_id"], "password": cur, "new_password": new})
                        if r.status_code == 200:
                            st.session_state.token, st.session_state.me = r.json()["token"], r.json()
                            st.rerun()
                        st.error(_err(r))
        if st.button("Log out", use_container_width=True):
            st.session_state.token = st.session_state.me = None
            st.session_state.history = []
            st.rerun()

    st.subheader("Session")
    as_of = st.date_input("As-of date", value=date.today(), help="Answer as if today were this date")

    st.subheader("System")
    try:
        health = httpx.get(f"{API_URL}/health", timeout=10).json()
        for name in ("api", "vector_store", "sqlite", "llm"):
            ok = health.get(name, {}).get("status") == "ok"
            st.markdown(f"{name}: " + (":green[**OK**]" if ok else ":red[**DOWN**]"))
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

for turn in st.session_state.history:
    st.chat_message("user", avatar=USER_ICON).write(turn["question"])
    with st.chat_message("assistant", avatar=BOT_ICON):
        st.write(turn["answer"])

question = st.chat_input("Ask about attendance, exams, grades, placement…")
if question:
    st.chat_message("user", avatar=USER_ICON).write(question)
    headers = {"Authorization": f"Bearer {st.session_state.token}"} if st.session_state.token else {}
    body = {"question": question, "as_of_date": as_of.isoformat()}
    with st.chat_message("assistant", avatar=BOT_ICON):
        try:
            with st.spinner("Checking the sources…"):
                resp = httpx.post(f"{API_URL}/ask", json=body, headers=headers, timeout=300)
        except httpx.HTTPError as exc:
            st.error(f"Request failed: {exc}")
            st.stop()
        if resp.status_code == 401 and st.session_state.token:
            st.session_state.token = st.session_state.me = None
            st.warning("Your session has expired. Please log in again.")
            st.stop()
        if resp.status_code != 200:
            st.warning(f"{resp.status_code}: {_err(resp)[:300]}")
            st.stop()
        data = resp.json()
        st.caption(f"Answer type: {TYPE_LABEL.get(data['answer_type'], data['answer_type'])} · trace `{data['trace_id']}`")
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
