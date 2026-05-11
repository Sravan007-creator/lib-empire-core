"""JWT token creation/verification and password hashing.

Uses PBKDF2-SHA256 (600K iterations) for passwords and HS256 for JWTs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt.exceptions import PyJWTError as JWTError

ALGORITHM = "HS256"
DEFAULT_EXPIRE_MINUTES = 60
PBKDF2_ITERATIONS = 600_000


def create_access_token(
    data: dict[str, Any],
    secret_key: str,
    expires_minutes: int = DEFAULT_EXPIRE_MINUTES,
) -> str:
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(UTC) + timedelta(minutes=expires_minutes)
    return jwt.encode(to_encode, secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str, secret_key: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
        if "exp" not in payload:
            raise ValueError("Token missing expiration")
        return payload
    except JWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    salt_b64 = base64.b64encode(salt).decode()
    digest_b64 = base64.b64encode(digest).decode()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt_b64}${digest_b64}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        _, iterations_str, salt_b64, digest_b64 = stored_hash.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations_str))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_mfa_challenge_token(
    user_id: int | str,
    secret_key: str,
    expires_seconds: int = 300,
) -> str:
    """Issue a short-lived JWT proving successful password auth but not full access.

    Used in the login → MFA challenge flow: when login returns
    ``mfa_required=true``, the client exchanges this token (plus a TOTP / backup
    code) at the API's ``/auth/mfa/verify`` endpoint to receive real
    access + refresh tokens.

    The token carries ``type="mfa_challenge"`` so callers can reject regular
    access tokens at the verify endpoint and vice versa.
    """
    expire = datetime.now(UTC) + timedelta(seconds=expires_seconds)
    payload = {"sub": str(user_id), "exp": expire, "type": "mfa_challenge"}
    return jwt.encode(payload, secret_key, algorithm=ALGORITHM)


def decode_mfa_challenge(token: str, secret_key: str) -> dict[str, Any] | None:
    """Decode and validate an MFA challenge token.

    Returns the payload if the token is signed, unexpired, and carries
    ``type="mfa_challenge"``. Returns ``None`` on any failure — callers map
    that to a 401 with a generic "invalid or expired MFA challenge" message
    rather than leaking which check failed.
    """
    try:
        payload = jwt.decode(token, secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != "mfa_challenge":
        return None
    if "sub" not in payload or "exp" not in payload:
        return None
    return payload


def validate_password_complexity(password: str) -> str | None:
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if not re.search(r"[A-Z]", password):
        return "Password must contain an uppercase letter"
    if not re.search(r"[a-z]", password):
        return "Password must contain a lowercase letter"
    if not re.search(r"\d", password):
        return "Password must contain a digit"
    return None
