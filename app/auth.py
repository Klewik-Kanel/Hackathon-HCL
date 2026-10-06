"""Student login: passwords, sign-in tokens and the "who is asking" check.

How it works
------------
* Passwords are never stored. We store a random salt and a PBKDF2-SHA256
  hash (200,000 rounds) in the ``student_credentials`` table.
* A student who has never set a password (for example a judge's test
  student loaded through /admin/load-students) signs in with the demo
  starting password (``DEMO_PASSWORD``, default ``nsut@123``) and is asked
  to choose their own. The demo password is refused once they have.
* A successful login returns a signed token: ``<student_id>.<expiry>.<hmac>``.
  The HMAC key is ``AUTH_SECRET`` or, if unset, a random key saved in
  ``data/.auth_secret``. Tokens last ``TOKEN_HOURS`` (default 8).
* /ask takes the student from the token only. The ``X-Student-Id`` header
  from the brief is still accepted when ``REQUIRE_LOGIN=false`` so the
  original API contract (and judge scripts written for it) keeps working.
* Five wrong passwords for one student ID lock that ID for five minutes.

Asking without logging in is still allowed: general policy questions work,
personal questions get "please log in" (the guard decides that).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from datetime import datetime, timezone

from app import db
from app.config import settings

ITERATIONS = 200_000
MAX_FAILURES = 5
LOCK_SECONDS = 300
MIN_PASSWORD_LEN = 8

_failures: dict[str, list[float]] = {}
_lock = threading.Lock()


class AuthError(Exception):
    """Raised with an HTTP status code and a message safe to show the user."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# ------------------------------------------------------------ settings --
def login_required() -> bool:
    """Read live so tests can switch it per test."""
    return os.getenv("REQUIRE_LOGIN", "true").strip().lower() in {"1", "true", "yes", "on"}


def demo_password() -> str:
    return os.getenv("DEMO_PASSWORD", "nsut@123")


def _token_hours() -> float:
    return float(os.getenv("TOKEN_HOURS", "8"))


def _secret() -> bytes:
    env = os.getenv("AUTH_SECRET")
    if env:
        return env.encode()
    path = settings.data_dir / ".auth_secret"
    if not path.exists():
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip().encode()


# ------------------------------------------------------------ hashing --
def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return salt.hex(), digest.hex()


def _verify(password: str, salt_hex: str, hash_hex: str) -> bool:
    _, digest = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(digest, hash_hex)


# ------------------------------------------------------------- tokens --
def make_token(student_id: str) -> tuple[str, int]:
    expires = int(time.time() + _token_hours() * 3600)
    payload = f"{student_id}.{expires}"
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}", expires


def read_token(token: str) -> str:
    """Return the student ID inside a valid token, else raise AuthError(401)."""
    try:
        student_id, expires, sig = token.split(".")
        expected = base64.urlsafe_b64encode(
            hmac.new(_secret(), f"{student_id}.{expires}".encode(), hashlib.sha256).digest()
        ).decode().rstrip("=")
    except ValueError as exc:
        raise AuthError(401, "Invalid sign-in token. Please log in again.") from exc
    if not hmac.compare_digest(sig, expected):
        raise AuthError(401, "Invalid sign-in token. Please log in again.")
    if int(expires) < time.time():
        raise AuthError(401, "Your session has expired. Please log in again.")
    return student_id


# -------------------------------------------------------------- login --
def _locked(student_id: str) -> bool:
    now = time.time()
    with _lock:
        recent = [t for t in _failures.get(student_id, []) if now - t < LOCK_SECONDS]
        _failures[student_id] = recent
        return len(recent) >= MAX_FAILURES


def _record_failure(student_id: str) -> None:
    with _lock:
        _failures.setdefault(student_id, []).append(time.time())


def login(student_id: str, password: str) -> dict:
    student_id = student_id.strip().upper()
    if _locked(student_id):
        raise AuthError(429, "Too many wrong attempts. Try again in 5 minutes.")
    with db.session() as conn:
        student = conn.execute("SELECT full_name FROM students WHERE student_id = ?", (student_id,)).fetchone()
        cred = conn.execute("SELECT salt, pw_hash FROM student_credentials WHERE student_id = ?",
                            (student_id,)).fetchone()
    # Same message for "no such student" and "wrong password" so IDs can't be probed.
    if student is None:
        _record_failure(student_id)
        raise AuthError(401, "Wrong student ID or password.")
    if cred is None:
        ok, must_change = hmac.compare_digest(password, demo_password()), True
    else:
        ok, must_change = _verify(password, cred["salt"], cred["pw_hash"]), False
    if not ok:
        _record_failure(student_id)
        raise AuthError(401, "Wrong student ID or password.")
    with _lock:
        _failures.pop(student_id, None)
    token, expires = make_token(student_id)
    return {"token": token, "student_id": student_id, "full_name": student["full_name"],
            "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat(),
            "must_change_password": must_change}


def change_password(student_id: str, current: str, new: str) -> None:
    login(student_id, current)  # re-checks the current password (and the lockout)
    if len(new) < MIN_PASSWORD_LEN:
        raise AuthError(422, f"New password must be at least {MIN_PASSWORD_LEN} characters.")
    if new == demo_password():
        raise AuthError(422, "Choose a password different from the starting password.")
    salt, digest = hash_password(new)
    with db.session() as conn:
        conn.execute(
            "INSERT INTO student_credentials (student_id, salt, pw_hash, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (student_id) DO UPDATE SET salt = excluded.salt, pw_hash = excluded.pw_hash, "
            "updated_at = excluded.updated_at",
            (student_id.strip().upper(), salt, digest, datetime.now(timezone.utc).isoformat()),
        )


# ------------------------------------------------- who is asking (/ask) --
def resolve_student(authorization: str | None, x_student_id: str | None) -> str | None:
    """Decide which student a request speaks for. None = not logged in."""
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthError(401, "Use 'Authorization: Bearer <token>' from POST /login.")
        student_id = read_token(token.strip())
        if x_student_id and x_student_id.strip().upper() != student_id:
            raise AuthError(403, "X-Student-Id does not match the logged-in student.")
        return student_id
    if x_student_id:
        if login_required():
            raise AuthError(401, "Please log in (POST /login) to ask about your own records.")
        return x_student_id.strip()
    return None
