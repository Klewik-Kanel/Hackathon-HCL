"""Minimal chat UI. It only calls the API over HTTP, never the code directly,
so what the judges see in the UI is exactly what the API returns."""

from __future__ import annotations

import os
from datetime import date

import httpx
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000")

st.set_page_config(page_title="NSUT Student Assistant", page_icon="🎓")
st.title("NSUT Student Services Assistant")

with st.sidebar:
    st.subheader("Session")
    student_id = st.text_input("Logged-in student ID", placeholder="e.g. S1002")
    as_of = st.date_input("As-of date", value=date.today())
    st.divider()
    try:
        health = httpx.get(f"{API_URL}/health", timeout=10).json()
        for name in ("api", "vector_store", "sqlite", "llm"):
            ok = health.get(name, {}).get("status") == "ok"
            st.write(("🟢 " if ok else "🔴 ") + name)
    except httpx.HTTPError:
        st.error(f"API not reachable at {API_URL}")

question = st.chat_input("Ask about attendance, exams, grades, placement…")
if question:
    st.chat_message("user").write(question)
    headers = {"X-Student-Id": student_id} if student_id else {}
    body = {"question": question, "as_of_date": as_of.isoformat()}
    try:
        resp = httpx.post(f"{API_URL}/ask", json=body, headers=headers, timeout=180)
    except httpx.HTTPError as exc:
        st.error(f"Request failed: {exc}")
    else:
        with st.chat_message("assistant"):
            if resp.status_code != 200:
                st.warning(f"{resp.status_code}: {resp.json().get('detail')}")
            else:
                data = resp.json()
                st.caption(f"answer_type: {data['answer_type']} · trace {data['trace_id']}")
                st.write(data["answer"])
                if data.get("citations"):
                    with st.expander("Sources"):
                        for c in data["citations"]:
                            st.write(
                                f"**{c['title']}** ({c['doc_id']}) · section {c.get('section')} · "
                                f"page {c.get('page')} · v{c.get('version')} · from {c.get('effective_from')}"
                            )
                if data.get("tools_invoked"):
                    with st.expander("Tools used"):
                        st.json(data["tools_invoked"])
