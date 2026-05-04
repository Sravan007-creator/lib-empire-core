"""Unit tests for the AI gateway. Mocks ``httpx`` — no network."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from empireoe_core.ai import (
    AIBadResponse,
    AIRateLimited,
    AIServiceUnavailable,
    AISettings,
    ChatResult,
    TokenUsage,
    chat_completion,
    chat_completion_with_usage,
    redact_pii,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for k in ("AI_PROVIDER", "AI_MODEL_DEFAULT", "OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)


# ---------------------------------------------------------------------------
# AISettings.resolve
# ---------------------------------------------------------------------------


def test_resolve_defaults_openai_with_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg = AISettings.resolve()
    assert cfg.provider == "openai"
    assert cfg.model == "gpt-4o-mini"
    assert cfg.shape == "openai"


def test_resolve_provider_env_override(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    cfg = AISettings.resolve()
    assert cfg.provider == "groq"
    assert "groq.com" in cfg.base_url


def test_resolve_missing_key_raises(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    with pytest.raises(AIServiceUnavailable):
        AISettings.resolve()


def test_resolve_unknown_provider_raises():
    with pytest.raises(AIServiceUnavailable):
        AISettings.resolve(provider="bogus")


def test_resolve_model_kwarg_wins(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("AI_MODEL_DEFAULT", "gpt-4o")
    cfg = AISettings.resolve(model="gpt-4-turbo")
    assert cfg.model == "gpt-4-turbo"


# ---------------------------------------------------------------------------
# chat_completion — OpenAI shape
# ---------------------------------------------------------------------------


def _openai_response(text: str = "hi", *, status: int = 200) -> httpx.Response:
    body = {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    return httpx.Response(status_code=status, json=body)


@pytest.mark.asyncio
async def test_chat_completion_openai_happy_path(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured: dict[str, Any] = {}

    async def fake_post(self, url, **kwargs):
        captured["url"] = url
        captured["body"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers")
        return _openai_response("hello world")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    text = await chat_completion(
        [{"role": "user", "content": "hi"}],
        system="be concise",
        max_tokens=50,
    )
    assert text == "hello world"
    assert captured["url"].endswith("/chat/completions")
    assert captured["body"]["messages"][0] == {"role": "system", "content": "be concise"}
    assert captured["body"]["max_tokens"] == 50
    assert captured["headers"]["Authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_chat_completion_json_mode_sets_response_format(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured: dict[str, Any] = {}

    async def fake_post(self, url, **kwargs):
        captured["body"] = kwargs.get("json")
        return _openai_response("{}")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    await chat_completion([{"role": "user", "content": "x"}], json_mode=True)
    assert captured["body"]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_chat_completion_rate_limited_raises(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    async def fake_post(self, url, **kwargs):
        return httpx.Response(status_code=429, text="rate limited")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(AIRateLimited):
        await chat_completion([{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_chat_completion_5xx_raises_bad_response(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    async def fake_post(self, url, **kwargs):
        return httpx.Response(status_code=502, text="bad gateway")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(AIBadResponse):
        await chat_completion([{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_chat_completion_transport_error_raises_unavailable(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    async def fake_post(self, url, **kwargs):
        raise httpx.ConnectError("dns fail")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    with pytest.raises(AIServiceUnavailable):
        await chat_completion([{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_chat_completion_redacts_pii_before_send(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    captured: dict[str, Any] = {}

    async def fake_post(self, url, **kwargs):
        captured["body"] = kwargs.get("json")
        return _openai_response("ok")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    user_msg = "Email me at foo@bar.com or call +91 9876543210"
    await chat_completion([{"role": "user", "content": user_msg}], redact_pii=True)
    sent = captured["body"]["messages"][0]["content"]
    assert "foo@bar.com" not in sent
    assert "9876543210" not in sent
    assert "[REDACTED_EMAIL]" in sent


# ---------------------------------------------------------------------------
# chat_completion — Anthropic shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_completion_anthropic_separates_system(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
    captured: dict[str, Any] = {}

    async def fake_post(self, url, **kwargs):
        captured["url"] = url
        captured["body"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers")
        return httpx.Response(
            status_code=200,
            json={
                "content": [{"text": "hello from claude"}],
                "usage": {"input_tokens": 8, "output_tokens": 3},
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    text = await chat_completion(
        [{"role": "user", "content": "hi"}],
        system="be concise",
    )
    assert text == "hello from claude"
    # Anthropic carries system as a top-level field, not in the message list
    assert captured["body"]["system"] == "be concise"
    assert all(m["role"] != "system" for m in captured["body"]["messages"])
    assert captured["headers"]["x-api-key"] == "ant-test"
    assert captured["url"].endswith("/messages")


# ---------------------------------------------------------------------------
# chat_completion_with_usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_completion_with_usage_returns_token_counts(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    async def fake_post(self, url, **kwargs):
        return _openai_response("hi back")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    result = await chat_completion_with_usage([{"role": "user", "content": "hi"}])
    assert isinstance(result, ChatResult)
    assert result.content == "hi back"
    assert result.usage == TokenUsage(prompt_tokens=10, completion_tokens=5)


@pytest.mark.asyncio
async def test_chat_completion_with_usage_anthropic_token_mapping(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")

    async def fake_post(self, url, **kwargs):
        return httpx.Response(
            status_code=200,
            json={
                "content": [{"text": "claude here"}],
                "usage": {"input_tokens": 12, "output_tokens": 7},
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    result = await chat_completion_with_usage([{"role": "user", "content": "hi"}])
    assert result.content == "claude here"
    # Anthropic input_tokens / output_tokens normalize into TokenUsage
    assert result.usage.prompt_tokens == 12
    assert result.usage.completion_tokens == 7


@pytest.mark.asyncio
async def test_chat_completion_string_api_unchanged(monkeypatch):
    """Backward compat: the original string-returning API still returns a string."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    async def fake_post(self, url, **kwargs):
        return _openai_response("plain text")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    text = await chat_completion([{"role": "user", "content": "hi"}])
    assert isinstance(text, str)
    assert text == "plain text"


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def test_redact_pii_email():
    assert "[REDACTED_EMAIL]" in redact_pii("ping nidin@teamempire.org please")


def test_redact_pii_aadhaar():
    assert "[REDACTED_AADHAAR]" in redact_pii("aadhaar 1234 5678 9012 ok")


def test_redact_pii_pan():
    assert "[REDACTED_PAN]" in redact_pii("PAN ABCDE1234F")


def test_redact_pii_empty_string_passthrough():
    assert redact_pii("") == ""


def test_redact_pii_no_match_unchanged():
    assert redact_pii("just a sentence") == "just a sentence"
