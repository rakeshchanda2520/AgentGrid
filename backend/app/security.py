"""Passwords, tokens, encryption, webhook signatures, PII detection, rate limiting."""

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings

_ph = PasswordHasher()


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except VerifyMismatchError:
        return False


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def access_token(user_id: UUID) -> str:
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=settings().access_token_minutes)
    return jwt.encode({"sub": str(user_id), "iat": now, "exp": exp, "typ": "access"}, settings().jwt_secret, "HS256")


def decode_access(token: str) -> UUID | None:
    try:
        data = jwt.decode(token, settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return UUID(data["sub"]) if data.get("typ") == "access" else None


def new_secret(prefix: str = "", n: int = 32) -> str:
    return prefix + secrets.token_urlsafe(n)


# ---- encryption: per-tenant keys derived from the master key (KMS-wrapped data keys in the target) ----


@lru_cache(maxsize=1024)
def _fernet(tenant_id: str) -> Fernet:
    master = settings().master_key or settings().jwt_secret  # ponytail: dev fallback; prod sets MASTER_KEY
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"agentgrid", info=tenant_id.encode()).derive(master.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(tenant_id: UUID | str, value: Any) -> bytes:
    return _fernet(str(tenant_id)).encrypt(json.dumps(value).encode())


def decrypt(tenant_id: UUID | str, blob: bytes | None) -> Any:
    if not blob:
        return None
    return json.loads(_fernet(str(tenant_id)).decrypt(bytes(blob)))


# ---- webhook signatures ----


def verify_meta_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """Meta signs webhook bodies: X-Hub-Signature-256: sha256=<hex hmac of raw body with app secret>."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def sign_payload(secret: str, body: bytes, ts: int | None = None) -> tuple[str, str]:
    """Outbound webhook signature: HMAC-SHA256 over '<ts>.<body>' (replay-safe with the timestamp)."""
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return str(ts), f"sha256={sig}"


# ---- PII detection (the LLM only ever sees placeholders like <PHONE_1>) ----

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_AADHAAR = re.compile(r"\b[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}\b")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_PHONE = re.compile(r"(?<![\w+])(?:\+?91[ -]?)?[6-9]\d{4}[ -]?\d{5}\b|(?<![\w+])\+\d{1,3}[ -]?\d(?:[ -]?\d){6,12}\b")

_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def _verhoeff_ok(num: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def _luhn_ok(num: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(num)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def find_pii(text: str) -> list[tuple[int, int, str, str]]:
    """Non-overlapping (start, end, kind, value) spans, most specific detector first."""
    found: list[tuple[int, int, str, str]] = []

    def free(s: int, e: int) -> bool:
        return all(e <= fs or s >= fe for fs, fe, _, _ in found)

    def add(pattern: re.Pattern[str], kind: str, check=None) -> None:
        for m in pattern.finditer(text):
            digits = re.sub(r"\D", "", m.group())
            if (check is None or check(digits)) and free(m.start(), m.end()):
                found.append((m.start(), m.end(), kind, m.group()))

    add(_EMAIL, "EMAIL")
    add(_CARD, "CARD", lambda d: 13 <= len(d) <= 19 and _luhn_ok(d))
    add(_AADHAAR, "AADHAAR", lambda d: len(d) == 12 and _verhoeff_ok(d))
    add(_PAN, "PAN")
    add(_PHONE, "PHONE")
    return sorted(found)


def normalize_pii(kind: str, value: str) -> str:
    return value.lower().strip() if kind == "EMAIL" else re.sub(r"[^\dA-Z+]", "", value.upper())


TOKEN_RE = re.compile(r"<(EMAIL|PHONE|CARD|AADHAAR|PAN)_(\d+)>")


# ---- in-memory rate limiting (ponytail: single process; Redis counters in the target) ----

_hits: dict[str, deque[float]] = defaultdict(deque)


def rate_limited(key: str, limit: int, window_s: float = 60.0) -> bool:
    now = time.monotonic()
    q = _hits[key]
    while q and q[0] <= now - window_s:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False
