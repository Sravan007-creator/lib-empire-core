"""Tests for empireoe_core.sentry module."""

from __future__ import annotations

from empireoe_core.sentry import init_sentry


def test_init_sentry_empty_dsn_does_nothing():
    """Calling init_sentry with empty DSN should be a no-op (no exception)."""
    init_sentry(dsn="", environment="test", service_name="test")
