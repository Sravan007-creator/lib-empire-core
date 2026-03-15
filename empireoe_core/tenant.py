"""Tenant isolation helpers.

Every service function MUST accept organization_id as a required int parameter.
These helpers enforce the pattern at the query level.
"""

from __future__ import annotations

from sqlalchemy import Select


def scope_query(stmt: Select, model: type, organization_id: int) -> Select:
    """Add organization_id filter to a SQLAlchemy select statement."""
    return stmt.where(model.organization_id == organization_id)


PROTECTED_FIELDS = frozenset({"id", "organization_id", "created_by_user_id", "created_at"})


def strip_protected_fields(data: dict) -> dict:
    """Remove fields that must never be modified via update endpoints."""
    return {k: v for k, v in data.items() if k not in PROTECTED_FIELDS}
