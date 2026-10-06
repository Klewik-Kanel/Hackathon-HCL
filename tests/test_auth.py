"""Student login: passwords, tokens, lockout, and that /ask trusts only the token."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app

client = TestClient(app)
TODAY = "2026-10-06"


@pytest.fixture(autouse=True)
def login_on(monkeypatch):
    monkeypatch.setenv("REQUIRE_LOGIN", "true")
    auth._failures.clear()


def login(sid, pw):
    return client.post("/login", json={"student_id": sid, "password": pw})


def ask(question, headers):
    return client.post("/ask", json={"question": question, "as_of_date": TODAY}, headers=headers)


def test_first_login_uses_demo_password_and_must_change():
    r = login("S1003", auth.demo_password())
    assert r.status_code == 200
    assert r.json()["must_change_password"] is True
    assert r.json()["student_id"] == "S1003"


def test_wrong_password_and_unknown_student_look_the_same():
    a, b = login("S1003", "wrong-pass"), login("S9999", "wrong-pass")
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_change_password_then_demo_password_stops_working():
    r = client.post("/change-password", json={"student_id": "S1004", "password": auth.demo_password(),
                                              "new_password": "my-new-pass-1"})
    assert r.status_code == 200 and r.json()["must_change_password"] is False
    assert login("S1004", auth.demo_password()).status_code == 401
    assert login("S1004", "my-new-pass-1").status_code == 200
    # the stored value is a salted hash, never the password
    from app import db
    with db.session() as conn:
        row = conn.execute("SELECT * FROM student_credentials WHERE student_id='S1004'").fetchone()
    assert "my-new-pass-1" not in (row["salt"] + row["pw_hash"])


def test_weak_new_password_rejected():
    r = client.post("/change-password", json={"student_id": "S1005", "password": auth.demo_password(),
                                              "new_password": "short"})
    assert r.status_code == 422


def test_lockout_after_five_failures():
    for _ in range(5):
        assert login("S1006", "nope-nope").status_code == 401
    assert login("S1006", auth.demo_password()).status_code == 429


def test_ask_uses_token_identity():
    token = login("S1002", auth.demo_password()).json()["token"]
    r = ask("What is my attendance in CS301?", {"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["answer_type"] != "refused"


def test_header_alone_is_rejected_when_login_required():
    assert ask("What is my attendance in CS301?", {"X-Student-Id": "S1002"}).status_code == 401


def test_header_must_match_token():
    token = login("S1002", auth.demo_password()).json()["token"]
    r = ask("What is my attendance?", {"Authorization": f"Bearer {token}", "X-Student-Id": "S1007"})
    assert r.status_code == 403


def test_tampered_or_expired_token_rejected(monkeypatch):
    token = login("S1002", auth.demo_password()).json()["token"]
    sid, exp, sig = token.split(".")
    forged = f"S1007.{exp}.{sig}"
    assert ask("What is my attendance?", {"Authorization": f"Bearer {forged}"}).status_code == 401
    monkeypatch.setenv("TOKEN_HOURS", "-1")
    old = auth.make_token("S1002")[0]
    assert ask("What is my attendance?", {"Authorization": f"Bearer {old}"}).status_code == 401


def test_policy_questions_work_without_login():
    r = ask("What is the minimum attendance required?", {})
    assert r.status_code == 200
