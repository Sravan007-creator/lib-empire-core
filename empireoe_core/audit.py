"""Audit trail helper — shared across all Empire backends.

Usage::

    from empireoe_core.audit import record_action
    from myapp.models import AuditEvent

    await record_action(
        db=db,
        model=AuditEvent,
        event_type="contact.created",
        actor_user_id=actor["id"],
        organization_id=org_id,
        entity_type="contact",
        entity_id=str(contact.id),
        payload_json={"name": contact.name},
    )
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def record_action(
    db: AsyncSession,
    *,
    model: type,
    event_type: str,
    actor_user_id: int,
    organization_id: int,
    entity_type: str,
    entity_id: str,
    payload_json: dict[str, Any] | None = None,
) -> Any:
    """Insert an audit event using the provided model class.

    Each product API supplies its own ``AuditEvent`` model so that the
    table lives in the product's own database.

    Returns the created audit event instance.
    """
    payload_str = json.dumps(payload_json) if payload_json is not None else None

    event = model(
        event_type=event_type,
        actor_user_id=actor_user_id,
        organization_id=organization_id,
        entity_type=entity_type,
        entity_id=entity_id,
        payload_json=payload_str,
    )
    db.add(event)
    await db.flush()
    return event
