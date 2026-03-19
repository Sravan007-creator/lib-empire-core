"""Shared test fixtures for empireoe-core tests."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import Integer, String, Text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from empireoe_core.db import create_session_factory
from empireoe_core.models import AuditEventBase, TenantMixin, TimestampMixin


# ---------- In-memory test base (no FK to organizations for simplicity) ----------

class TestBase(DeclarativeBase):
    pass


class Organization(TestBase):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))


class SampleModel(TenantMixin, TimestampMixin, TestBase):
    __tablename__ = "samples"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))


class AuditEvent(AuditEventBase, TestBase):
    __tablename__ = "audit_events"


# ---------- Fixtures ----------

@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(TestBase.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    factory = create_session_factory(engine)
    async with factory() as session:
        # Seed an organization
        session.add(Organization(id=1, name="Test Org"))
        session.add(Organization(id=2, name="Other Org"))
        await session.commit()
        yield session
