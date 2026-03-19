"""Tests for empireoe_core.health module."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from empireoe_core.health import create_health_router


@pytest.mark.asyncio
async def test_health_endpoint():
    app = FastAPI()
    app.include_router(create_health_router("test-service", "1.2.3"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "test-service"
    assert data["version"] == "1.2.3"
