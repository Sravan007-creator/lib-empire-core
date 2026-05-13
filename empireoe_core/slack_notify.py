"""Slack webhook notification — fire-and-forget posts to a configured channel.

Used by ``empireoe_core.lead_router`` to ping the lead assignee on every
inbound lead. Deliberately minimal:

  - One configured webhook URL per "destination" (recruitment, default,
    product-specific). Set via env so a Slack webhook can be rotated
    without a code change.
  - Posts with httpx; ``httpx.AsyncClient`` is already a transitive
    dependency of every Empire backend (FastAPI test client).
  - Swallows non-2xx into a logged warning rather than raising. A Slack
    outage must NOT take down the lead ingestion path.

Configuration:

  SLACK_WEBHOOK_URL_LEADS_RECRUITMENT   — Sravan's channel for recruitment
  SLACK_WEBHOOK_URL_LEADS_DEFAULT       — Shybin's channel for everything else
  SLACK_WEBHOOK_URL_LEADS_<PRODUCT>     — optional product override
                                          e.g. SLACK_WEBHOOK_URL_LEADS_HOTELO

The product override is consulted first, then the category-based pair.
Returns silently when no webhook is configured for the resolved channel —
this keeps the test environment quiet without code branches at call sites.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger("empireoe_core.slack_notify")


@dataclass(frozen=True)
class SlackLeadMessage:
    """Structured payload for a lead-arrival Slack ping."""

    title: str  # "New IG lead — Recruitment"
    summary: str  # "Aisha K. (+971-50-...) asked about senior frontend roles"
    lead_id: str | None = None
    dashboard_url: str | None = None
    extra_fields: dict | None = None

    def to_blocks(self) -> list[dict]:
        """Render to Slack Block Kit. Keeps the lead-room readable."""
        blocks: list[dict] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": self.title, "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": self.summary},
            },
        ]
        if self.extra_fields:
            blocks.append(
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*{k}*\n{v}",
                        }
                        for k, v in self.extra_fields.items()
                    ][:10],
                }
            )
        if self.dashboard_url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open in dashboard"},
                            "url": self.dashboard_url,
                            "style": "primary",
                        }
                    ],
                }
            )
        return blocks


def _resolve_webhook(*, category: str, product: str | None = None) -> str:
    """Pick the Slack webhook URL for this lead.

    Order of precedence:
      1. SLACK_WEBHOOK_URL_LEADS_<PRODUCT>
      2. SLACK_WEBHOOK_URL_LEADS_RECRUITMENT  (if category == recruitment)
      3. SLACK_WEBHOOK_URL_LEADS_DEFAULT
    Empty string = "no webhook configured" — fire-and-forget no-op.
    """
    if product:
        url = os.getenv(f"SLACK_WEBHOOK_URL_LEADS_{product.upper()}", "")
        if url:
            return url
    if category == "recruitment":
        url = os.getenv("SLACK_WEBHOOK_URL_LEADS_RECRUITMENT", "")
        if url:
            return url
    return os.getenv("SLACK_WEBHOOK_URL_LEADS_DEFAULT", "")


async def notify_lead_arrived(
    *,
    category: str,
    product: str | None,
    message: SlackLeadMessage,
    timeout_seconds: float = 5.0,
) -> bool:
    """Post a lead-arrival ping to the Slack channel for this category /
    product. Returns True if the post succeeded; False if no webhook is
    configured or Slack returned non-2xx. Never raises.

    Caller pattern (inside an inbound-webhook handler):

        from empireoe_core.slack_notify import SlackLeadMessage, notify_lead_arrived

        await notify_lead_arrived(
            category="recruitment",
            product="empireo",
            message=SlackLeadMessage(
                title="New IG lead — Recruitment",
                summary=f"{lead.name} asked about senior frontend roles",
                lead_id=str(lead.id),
                dashboard_url=f"{dashboard_origin}/leads/{lead.id}",
                extra_fields={"Phone": lead.phone, "Source": "Instagram"},
            ),
        )
    """
    webhook_url = _resolve_webhook(category=category, product=product)
    if not webhook_url:
        logger.debug(
            "Slack webhook not configured for category=%s product=%s — skipping",
            category,
            product,
        )
        return False

    payload = {"blocks": message.to_blocks(), "text": message.title}
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(webhook_url, json=payload)
        if 200 <= resp.status_code < 300:
            return True
        logger.warning(
            "Slack lead-notify non-2xx: status=%s body=%s",
            resp.status_code,
            resp.text[:200],
        )
        return False
    except Exception as exc:  # noqa: BLE001 — Slack must never break ingestion
        logger.warning("Slack lead-notify failed: %s", exc)
        return False
