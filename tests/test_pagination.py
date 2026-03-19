"""Tests for empireoe_core.pagination module."""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from empireoe_core.pagination import PaginatedResponse, PaginationParams, paginate
from tests.conftest import SampleModel


class SampleRead(BaseModel):
    id: int
    name: str
    organization_id: int

    model_config = {"from_attributes": True}


def test_pagination_params_defaults():
    p = PaginationParams()
    assert p.skip == 0
    assert p.limit == 50


def test_pagination_params_clamps():
    p = PaginationParams(skip=-5, limit=999)
    assert p.skip == 0
    assert p.limit == 200


def test_pagination_params_min_limit():
    p = PaginationParams(limit=0)
    assert p.limit == 1


@pytest.mark.asyncio
async def test_paginate(db):
    for i in range(10):
        db.add(SampleModel(name=f"Item {i}", organization_id=1))
    await db.commit()

    stmt = select(SampleModel).where(SampleModel.organization_id == 1)
    params = PaginationParams(skip=0, limit=3)
    result = await paginate(db, stmt, params, SampleRead)

    assert isinstance(result, PaginatedResponse)
    assert result.total == 10
    assert len(result.items) == 3
    assert result.skip == 0
    assert result.limit == 3
    assert isinstance(result.items[0], SampleRead)


@pytest.mark.asyncio
async def test_paginate_skip(db):
    for i in range(5):
        db.add(SampleModel(name=f"S {i}", organization_id=1))
    await db.commit()

    stmt = select(SampleModel).where(SampleModel.organization_id == 1)
    params = PaginationParams(skip=3, limit=50)
    result = await paginate(db, stmt, params)

    assert result.total == 5
    assert len(result.items) == 2
