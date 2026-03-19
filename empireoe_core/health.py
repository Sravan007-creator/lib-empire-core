"""Health-check router factory for Empire backends.

Usage::

    from empireoe_core.health import create_health_router

    app.include_router(create_health_router("empireo-api", "1.0.0"))
"""

from __future__ import annotations

from fastapi import APIRouter


def create_health_router(service_name: str, version: str) -> APIRouter:
    """Return a router with a ``GET /api/v1/health`` endpoint."""
    router = APIRouter(tags=["health"])

    @router.get("/api/v1/health")
    async def health_check() -> dict:
        return {
            "status": "ok",
            "service": service_name,
            "version": version,
        }

    return router
