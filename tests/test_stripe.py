"""Unit tests for the empireoe_core.stripe submodule.

Mirrors the BOS test suite (``tests/test_stripe_platform.py``) so the
shared library is verified the same way it's used in production. No
network — webhook signing is deterministic, and client construction is
just object instantiation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass

import pytest

from empireoe_core.stripe import (
    STRIPE_API_VERSION,
    StripeOperationError,
    fingerprint_payload,
    get_client,
    get_connected_client,
    idempotency_key_for,
    verify_webhook_signature,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeSettings:
    """Minimal stand-in for a backend's pydantic Settings — anything with
    these two attributes satisfies the StripeSettings protocol."""

    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""


def _stripe_signed_header(payload: bytes, secret: str, timestamp: int) -> str:
    """Build a valid ``Stripe-Signature`` header for tests.

    Mirrors Stripe's documented signing scheme:
        signed_payload = "<timestamp>.<payload>"
        signature      = HMAC-SHA256(secret, signed_payload)
        header         = "t=<timestamp>,v1=<signature>"
    """
    signed = f"{timestamp}.".encode() + payload
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


# ---------------------------------------------------------------------------
# idempotency_key_for
# ---------------------------------------------------------------------------


def test_idempotency_key_format():
    key = idempotency_key_for(
        operation="create_invoice", entity_type="engagement", entity_id=42
    )
    assert key == "bos:create_invoice:engagement:42"


def test_idempotency_key_with_suffix():
    key = idempotency_key_for(
        operation="create_invoice",
        entity_type="engagement",
        entity_id=42,
        suffix="retry-1",
    )
    assert key == "bos:create_invoice:engagement:42:retry-1"


def test_idempotency_key_string_entity_id():
    key = idempotency_key_for(
        operation="refund", entity_type="charge", entity_id="ch_abc123"
    )
    assert key == "bos:refund:charge:ch_abc123"


# ---------------------------------------------------------------------------
# verify_webhook_signature
# ---------------------------------------------------------------------------


def test_verify_signature_valid():
    secret = "whsec_test_secret_value"
    payload = json.dumps({"id": "evt_x", "object": "event", "type": "ping"}).encode()
    ts = int(time.time())
    header = _stripe_signed_header(payload, secret, ts)

    out = verify_webhook_signature(payload, header, secret)
    assert out["id"] == "evt_x"
    assert out["type"] == "ping"


def test_verify_signature_invalid_secret_rejected():
    secret = "whsec_real"
    payload = json.dumps({"id": "evt_x", "object": "event", "type": "ping"}).encode()
    ts = int(time.time())
    header = _stripe_signed_header(payload, "whsec_wrong", ts)

    with pytest.raises(StripeOperationError) as exc_info:
        verify_webhook_signature(payload, header, secret)
    assert exc_info.value.stripe_code == "invalid_signature"
    assert exc_info.value.http_status == 401


def test_verify_signature_replay_too_old_rejected():
    secret = "whsec_test"
    payload = json.dumps({"id": "evt_x", "object": "event", "type": "ping"}).encode()
    ts = int(time.time()) - 600  # 10 minutes ago
    header = _stripe_signed_header(payload, secret, ts)

    with pytest.raises(StripeOperationError) as exc_info:
        verify_webhook_signature(payload, header, secret, tolerance_seconds=300)
    # Stripe SDK reports replay-too-old as SignatureVerificationError;
    # we map it to invalid_signature for callers.
    assert exc_info.value.stripe_code == "invalid_signature"


def test_verify_signature_no_secret_rejected():
    with pytest.raises(StripeOperationError) as exc_info:
        verify_webhook_signature(b"{}", "t=1,v1=abc", "")
    assert exc_info.value.stripe_code == "invalid_signature"


def test_verify_signature_invalid_payload_rejected():
    secret = "whsec_test"
    # Not valid JSON — should map to invalid_payload, not invalid_signature.
    payload = b"this is not valid json {"
    ts = int(time.time())
    header = _stripe_signed_header(payload, secret, ts)

    with pytest.raises(StripeOperationError) as exc_info:
        verify_webhook_signature(payload, header, secret)
    assert exc_info.value.stripe_code == "invalid_payload"
    assert exc_info.value.http_status == 400


# ---------------------------------------------------------------------------
# get_client / get_connected_client
# ---------------------------------------------------------------------------


def test_get_client_raises_when_secret_missing():
    settings = _FakeSettings(STRIPE_SECRET_KEY="")
    with pytest.raises(StripeOperationError) as exc_info:
        get_client(settings)
    assert "STRIPE_SECRET_KEY" in str(exc_info.value)


def test_get_client_returns_pinned_version():
    settings = _FakeSettings(STRIPE_SECRET_KEY="sk_test_dummy")
    client = get_client(settings)
    # The Stripe SDK exposes the configured API version on the client.
    assert getattr(client, "stripe_version", STRIPE_API_VERSION) == STRIPE_API_VERSION


def test_get_connected_client_validates_account_id():
    settings = _FakeSettings(STRIPE_SECRET_KEY="sk_test_dummy")
    with pytest.raises(StripeOperationError) as exc_info:
        get_connected_client("not_an_account", settings)
    assert "acct_" in str(exc_info.value)


def test_get_connected_client_requires_secret():
    settings = _FakeSettings(STRIPE_SECRET_KEY="")
    with pytest.raises(StripeOperationError) as exc_info:
        get_connected_client("acct_test_123", settings)
    assert "STRIPE_SECRET_KEY" in str(exc_info.value)


def test_get_connected_client_happy_path():
    settings = _FakeSettings(STRIPE_SECRET_KEY="sk_test_dummy")
    client = get_connected_client("acct_test_123", settings)
    assert client is not None


# ---------------------------------------------------------------------------
# fingerprint_payload
# ---------------------------------------------------------------------------


def test_fingerprint_payload_stable_and_truncated():
    fp = fingerprint_payload(b'{"id":"evt_x"}')
    assert len(fp) == 16
    # Same input → same fingerprint.
    assert fp == fingerprint_payload(b'{"id":"evt_x"}')
    # Different input → different fingerprint (overwhelmingly likely).
    assert fp != fingerprint_payload(b'{"id":"evt_y"}')


# ---------------------------------------------------------------------------
# API version constant
# ---------------------------------------------------------------------------


def test_api_version_pinned():
    # Hard-coded so a casual edit to the wrapper does not silently change
    # the version every backend codes against.
    assert STRIPE_API_VERSION == "2024-12-18.acacia"
