"""Lead router v0 — classify inbound leads and assign to the right team member.

Routing rules (as of 2026-05-10):
    recruitment   → Sravan  (handles all job-seeking / employer leads)
    everything else → Shybin (study_abroad, agent, general, post_arrival, etc.)

Contact details are read from environment variables so they can be rotated
without a code change. Set these in each API's .env:

    LEAD_ROUTER_RECRUITMENT_WA   — Sravan's WhatsApp number (e164, e.g. +919876543210)
    LEAD_ROUTER_DEFAULT_WA       — Shybin's WhatsApp number
    LEAD_ROUTER_RECRUITMENT_NAME — display name for recruitment assignee (default "Sravan")
    LEAD_ROUTER_DEFAULT_NAME     — display name for default assignee (default "Shybin")
"""

from __future__ import annotations

import os
from dataclasses import dataclass

RECRUITMENT_CATEGORIES = frozenset({"recruitment"})


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
