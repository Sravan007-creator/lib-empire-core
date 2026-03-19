"""Tests for empireoe_core.audit module."""

from __future__ import annotations

import json

import pytest

from empireoe_core.audit import record_action
from tests.conftest import AuditEvent


@pytest.mark.asyncio
async def test_record_action(db):
    event = await record_action(
        db,
        model=AuditEvent,
        event_type="contact.created",
        actor_user_id=1,
        organization_id=1,
        entity_type="contact",
        entity_id="99",
        payload_json={"name": "John"},
    )
    assert event.id is not None
    assert event.event_type == "contact.created"
    assert event.entity_id == "99"
    assert json.loads(event.payload_json) == {"name": "John"}


@pytest.mark.asyncio
async def test_record_action_no_payload(db):
    event = await record_action(
        db,
        model=AuditEvent,
        event_type="user.login",
        actor_user_id=1,
        organization_id=1,
        entity_type="user",
        entity_id="1",
    )
    assert event.payload_json is None
