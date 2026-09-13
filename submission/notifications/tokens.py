"""
Signed, single-use approval tokens for the email Approve/Reject links.

HMAC-SHA256 over a JSON payload (stdlib hmac/hashlib -- no new dependency).
Bound to the exact proposal_hash, so a link from a stale/revised proposal
fails closed automatically (extra scenario-7 protection, not just link
security). Single-use is enforced via a tiny local sqlite table, checked
only in consume_token() -- verify_token() alone (used for the GET confirm
page) never marks a token used, so link-prefetching email/security
scanners can't burn it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from dataclasses import dataclass

from submission.config import config

_DB_PATH = "submission/used_tokens.sqlite"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS used_tokens (jti TEXT PRIMARY KEY, used_at REAL NOT NULL)")
    conn.commit()
    return conn


def _require_secret() -> str:
    if not config.approval_token_secret:
        raise RuntimeError(
            "APPROVAL_TOKEN_SECRET is not set. Generate one with: "
            "python -c \"import secrets; print(secrets.token_hex(32))\" and put it in submission/.env"
        )
    return config.approval_token_secret


def make_token(case_id: str, proposal_hash: str, decision: str, approver: str) -> str:
    payload = {
        "jti": secrets.token_hex(16),
        "case_id": case_id,
        "proposal_hash": proposal_hash,
        "decision": decision,
        "approver": approver,
        "exp": time.time() + config.approval_token_ttl_minutes * 60,
    }
    raw = json.dumps(payload, sort_keys=True).encode()
    sig = hmac.new(_require_secret().encode(), raw, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(raw).decode() + "." + sig


@dataclass(frozen=True)
class TokenResult:
    ok: bool
    payload: dict | None = None
    error: str | None = None


def verify_token(token: str) -> TokenResult:
    """Signature + expiry only. Safe to call on every GET, including
    scanner prefetches -- does not consume the token."""
    try:
        raw_b64, sig = token.rsplit(".", 1)
        raw = base64.urlsafe_b64decode(raw_b64.encode())
    except (ValueError, base64.binascii.Error):
        return TokenResult(False, error="malformed token")

    expected_sig = hmac.new(_require_secret().encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return TokenResult(False, error="invalid signature")

    payload = json.loads(raw)
    if time.time() > payload["exp"]:
        return TokenResult(False, error="token expired")

    return TokenResult(True, payload=payload)


def consume_token(jti: str) -> bool:
    """Marks a token used. Call only when the decision is actually being
    executed (the POST handler), never on GET. Returns False if already used."""
    conn = _connect()
    try:
        conn.execute("INSERT INTO used_tokens (jti, used_at) VALUES (?, ?)", (jti, time.time()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()
