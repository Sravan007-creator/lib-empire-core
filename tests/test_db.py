"""Tests for empireoe_core.db module."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from empireoe_core.db import create_async_engine_from_url, create_session_factory, get_db, set_session_factory


@pytest.mark.asyncio
async def test_create_engine_and_session():
    engine = create_async_engine_from_url("sqlite+aiosqlite://")
    factory = create_session_factory(engine)
    async with factory() as session:
        assert isinstance(session, AsyncSession)
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_db_raises_without_factory():
    """get_db should raise RuntimeError if no session factory is set."""
    set_session_factory(None)
    with pytest.raises(RuntimeError, match="session factory not configured"):
        async for _ in get_db():
            pass


@pytest.mark.asyncio
async def test_get_db_yields_session():
    engine = create_async_engine_from_url("sqlite+aiosqlite://")
    factory = create_session_factory(engine)
    set_session_factory(factory)
    try:
        async for session in get_db():
            assert isinstance(session, AsyncSession)
    finally:
        set_session_factory(None)
        await engine.dispose()
