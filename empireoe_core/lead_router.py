"""Lead router v0 — classify inbound leads, assign to the right team, and
handle Meta (Instagram + WhatsApp) inbound webhook events.

Routing rules (as of 2026-05-10):
    recruitment   → Sravan  (handles all job-seeking / employer leads)
    everything else → Shybin (study_abroad, agent, general, post_arrival, etc.)

Contact details are read from environment variables so they can be rotated
without a code change. Set these in each API's .env:

    LEAD_ROUTER_RECRUITMENT_WA   — Sravan's WhatsApp number (e164, e.g. +919876543210)
    LEAD_ROUTER_DEFAULT_WA       — Shybin's WhatsApp number
    LEAD_ROUTER_RECRUITMENT_NAME — display name for recruitment assignee (default "Sravan")
    LEAD_ROUTER_DEFAULT_NAME     — display name for default assignee (default "Shybin")

Meta webhook env vars (one set per product — share if the same Meta App is used):

    META_APP_SECRET              — HMAC-SHA256 secret from Meta App dashboard
    INSTAGRAM_PAGE_ACCESS_TOKEN  — IG page token (for sending IG DM replies)
    INSTAGRAM_VERIFY_TOKEN       — Hub verification token for IG webhook
    WHATSAPP_ACCESS_TOKEN        — WA Cloud API token
    WHATSAPP_PHONE_NUMBER_ID     — WA Cloud API phone number ID
    WHATSAPP_VERIFY_TOKEN        — Hub verification token for WA webhook
    ANTHROPIC_API_KEY            — for Claude lead classification

Usage (in any Empire FastAPI backend)::

    from empireoe_core.lead_router import create_meta_webhook_router, MetaWebhookConfig

    async def _save_lead(source, identifier, name, message):
        async with db_session() as db:
            await lead_service.create_lead(db, ...)

    router = create_meta_webhook_router(
        config=MetaWebhookConfig.from_env(),
        on_lead=_save_lead,
    )
    app.include_router(router)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Request, Response

logger = logging.getLogger(__name__)

# ── Lead assignment ────────────────────────────────────────────────────────────

RECRUITMENT_CATEGORIES = frozenset({"recruitment"})

VALID_CATEGORIES = frozenset({"recruitment", "study_abroad", "agent", "general"})


@dataclass(frozen=True)
class Assignee:
    name: str
    whatsapp: str


def _recruitment_assignee() -> Assignee:
    return Assignee(
        name=os.getenv("LEAD_ROUTER_RECRUITMENT_NAME", "Sravan"),
        whatsapp=os.getenv("LEAD_ROUTER_RECRUITMENT_WA", ""),
    )


def _default_assignee() -> Assignee:
    return Assignee(
        name=os.getenv("LEAD_ROUTER_DEFAULT_NAME", "Shybin"),
        whatsapp=os.getenv("LEAD_ROUTER_DEFAULT_WA", ""),
    )


def route_lead(category: str, product: str | None = None) -> Assignee:
    """Return the assignee for a classified lead.

    Args:
        category: Lead category string, e.g. "recruitment", "study_abroad",
                  "agent", "general". Unknown categories default to Shybin.
        product:  Optional product slug (reserved for future product-specific
                  routing; currently unused).
    """
    if category in RECRUITMENT_CATEGORIES:
        return _recruitment_assignee()
    return _default_assignee()


def should_notify(category: str) -> bool:
    """Return True for categories that warrant an immediate WhatsApp ping."""
    return category in {"recruitment", "study_abroad", "agent"}


# ── Meta webhook config ────────────────────────────────────────────────────────

@dataclass
class MetaWebhookConfig:
    """All credentials and tokens needed for the Meta webhook router.

    Use ``MetaWebhookConfig.from_env()`` to populate from environment variables.
    """

    app_secret: str = ""
    ig_page_token: str = ""
    ig_verify_token: str = ""
    wa_token: str = ""
    wa_phone_id: str = ""
    wa_verify_token: str = ""
    anthropic_key: str = ""
    # Which category of leads to persist (others get reply only, no DB write)
    persist_categories: frozenset[str] = field(
        default_factory=lambda: frozenset({"recruitment", "study_abroad", "agent"})
    )

    @classmethod
    def from_env(cls) -> "MetaWebhookConfig":
        return cls(
            app_secret=os.getenv("META_APP_SECRET", ""),
            ig_page_token=os.getenv("INSTAGRAM_PAGE_ACCESS_TOKEN", ""),
            ig_verify_token=os.getenv("INSTAGRAM_VERIFY_TOKEN", ""),
            wa_token=os.getenv("WHATSAPP_ACCESS_TOKEN", ""),
            wa_phone_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
            wa_verify_token=os.getenv("WHATSAPP_VERIFY_TOKEN", ""),
            anthropic_key=os.getenv("ANTHROPIC_API_KEY", ""),
        )


# ── Security ───────────────────────────────────────────────────────────────────

def verify_meta_signature(raw_body: bytes, signature_header: str, app_secret: str) -> bool:
    """Verify Meta HMAC-SHA256 webhook signature.

    SECURITY: if ``app_secret`` is empty we REJECT (return False) rather than
    accept.  Accepting all webhooks when the secret is missing would allow
    anyone to forge arbitrary Meta webhook events.

    Args:
        raw_body:         Raw request body bytes (before any parsing).
        signature_header: Value of the ``x-hub-signature-256`` header.
        app_secret:       The Meta App Secret from the developer dashboard.

    Returns:
        True only if the signature matches the HMAC-SHA256 of the body.
    """
    if not app_secret:
        logger.warning("verify_meta_signature: META_APP_SECRET not set — rejecting webhook")
        return False
    try:
        expected = hmac.new(
            app_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        received = signature_header.replace("sha256=", "")
        return hmac.compare_digest(expected, received)
    except Exception:
        return False


# ── AI classification ──────────────────────────────────────────────────────────

_CLASSIFY_SYSTEM = """You are an AI assistant for Team Empire, a group running two main services:
1. **Empire Overseas Recruitment** — places professionals in jobs abroad across Healthcare, Engineering, IT, Finance, Oil & Gas, Construction, Hospitality.
2. **Empire Overseas Education (EOE)** — study abroad consulting for students wanting to study in UK, Canada, Australia, Germany, Ireland etc.

There are also **study abroad agents** — education consultants who want to partner with EOE.

A) CLASSIFY the message into exactly one category:
   - "recruitment"   → person looking for a job abroad, work visas, salaries, job opportunities
   - "study_abroad"  → student asking about studying abroad, university admissions, student visas
   - "agent"         → education agent/consultant asking about partnership with EOE
   - "general"       → anything else

B) WRITE a WhatsApp reply (2–4 sentences max, warm and professional, end with one question).

IMPORTANT: Reply in the SAME language as the user's message.

Respond in this exact JSON format (no markdown):
{"category":"recruitment","reply":"Your reply here"}"""

_IG_CLASSIFY_SYSTEM = """You are a friendly recruitment consultant for Empire Overseas Recruitment, responding to Instagram DMs.

Empire Overseas Recruitment places professionals across UAE, Saudi Arabia, Qatar, Germany, Singapore, Norway, UK, Australia, Canada and more.
Key sectors: Healthcare, Engineering, IT, Finance, Oil & Gas, Construction, Hospitality.

Rules:
- Keep replies SHORT — 2 to 4 sentences max
- Be warm, enthusiastic, and professional
- Never guarantee placement or specific salaries
- Always end with ONE clear question
- Use 1–2 relevant emojis max
- If ready to apply, direct to: empireoverseasrecruitment.com/jobs

Respond with ONLY the reply text (no JSON)."""


def _fallback_reply() -> str:
    return (
        "Hi! Thanks for reaching out to Team Empire 👋 "
        "We help professionals find jobs abroad and students study overseas. "
        "What can we help you with today?"
    )


async def classify_inbound_lead(message: str, anthropic_key: str) -> dict[str, str]:
    """Classify a WhatsApp/website lead message using Claude and generate a reply.

    Args:
        message:       The inbound message text from the lead.
        anthropic_key: Anthropic API key. Returns static fallback when empty.

    Returns:
        Dict with keys ``category`` (str) and ``reply`` (str).
    """
    if not anthropic_key:
        return {"category": "general", "reply": _fallback_reply()}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": "claude-3-5-haiku-20241022",
                    "max_tokens": 400,
                    "system": _CLASSIFY_SYSTEM,
                    "messages": [{"role": "user", "content": message}],
                },
            )
        if not res.is_success:
            return {"category": "general", "reply": _fallback_reply()}

        data = res.json()
        raw = (data.get("content") or [{}])[0].get("text", "").strip()
        clean = raw.lstrip("```json").rstrip("```").strip()
        parsed = json.loads(clean)
        category = parsed.get("category", "general")
        if category not in VALID_CATEGORIES:
            category = "general"
        return {"category": category, "reply": parsed.get("reply", _fallback_reply()).strip()}
    except Exception:
        return {"category": "general", "reply": _fallback_reply()}


async def _ig_reply(message: str, anthropic_key: str) -> str:
    """Instagram-specific reply (recruitment persona, plain text, no JSON)."""
    if not anthropic_key:
        return (
            "Hi! Thanks for reaching out to Empire Overseas Recruitment 👋 "
            "We help professionals find opportunities across the Middle East, Europe & Asia-Pacific. "
            "What role are you looking for, and which country interests you?"
        )
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": anthropic_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": "claude-3-5-haiku-20241022",
                    "max_tokens": 250,
                    "system": _IG_CLASSIFY_SYSTEM,
                    "messages": [{"role": "user", "content": message}],
                },
            )
        if not res.is_success:
            raise ValueError("Claude error")
        data = res.json()
        return (data.get("content") or [{}])[0].get("text", "").strip() or _fallback_reply()
    except Exception:
        return _fallback_reply()


# ── Meta messaging helpers ─────────────────────────────────────────────────────

async def send_ig_message(recipient_id: str, text: str, page_token: str) -> None:
    """Send an Instagram DM reply via the Graph API."""
    if not page_token:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                "https://graph.instagram.com/v21.0/me/messages",
                headers={"Authorization": f"Bearer {page_token}"},
                json={"recipient": {"id": recipient_id}, "message": {"text": text}},
            )
    except Exception:
        pass


async def send_wa_message(to: str, text: str, wa_token: str, wa_phone_id: str) -> None:
    """Send a WhatsApp Cloud API text message."""
    if not wa_token or not wa_phone_id:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"https://graph.facebook.com/v21.0/{wa_phone_id}/messages",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {wa_token}",
                },
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {"body": text},
                },
            )
    except Exception:
        pass


async def _get_ig_username(user_id: str, page_token: str) -> str | None:
    if not page_token:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(
                f"https://graph.instagram.com/v21.0/{user_id}",
                params={"fields": "name", "access_token": page_token},
            )
        if res.is_success:
            return res.json().get("name")
    except Exception:
        pass
    return None


# ── Router factory ─────────────────────────────────────────────────────────────

#: Type alias for the on_lead callback injected by each product.
#: Called with (source, identifier, name_or_None, message_text).
OnLeadCallback = Callable[[str, str, Optional[str], str], Awaitable[None]]


def create_meta_webhook_router(
    config: MetaWebhookConfig,
    on_lead: OnLeadCallback | None = None,
    prefix: str = "/webhooks/meta",
) -> APIRouter:
    """Build a FastAPI router that handles Meta (Instagram + WhatsApp) webhooks.

    Each Empire product passes its own ``on_lead`` async callback so that lead
    persistence is product-specific while all the Meta plumbing is shared.

    Args:
        config:   A ``MetaWebhookConfig`` instance (typically from ``from_env()``).
        on_lead:  Async callback ``(source, identifier, name, message) → None``.
                  Called in a background task for every qualifying inbound message.
                  If None, leads are classified and replied to but not persisted.
        prefix:   URL prefix for the router (default ``/webhooks/meta``).

    Returns:
        A FastAPI ``APIRouter`` ready to be included with ``app.include_router()``.

    Example::

        router = create_meta_webhook_router(
            config=MetaWebhookConfig.from_env(),
            on_lead=my_save_lead,
        )
        app.include_router(router)
    """
    import asyncio

    router = APIRouter(prefix=prefix, tags=["meta-webhooks"])

    # ── Instagram ────────────────────────────────────────────────────────────

    @router.get("/instagram")
    async def ig_verify(request: Request) -> Response:
        params = request.query_params
        if (
            params.get("hub.mode") == "subscribe"
            and params.get("hub.verify_token") == config.ig_verify_token
            and params.get("hub.challenge")
        ):
            return Response(content=params["hub.challenge"], media_type="text/plain")
        return Response(content="Forbidden", status_code=403)

    @router.post("/instagram")
    async def ig_webhook(request: Request, background_tasks: BackgroundTasks) -> Any:
        raw_body = await request.body()
        signature = request.headers.get("x-hub-signature-256", "")
        if not verify_meta_signature(raw_body, signature, config.app_secret):
            return Response(content="Invalid signature", status_code=401)

        try:
            payload = json.loads(raw_body)
        except Exception:
            return {"status": "ok"}

        async def _process() -> None:
            for entry in payload.get("entry", []):
                for event in entry.get("messaging", []):
                    if event.get("message", {}).get("is_echo"):
                        continue
                    if "read" in event or "delivery" in event:
                        continue
                    text = (event.get("message") or {}).get("text", "").strip()
                    sender_id = (event.get("sender") or {}).get("id")
                    if not text or not sender_id:
                        continue

                    username, reply = await asyncio.gather(
                        _get_ig_username(sender_id, config.ig_page_token),
                        _ig_reply(text, config.anthropic_key),
                    )
                    await send_ig_message(sender_id, reply, config.ig_page_token)
                    if on_lead:
                        await on_lead("Instagram DM", sender_id, username, text)

        background_tasks.add_task(_process)
        return {"status": "ok"}

    # ── WhatsApp ─────────────────────────────────────────────────────────────

    @router.get("/whatsapp")
    async def wa_verify(request: Request) -> Response:
        params = request.query_params
        if (
            params.get("hub.mode") == "subscribe"
            and params.get("hub.verify_token") == config.wa_verify_token
            and params.get("hub.challenge")
        ):
            return Response(content=params["hub.challenge"], media_type="text/plain")
        return Response(content="Forbidden", status_code=403)

    @router.post("/whatsapp")
    async def wa_webhook(request: Request, background_tasks: BackgroundTasks) -> Any:
        raw_body = await request.body()
        signature = request.headers.get("x-hub-signature-256", "")
        if not verify_meta_signature(raw_body, signature, config.app_secret):
            return Response(content="Invalid signature", status_code=401)

        try:
            payload = json.loads(raw_body)
        except Exception:
            return {"status": "ok"}

        async def _process() -> None:
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value") or {}
                    messages = value.get("messages") or []
                    contacts = value.get("contacts") or []
                    for msg in messages:
                        if msg.get("type") != "text":
                            continue
                        text = (msg.get("text") or {}).get("body", "").strip()
                        phone = msg.get("from")
                        if not text or not phone:
                            continue

                        contact = next(
                            (c for c in contacts if c.get("wa_id") == phone), {}
                        )
                        sender_name = (contact.get("profile") or {}).get("name")

                        result = await classify_inbound_lead(text, config.anthropic_key)
                        await send_wa_message(
                            phone, result["reply"],
                            config.wa_token, config.wa_phone_id,
                        )

                        if on_lead and result["category"] in config.persist_categories:
                            await on_lead("WhatsApp DM", phone, sender_name, text)

        background_tasks.add_task(_process)
        return {"status": "ok"}

    return router
