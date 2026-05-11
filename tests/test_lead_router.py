"""Tests for empireoe_core.lead_router — v0.5 Meta webhook upgrade."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from empireoe_core.lead_router import (
    Assignee,
    MetaWebhookConfig,
    classify_inbound_lead,
    create_meta_webhook_router,
    route_lead,
    should_notify,
    verify_meta_signature,
)


# ── Assignment tests (existing) ────────────────────────────────────────────────

def test_route_lead_recruitment():
    assignee = route_lead("recruitment")
    assert isinstance(assignee, Assignee)


def test_route_lead_study_abroad_goes_to_default():
    a1 = route_lead("study_abroad")
    a2 = route_lead("general")
    assert a1.name == a2.name  # both default


def test_should_notify_true():
    assert should_notify("recruitment") is True
    assert should_notify("study_abroad") is True
    assert should_notify("agent") is True


def test_should_notify_false():
    assert should_notify("general") is False
    assert should_notify("unknown") is False


# ── verify_meta_signature ──────────────────────────────────────────────────────

def _make_sig(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_verify_signature_valid():
    body = b'{"test": true}'
    secret = "mysecret"
    sig = _make_sig(secret, body)
    assert verify_meta_signature(body, sig, secret) is True


def test_verify_signature_wrong_secret():
    body = b'{"test": true}'
    sig = _make_sig("correct_secret", body)
    assert verify_meta_signature(body, sig, "wrong_secret") is False


def test_verify_signature_empty_secret_rejects():
    body = b'{"test": true}'
    sig = _make_sig("secret", body)
    # Security: must reject when app_secret is empty
    assert verify_meta_signature(body, sig, "") is False


def test_verify_signature_tampered_body():
    body = b'{"test": true}'
    secret = "mysecret"
    sig = _make_sig(secret, body)
    tampered = b'{"test": false}'
    assert verify_meta_signature(tampered, sig, secret) is False


# ── MetaWebhookConfig ──────────────────────────────────────────────────────────

def test_config_from_env(monkeypatch):
    monkeypatch.setenv("META_APP_SECRET", "testsecret")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "wa_verify")
    monkeypatch.setenv("INSTAGRAM_VERIFY_TOKEN", "ig_verify")
    cfg = MetaWebhookConfig.from_env()
    assert cfg.app_secret == "testsecret"
    assert cfg.wa_verify_token == "wa_verify"
    assert cfg.ig_verify_token == "ig_verify"


# ── classify_inbound_lead ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_classify_no_key_returns_fallback():
    result = await classify_inbound_lead("I want a job in Dubai", anthropic_key="")
    assert result["category"] == "general"
    assert len(result["reply"]) > 0


@pytest.mark.asyncio
async def test_classify_api_error_returns_fallback():
    with patch("empireoe_core.lead_router.httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.is_success = False
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.post = AsyncMock(return_value=mock_resp)

        result = await classify_inbound_lead("Hi", anthropic_key="fake_key")
    assert result["category"] == "general"


@pytest.mark.asyncio
async def test_classify_valid_response():
    mock_payload = {
        "content": [{"text": '{"category":"recruitment","reply":"Hello, what role?"}'}]
    }
    with patch("empireoe_core.lead_router.httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = mock_payload
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.post = AsyncMock(return_value=mock_resp)

        result = await classify_inbound_lead("I want job in UAE", anthropic_key="key")
    assert result["category"] == "recruitment"
    assert result["reply"] == "Hello, what role?"


@pytest.mark.asyncio
async def test_classify_invalid_category_coerced_to_general():
    mock_payload = {
        "content": [{"text": '{"category":"spam","reply":"Hello"}'}]
    }
    with patch("empireoe_core.lead_router.httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = mock_payload
        mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value.post = AsyncMock(return_value=mock_resp)

        result = await classify_inbound_lead("Buy cheap watches", anthropic_key="key")
    assert result["category"] == "general"


# ── create_meta_webhook_router ─────────────────────────────────────────────────

def _build_app(config: MetaWebhookConfig, on_lead=None) -> TestClient:
    app = FastAPI()
    router = create_meta_webhook_router(config=config, on_lead=on_lead)
    app.include_router(router)
    return TestClient(app)


def _wa_body_with_sig(secret: str, payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    sig = _make_sig(secret, body)
    return body, sig


SECRET = "test_app_secret"
CFG = MetaWebhookConfig(
    app_secret=SECRET,
    ig_verify_token="ig_tok",
    wa_verify_token="wa_tok",
)


def test_ig_hub_challenge_valid():
    client = _build_app(CFG)
    resp = client.get(
        "/webhooks/meta/instagram",
        params={"hub.mode": "subscribe", "hub.verify_token": "ig_tok", "hub.challenge": "abc123"},
    )
    assert resp.status_code == 200
    assert resp.text == "abc123"


def test_ig_hub_challenge_wrong_token():
    client = _build_app(CFG)
    resp = client.get(
        "/webhooks/meta/instagram",
        params={"hub.mode": "subscribe", "hub.verify_token": "WRONG", "hub.challenge": "abc"},
    )
    assert resp.status_code == 403


def test_wa_hub_challenge_valid():
    client = _build_app(CFG)
    resp = client.get(
        "/webhooks/meta/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "wa_tok", "hub.challenge": "xyz"},
    )
    assert resp.status_code == 200
    assert resp.text == "xyz"


def test_ig_webhook_invalid_signature():
    client = _build_app(CFG)
    resp = client.post(
        "/webhooks/meta/instagram",
        content=b'{"entry":[]}',
        headers={"x-hub-signature-256": "sha256=badsig"},
    )
    assert resp.status_code == 401


def test_wa_webhook_invalid_signature():
    client = _build_app(CFG)
    body, _ = _wa_body_with_sig(SECRET, {"entry": []})
    resp = client.post(
        "/webhooks/meta/whatsapp",
        content=body,
        headers={"x-hub-signature-256": "sha256=badsig"},
    )
    assert resp.status_code == 401


def test_wa_webhook_valid_sig_returns_ok():
    client = _build_app(CFG)
    payload = {"entry": []}
    body, sig = _wa_body_with_sig(SECRET, payload)
    resp = client.post(
        "/webhooks/meta/whatsapp",
        content=body,
        headers={"x-hub-signature-256": sig},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ig_webhook_valid_sig_returns_ok():
    client = _build_app(CFG)
    payload = {"entry": []}
    body, sig = _wa_body_with_sig(SECRET, payload)
    resp = client.post(
        "/webhooks/meta/instagram",
        content=body,
        headers={"x-hub-signature-256": sig},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
