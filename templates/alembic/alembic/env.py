"""Alembic env.py — async PostgreSQL migrations.

Patterns from BOS (proven in production):
- Async engine via asyncpg
- Uses DATABASE_URL from environment
- Imports all models via load_all_models()
- Renders column types for autogenerate
"""

from __future__ import annotations

import asyncio
import os

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

load_dotenv()

# Import your Base and models here:
# from app.models.base import Base
# from app.models.registry import load_all_models
# load_all_models()
# target_metadata = Base.metadata

target_metadata = None  # Replace with your Base.metadata


def run_migrations_offline() -> None:
    url = os.getenv("DATABASE_URL", "")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    config_section = context.config.get_section(context.config.config_ini_section, {})
    config_section["sqlalchemy.url"] = os.getenv("DATABASE_URL", "")

    connectable = async_engine_from_config(
        config_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
