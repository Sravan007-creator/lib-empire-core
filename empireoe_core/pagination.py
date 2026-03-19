"""Pagination utilities for FastAPI + SQLAlchemy async.

Usage::

    from empireoe_core.pagination import PaginationParams, PaginatedResponse, paginate

    @router.get("/contacts", response_model=PaginatedResponse[ContactRead])
    async def list_contacts(
        pagination: PaginationParams = Depends(),
        db: AsyncSession = Depends(get_db),
    ):
        stmt = select(Contact).where(Contact.organization_id == org_id)
        return await paginate(db, stmt, pagination, ContactRead)
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

T = TypeVar("T")

MAX_LIMIT = 200


class PaginationParams:
    """FastAPI dependency for skip/limit pagination."""

    def __init__(self, skip: int = 0, limit: int = 50) -> None:
        self.skip = max(skip, 0)
        self.limit = min(max(limit, 1), MAX_LIMIT)


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""

    items: list[T] = Field(default_factory=list)
    total: int = 0
    skip: int = 0
    limit: int = 50


async def paginate(
    db: AsyncSession,
    stmt: Select,
    params: PaginationParams,
    response_model: type[T] | None = None,
) -> PaginatedResponse:
    """Execute a query with pagination and return a PaginatedResponse.

    If ``response_model`` is provided and has a ``model_validate`` method
    (i.e. a Pydantic model), each row is converted via ``model_validate``.
    Otherwise rows are returned as-is.
    """
    # Count total rows (without offset/limit)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    # Fetch the page
    page_stmt = stmt.offset(params.skip).limit(params.limit)
    result = await db.execute(page_stmt)
    rows = result.scalars().all()

    # Optionally convert to response model
    if response_model is not None and hasattr(response_model, "model_validate"):
        items = [response_model.model_validate(row, from_attributes=True) for row in rows]
    else:
        items = list(rows)

    return PaginatedResponse(
        items=items,
        total=total,
        skip=params.skip,
        limit=params.limit,
    )
