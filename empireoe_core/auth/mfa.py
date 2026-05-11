"""TOTP-based MFA primitives — pure-function building blocks.

Per Empire's polyrepo conventions, each consumer (recruitment-api, lwe-api,
digital-api, …) owns its own ``user_mfa`` table + persistence logic, since
the foreign key to ``users.id`` is repo-local. This module provides the
crypto / TOTP / backup-code primitives so the per-repo service is a thin
shell rather than a full re-implementation.

Typical per-repo wiring::

    # app/services/mfa_service.py
    from empireoe_core.auth import mfa as mfa_core

    async def begin_enrollment(db, *, user_id, email):
        secret = mfa_core.new_totp_secret()
        encrypted = mfa_core.encrypt_secret(secret, settings.MFA_ENCRYPTION_KEY)
        # … persist UserMFA(encrypted_secret=encrypted, confirmed=False) …
        return mfa_core.provisioning_uri(secret, email, settings.MFA_ISSUER_NAME), secret

    async def verify_code(db, *, user_id, code):
        state = await get_state(db, user_id)
        if state is None or not state.confirmed:
            return False
        secret = mfa_core.decrypt_secret(state.encrypted_secret,
                                         settings.MFA_ENCRYPTION_KEY)
        if mfa_core.verify_totp(secret, code):
            return True
        matched, new_hashes = mfa_core.consume_backup_code(code,
                                                          state.backup_code_hashes or [])
        if matched:
            state.backup_code_hashes = new_hashes
            await db.commit()
            return True
        return False
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import pyotp
from cryptography.fernet import Fernet, InvalidToken

from empireoe_core.auth.security import hash_password, verify_password

if TYPE_CHECKING:
    pass


__all__ = [
    "new_totp_secret",
    "provisioning_uri",
    "verify_totp",
    "encrypt_secret",
    "decrypt_secret",
    "generate_backup_codes",
    "consume_backup_code",
    "InvalidEncryptionKeyError",
]


class InvalidEncryptionKeyError(RuntimeError):
    """Raised when MFA_ENCRYPTION_KEY is missing or fails to decrypt an existing secret.

    This is a distinct exception from cryptography.fernet.InvalidToken so callers
    can give the operator an actionable error message ("did you rotate the key?")
    instead of a generic crypto failure.
    """


# ─────────────────────────────────────────────────────────────────────────────
# TOTP secret + URI helpers
# ─────────────────────────────────────────────────────────────────────────────


def new_totp_secret() -> str:
    """Generate a fresh base32-encoded TOTP secret suitable for an authenticator app."""
    return pyotp.random_base32()


def provisioning_uri(secret_b32: str, account_name: str, issuer_name: str) -> str:
    """Return the ``otpauth://`` URL that an authenticator app (Google Authenticator,
    Authy, 1Password, etc.) can consume to register the secret.

    The frontend typically renders this as a QR code.
    """
    return pyotp.TOTP(secret_b32).provisioning_uri(name=account_name, issuer_name=issuer_name)


def verify_totp(secret_b32: str, code: str, *, valid_window: int = 1) -> bool:
    """Verify a 6-digit TOTP ``code`` against ``secret_b32``.

    ``valid_window=1`` accepts the current code plus the immediately preceding
    and following 30-second windows — this absorbs clock skew between client
    and server while staying within RFC 6238's recommended tolerance.
    """
    code = (code or "").strip().replace(" ", "")
    if not code:
        return False
    return pyotp.TOTP(secret_b32).verify(code, valid_window=valid_window)


# ─────────────────────────────────────────────────────────────────────────────
# At-rest encryption of TOTP secrets
# ─────────────────────────────────────────────────────────────────────────────


def _fernet(key: str) -> Fernet:
    if not key:
        raise InvalidEncryptionKeyError(
            "MFA_ENCRYPTION_KEY is not configured. Generate one with "
            '`python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"`'
        )
    return Fernet(key.encode())


def encrypt_secret(plain: str, key: str) -> str:
    """Encrypt a TOTP secret with a Fernet key.

    ``key`` should be a 32-byte URL-safe-base64 string (Fernet's standard format),
    distinct from the JWT signing key — a JWT-key compromise must not also leak
    every TOTP secret.
    """
    return _fernet(key).encrypt(plain.encode()).decode()


def decrypt_secret(token: str, key: str) -> str:
    """Decrypt a Fernet-encrypted TOTP secret.

    Raises :class:`InvalidEncryptionKeyError` if decryption fails — the only
    benign reason for that is a key rotation that wasn't accompanied by a
    re-enrollment migration.
    """
    try:
        return _fernet(key).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise InvalidEncryptionKeyError(
            "MFA secret cannot be decrypted with the current MFA_ENCRYPTION_KEY. "
            "If the key was rotated, affected users must re-enrol."
        ) from exc


# ─────────────────────────────────────────────────────────────────────────────
# Backup codes
# ─────────────────────────────────────────────────────────────────────────────


def generate_backup_codes(n: int = 10) -> tuple[list[str], list[str]]:
    """Generate ``n`` one-time backup codes.

    Returns ``(plain, hashed)``:

    * ``plain``  — the codes to **show to the user once**, then forget.
                   Format: ``xxxxxxxx-xxxxxxxx`` (16 hex chars + a dash for readability,
                   ~64 bits of entropy each).
    * ``hashed`` — bcrypt hashes suitable for persistence. Verify a presented
                   code by iterating these via :func:`consume_backup_code`.
    """
    plain = [f"{secrets.token_hex(4)}-{secrets.token_hex(4)}" for _ in range(n)]
    hashed = [hash_password(c) for c in plain]
    return plain, hashed


def consume_backup_code(presented: str, hashed_codes: list[str]) -> tuple[bool, list[str]]:
    """Verify ``presented`` against a list of bcrypt-hashed backup codes.

    Returns ``(matched, remaining)``:

    * If a code matches, ``matched=True`` and ``remaining`` is the hashed-codes
      list **with the consumed entry removed** — store that back so the code
      can't be reused.
    * If no code matches, ``matched=False`` and ``remaining`` is the original
      list unchanged.

    Uses constant-time comparison via bcrypt.
    """
    presented = (presented or "").strip().replace(" ", "")
    if not presented:
        return False, list(hashed_codes)
    remaining = list(hashed_codes)
    for i, h in enumerate(remaining):
        if verify_password(presented, h):
            remaining.pop(i)
            return True, remaining
    return False, remaining
