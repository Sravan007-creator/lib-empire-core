"""Tests for empireoe_core.models mixins."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.conftest import AuditEvent, SampleModel


@pytest.mark.asyncio
async def test_tenant_and_timestamp_mixin(db):
    """TenantMixin adds organization_id; TimestampMixin adds created_at/updated_at."""
    obj = SampleModel(name="Test", organization_id=1)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)

    assert obj.id is not None
    assert obj.organization_id == 1
    assert obj.created_at is not None
    assert obj.updated_at is not None


@pytest.mark.asyncio
async def test_audit_event_base(db):
    """AuditEventBase columns are present and insertable."""
    event = AuditEvent(
        event_type="contact.created",
        actor_user_id=1,
        organization_id=1,
        entity_type="contact",
        entity_id="42",
        payload_json='{"name": "test"}',
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    assert event.id is not None
    assert event.event_type == "contact.created"
    assert event.created_at is not None


@pytest.mark.asyncio
async def test_tenant_isolation(db):
    """Objects from org 1 should not appear in org 2 query."""
    db.add(SampleModel(name="Org1 Item", organization_id=1))
    db.add(SampleModel(name="Org2 Item", organization_id=2))
    await db.commit()

    result = await db.execute(select(SampleModel).where(SampleModel.organization_id == 1))
    items = result.scalars().all()
    assert all(item.organization_id == 1 for item in items)
    assert any(item.name == "Org1 Item" for item in items)
    assert not any(item.name == "Org2 Item" for item in items)
