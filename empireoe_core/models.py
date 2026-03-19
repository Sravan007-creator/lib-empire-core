"""Reusable SQLAlchemy mixins and base models for Empire backends.

Usage::

    from empireoe_core.models import TenantMixin, TimestampMixin, AuditEventBase

    class MyModel(TenantMixin, TimestampMixin, Base):
        __tablename__ = "my_table"
        name: Mapped[str] = mapped_column()
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class TenantMixin:
    """Adds ``organization_id`` (FK, indexed, NOT NULL) to any model."""

    @declared_attr
    def organization_id(cls) -> Mapped[int]:
        return mapped_column(
            Integer,
            ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` columns."""

    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            server_default=func.now(),
        )

    @declared_attr
    def updated_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            onupdate=lambda: datetime.now(UTC),
            server_default=func.now(),
        )


class AuditEventBase:
    """Base mixin for an ``audit_events`` table.

    Each product API creates its own concrete model::

        from empireoe_core.db import Base
        from empireoe_core.models import AuditEventBase

        class AuditEvent(AuditEventBase, Base):
            __tablename__ = "audit_events"
    """

    @declared_attr
    def id(cls) -> Mapped[int]:
        return mapped_column(Integer, primary_key=True, autoincrement=True)

    @declared_attr
    def event_type(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False, index=True)

    @declared_attr
    def actor_user_id(cls) -> Mapped[int]:
        return mapped_column(Integer, nullable=False, index=True)

    @declared_attr
    def organization_id(cls) -> Mapped[int]:
        return mapped_column(
            Integer,
            ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )

    @declared_attr
    def entity_type(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def entity_id(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False)

    @declared_attr
    def payload_json(cls) -> Mapped[str | None]:
        return mapped_column(Text, nullable=True)

    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True),
            default=lambda: datetime.now(UTC),
            server_default=func.now(),
        )
