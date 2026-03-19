"""Database engine, session factory, FastAPI dependency, and declarative base.

Usage in a product API::

    from empireoe_core.db import create_async_engine_from_url, create_session_factory, get_db, Base

    engine = create_async_engine_from_url(settings.DATABASE_URL)
    SessionLocal = create_session_factory(engine)

    # Override get_db in your app:
    async def get_db_override():
        async with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = get_db_override
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import AsyncIterator

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def create_async_engine_from_url(
    url: str,
    *,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_timeout: int = 30,
    pool_pre_ping: bool = True,
    echo: bool = False,
) -> AsyncEngine:
    """Create an async SQLAlchemy engine with sensible defaults.

    Pool-size parameters are only applied for poolable backends (e.g.
    PostgreSQL).  SQLite uses a StaticPool and ignores them.
    """
    kwargs: dict = {
        "echo": echo,
        "pool_pre_ping": pool_pre_ping,
    }
    # SQLite (used in tests) does not support pool_size / max_overflow
    if not url.startswith("sqlite"):
        kwargs.update(
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
        )
    return create_async_engine(url, **kwargs)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return an async session factory bound to the given engine."""
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# Sentinel session factory — product APIs must override get_db via
# ``app.dependency_overrides[get_db] = ...`` before serving requests.
_session_factory: async_sessionmaker[AsyncSession] | None = None


def set_session_factory(factory: async_sessionmaker[AsyncSession]) -> None:
    """Set the global session factory used by the default ``get_db`` dependency."""
    global _session_factory
    _session_factory = factory


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a database session.

    Product APIs should either:
    1. Call ``set_session_factory()`` at startup, or
    2. Override this dependency via ``app.dependency_overrides[get_db]``.
    """
    if _session_factory is None:
        raise RuntimeError(
            "Database session factory not configured. "
            "Call set_session_factory() or override get_db via app.dependency_overrides."
        )
    async with _session_factory() as session:
        yield session


class Base(AsyncAttrs, DeclarativeBase):
    """Shared declarative base with common columns.

    Product models inherit from this base and add their own columns::

        class Contact(Base):
            __tablename__ = "contacts"
            name: Mapped[str] = mapped_column()
    """

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
