"""Tests for empireoe_core.auth.mfa + the MFA challenge token helpers."""

from __future__ import annotations

import time

import pyotp
import pytest
from cryptography.fernet import Fernet

from empireoe_core.auth import (
    create_mfa_challenge_token,
    decode_mfa_challenge,
    mfa,
)
from empireoe_core.auth.mfa import InvalidEncryptionKeyError


# ── Encryption ─────────────────────────────────────────────────────────────


def test_encrypt_decrypt_roundtrip():
    key = Fernet.generate_key().decode()
    secret = pyotp.random_base32()
    encrypted = mfa.encrypt_secret(secret, key)
    assert encrypted != secret
    assert mfa.decrypt_secret(encrypted, key) == secret


def test_decrypt_with_wrong_key_raises_invalid_encryption_key_error():
    key1 = Fernet.generate_key().decode()
    key2 = Fernet.generate_key().decode()
    encrypted = mfa.encrypt_secret("JBSWY3DPEHPK3PXP", key1)
    with pytest.raises(InvalidEncryptionKeyError):
        mfa.decrypt_secret(encrypted, key2)


def test_empty_key_raises_invalid_encryption_key_error():
    with pytest.raises(InvalidEncryptionKeyError):
        mfa.encrypt_secret("JBSWY3DPEHPK3PXP", "")


# ── TOTP ───────────────────────────────────────────────────────────────────


def test_new_secret_is_base32_and_unique():
    a = mfa.new_totp_secret()
    b = mfa.new_totp_secret()
    assert a != b
    # base32 alphabet check
    assert set(a).issubset(set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"))


def test_verify_totp_accepts_correct_code():
    secret = mfa.new_totp_secret()
    code = pyotp.TOTP(secret).now()
    assert mfa.verify_totp(secret, code) is True


def test_verify_totp_rejects_wrong_code():
    secret = mfa.new_totp_secret()
    assert mfa.verify_totp(secret, "000000") is False


def test_verify_totp_rejects_empty():
    secret = mfa.new_totp_secret()
    assert mfa.verify_totp(secret, "") is False
    assert mfa.verify_totp(secret, "   ") is False


def test_verify_totp_strips_whitespace():
    secret = mfa.new_totp_secret()
    code = pyotp.TOTP(secret).now()
    # User-entered codes often have a space in the middle (e.g. "123 456")
    spaced = code[:3] + " " + code[3:]
    assert mfa.verify_totp(secret, spaced) is True


def test_provisioning_uri_contains_account_and_issuer():
    uri = mfa.provisioning_uri("JBSWY3DPEHPK3PXP", "alice@example.com", "Empire Digital")
    assert "otpauth://totp/" in uri
    assert "alice%40example.com" in uri or "alice@example.com" in uri
    assert "Empire%20Digital" in uri or "Empire Digital" in uri


# ── Backup codes ───────────────────────────────────────────────────────────


def test_generate_backup_codes_returns_n_plain_and_n_hashed():
    plain, hashed = mfa.generate_backup_codes(5)
    assert len(plain) == 5
    assert len(hashed) == 5
    # Plain codes should look like xxxxxxxx-xxxxxxxx
    for code in plain:
        assert len(code) == 17 and code[8] == "-"


def test_generate_backup_codes_default_is_ten():
    plain, hashed = mfa.generate_backup_codes()
    assert len(plain) == 10


def test_consume_backup_code_matches_and_returns_remaining():
    plain, hashed = mfa.generate_backup_codes(3)
    matched, remaining = mfa.consume_backup_code(plain[1], hashed)
    assert matched is True
    assert len(remaining) == 2
    # the consumed entry is gone — the other two remain in original order
    assert remaining == [hashed[0], hashed[2]]


def test_consume_backup_code_no_match_returns_original_list():
    plain, hashed = mfa.generate_backup_codes(3)
    matched, remaining = mfa.consume_backup_code("not-a-real-code", hashed)
    assert matched is False
    assert remaining == hashed


def test_consume_backup_code_empty_input_returns_no_match():
    _, hashed = mfa.generate_backup_codes(3)
    matched, _ = mfa.consume_backup_code("", hashed)
    assert matched is False


def test_consumed_code_cannot_be_reused():
    plain, hashed = mfa.generate_backup_codes(3)
    _, after_first = mfa.consume_backup_code(plain[0], hashed)
    matched_again, _ = mfa.consume_backup_code(plain[0], after_first)
    assert matched_again is False


# ── MFA challenge token ────────────────────────────────────────────────────


def test_challenge_token_roundtrip():
    secret = "x" * 32
    token = create_mfa_challenge_token(42, secret)
    payload = decode_mfa_challenge(token, secret)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["type"] == "mfa_challenge"


def test_challenge_token_rejects_wrong_type():
    """An access token must not be accepted at the MFA verify endpoint."""
    from empireoe_core.auth import create_access_token

    secret = "x" * 32
    access = create_access_token({"sub": "42"}, secret)
    assert decode_mfa_challenge(access, secret) is None


def test_challenge_token_rejects_wrong_signature():
    secret1 = "x" * 32
    secret2 = "y" * 32
    token = create_mfa_challenge_token(42, secret1)
    assert decode_mfa_challenge(token, secret2) is None


def test_challenge_token_rejects_garbage():
    assert decode_mfa_challenge("not-a-jwt", "x" * 32) is None
    assert decode_mfa_challenge("", "x" * 32) is None


def test_challenge_token_expires():
    secret = "x" * 32
    token = create_mfa_challenge_token(42, secret, expires_seconds=1)
    time.sleep(1.1)
    assert decode_mfa_challenge(token, secret) is None
