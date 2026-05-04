"""AI gateway — shared LLM client for all Empire backends.

One place for provider routing, cost tracking, PII redaction, and guardrails.
Backends call ``chat_completion`` instead of hand-rolling httpx calls to OpenAI.
"""

from empireoe_core.ai.gateway import (
    AIBadResponse,
    AIError,
    AIRateLimited,
    AIServiceUnavailable,
    AISettings,
    ChatResult,
    TokenUsage,
    chat_completion,
    chat_completion_with_usage,
)
from empireoe_core.ai.redaction import redact_pii

__all__ = [
    "AIError",
    "AIServiceUnavailable",
    "AIRateLimited",
    "AIBadResponse",
    "AISettings",
    "ChatResult",
    "TokenUsage",
    "chat_completion",
    "chat_completion_with_usage",
    "redact_pii",
]
