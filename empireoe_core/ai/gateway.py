"""Provider-agnostic chat completion gateway.

Replaces the ad-hoc ``httpx.AsyncClient`` calls scattered across product
backends. One entry point — ``chat_completion`` — with provider routing,
cost-tracking logs, optional PII redaction, and typed errors that backends
map to HTTP responses.

Provider is chosen at call time via ``model`` prefix or via the
``AI_PROVIDER`` environment variable. Supported providers: ``openai``,
``groq``, ``anthropic``. Adding a new provider means extending ``_PROVIDERS``
and (for non-OpenAI-shaped APIs) a translator function.

Usage:

    from empireoe_core.ai import chat_completion

    text = await chat_completion(
        [{"role": "user", "content": "Say hi"}],
        system="You are a job advisor.",
        max_tokens=200,
    )

Errors:

    AIServiceUnavailable  — no API key configured / connection failure
    AIRateLimited         — provider returned 429
    AIBadResponse         — provider returned non-2xx (other) or unparseable
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from empireoe_core.ai.redaction import redact_pii as _redact_pii

logger = logging.getLogger("empireoe_core.ai")

# ---------------------------------------------------------------------------
# Provider catalogue
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, dict[str, str]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
        "shape": "openai",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "key_env": "GROQ_API_KEY",
        "shape": "openai",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-haiku-4-5-20251001",
        "key_env": "ANTHROPIC_API_KEY",
        "shape": "anthropic",
    },
}

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AIError(Exception):
    """Base for all AI gateway errors."""


class AIServiceUnavailable(AIError):
    """No key configured or transport-level failure."""


class AIRateLimited(AIError):
    """Provider returned 429."""


class AIBadResponse(AIError):
    """Provider returned non-2xx or unparseable body."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class ChatResult:
    """Returned by ``chat_completion_with_usage``. ``content`` is what the
    model said; ``usage`` exposes the token counts the provider reported so
    callers can persist or aggregate spend."""

    content: str
    usage: TokenUsage


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AISettings:
    """Per-call resolution of provider, key, model.

    Resolution order: explicit kwargs > ``AI_PROVIDER`` / ``AI_MODEL_DEFAULT``
    env > catalogue defaults. Built lazily so unit tests can patch ``os.environ``.
    """

    provider: str
    model: str
    api_key: str
    base_url: str
    shape: str

    @classmethod
    def resolve(cls, *, provider: str | None = None, model: str | None = None) -> AISettings:
        chosen = (provider or os.getenv("AI_PROVIDER") or "openai").lower()
        if chosen not in _PROVIDERS:
            raise AIServiceUnavailable(f"Unknown AI provider: {chosen!r}")
        spec = _PROVIDERS[chosen]
        api_key = os.getenv(spec["key_env"], "")
        if not api_key:
            raise AIServiceUnavailable(f"{spec['key_env']} not configured")
        chosen_model = model or os.getenv("AI_MODEL_DEFAULT") or spec["default_model"]
        return cls(
            provider=chosen,
            model=chosen_model,
            api_key=api_key,
            base_url=spec["base_url"],
            shape=spec["shape"],
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def chat_completion(
    messages: list[dict[str, Any]],
    *,
    system: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    max_tokens: int = 500,
    temperature: float = 0.7,
    json_mode: bool = False,
    redact_pii: bool = False,
    timeout: float = 30.0,
) -> str:
    """Run a chat completion and return the assistant message text.

    ``redact_pii`` runs ``empireoe_core.ai.redact_pii`` over every user/system
    message *before* the prompt leaves the cluster. ``json_mode`` enables the
    provider's JSON-output flag where supported (OpenAI and Groq).

    Use ``chat_completion_with_usage`` when you also need token counts (e.g.
    to persist spend or render a cost dashboard).
    """
    result = await chat_completion_with_usage(
        messages,
        system=system,
        model=model,
        provider=provider,
        max_tokens=max_tokens,
        temperature=temperature,
        json_mode=json_mode,
        redact_pii=redact_pii,
        timeout=timeout,
    )
    return result.content


async def chat_completion_with_usage(
    messages: list[dict[str, Any]],
    *,
    system: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    max_tokens: int = 500,
    temperature: float = 0.7,
    json_mode: bool = False,
    redact_pii: bool = False,
    timeout: float = 30.0,
) -> ChatResult:
    """Like ``chat_completion`` but also returns prompt / completion token counts.

    Backends that persist per-message spend (e.g. chatbot message rows) call
    this to keep the metric. Other callers should prefer ``chat_completion``.
    """
    cfg = AISettings.resolve(provider=provider, model=model)

    payload_messages: list[dict[str, Any]] = []
    if system:
        payload_messages.append(
            {"role": "system", "content": _redact_pii(system) if redact_pii else system}
        )
    for m in messages:
        content = m.get("content", "")
        if redact_pii and isinstance(content, str):
            content = _redact_pii(content)
        payload_messages.append({"role": m.get("role", "user"), "content": content})

    if cfg.shape == "openai":
        return await _call_openai_shape(
            cfg,
            payload_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=json_mode,
            timeout=timeout,
        )
    if cfg.shape == "anthropic":
        return await _call_anthropic_shape(
            cfg,
            payload_messages,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
    raise AIServiceUnavailable(f"Unsupported provider shape: {cfg.shape}")


# ---------------------------------------------------------------------------
# Provider transport
# ---------------------------------------------------------------------------


async def _call_openai_shape(
    cfg: AISettings,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int,
    temperature: float,
    json_mode: bool,
    timeout: float,
) -> ChatResult:
    body: dict[str, Any] = {
        "model": cfg.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(
                f"{cfg.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {cfg.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        except httpx.HTTPError as exc:
            raise AIServiceUnavailable(f"{cfg.provider} transport error: {exc}") from exc

    if resp.status_code == 429:
        raise AIRateLimited(f"{cfg.provider} rate limited")
    if resp.status_code != 200:
        raise AIBadResponse(f"{cfg.provider} {resp.status_code}: {resp.text[:300]}")

    try:
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {}) or {}
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        raise AIBadResponse(f"{cfg.provider} unparseable response: {exc}") from exc

    _log_usage(cfg, usage)
    return ChatResult(
        content=text,
        usage=TokenUsage(
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
        ),
    )


async def _call_anthropic_shape(
    cfg: AISettings,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> ChatResult:
    # Anthropic separates the system prompt from the message list.
    system_prompt: str | None = None
    user_messages: list[dict[str, Any]] = []
    for m in messages:
        if m.get("role") == "system":
            system_prompt = m.get("content")
        else:
            user_messages.append(m)

    body: dict[str, Any] = {
        "model": cfg.model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": user_messages,
    }
    if system_prompt:
        body["system"] = system_prompt

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(
                f"{cfg.base_url}/messages",
                headers={
                    "x-api-key": cfg.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        except httpx.HTTPError as exc:
            raise AIServiceUnavailable(f"{cfg.provider} transport error: {exc}") from exc

    if resp.status_code == 429:
        raise AIRateLimited(f"{cfg.provider} rate limited")
    if resp.status_code != 200:
        raise AIBadResponse(f"{cfg.provider} {resp.status_code}: {resp.text[:300]}")

    try:
        data = resp.json()
        text = data["content"][0]["text"]
        usage = {
            "prompt_tokens": data.get("usage", {}).get("input_tokens", 0),
            "completion_tokens": data.get("usage", {}).get("output_tokens", 0),
        }
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        raise AIBadResponse(f"{cfg.provider} unparseable response: {exc}") from exc

    _log_usage(cfg, usage)
    return ChatResult(
        content=text,
        usage=TokenUsage(
            prompt_tokens=int(usage["prompt_tokens"] or 0),
            completion_tokens=int(usage["completion_tokens"] or 0),
        ),
    )


def _log_usage(cfg: AISettings, usage: dict[str, Any]) -> None:
    logger.info(
        "ai_call",
        extra={
            "provider": cfg.provider,
            "model": cfg.model,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        },
    )
