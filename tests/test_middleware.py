"""Tests for empireoe_core.middleware module."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from empireoe_core.middleware import setup_cors, setup_request_logging


@pytest.mark.asyncio
async def test_cors_headers():
    app = FastAPI()
    setup_cors(app, origins=["https://example.com"])

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.options(
            "/ping",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert resp.headers.get("access-control-allow-origin") == "https://example.com"


@pytest.mark.asyncio
async def test_request_logging(caplog):
    app = FastAPI()
    setup_request_logging(app)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    import logging
    with caplog.at_level(logging.INFO, logger="empireoe_core.middleware"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/ping")

    assert resp.status_code == 200
    assert any("GET" in rec.message and "/ping" in rec.message for rec in caplog.records)
