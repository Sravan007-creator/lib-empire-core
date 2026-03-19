"""Common middleware setup for Empire backends.

Usage::

    from empireoe_core.middleware import setup_cors, setup_request_logging

    setup_cors(app, origins=["https://app.empireoe.com"])
    setup_request_logging(app)
"""

from __future__ import annotations

import logging
import time
from typing import Sequence

from fastapi import FastAPI, Request
from starlette.middleware.cors import CORSMiddleware

logger = logging.getLogger("empireoe_core.middleware")


def setup_cors(
    app: FastAPI,
    origins: Sequence[str],
    *,
    allow_credentials: bool = True,
    allow_methods: Sequence[str] = ("*",),
    allow_headers: Sequence[str] = ("*",),
) -> None:
    """Add CORS middleware with the given origins."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_credentials=allow_credentials,
        allow_methods=list(allow_methods),
        allow_headers=list(allow_headers),
    )


def setup_request_logging(app: FastAPI) -> None:
    """Add middleware that logs method, path, status code, and latency for every request."""

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s %s %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            latency_ms,
        )
        return response
