"""Sentry initialization wrapper for Empire backends.

Usage::

    from empireoe_core.sentry import init_sentry

    init_sentry(
        dsn=settings.SENTRY_DSN,
        environment="production",
        service_name="empireo-api",
    )
"""

from __future__ import annotations


def init_sentry(
    dsn: str,
    environment: str,
    service_name: str,
    *,
    traces_sample_rate: float = 0.1,
) -> None:
    """Initialize Sentry SDK with FastAPI integration.

    Does nothing if ``dsn`` is empty, so calling this is always safe
    even when Sentry is not configured.
    """
    if not dsn:
        return

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        server_name=service_name,
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
        ],
    )
