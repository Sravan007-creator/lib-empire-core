"""Stripe integration package — single source of truth for Stripe SDK use.

Per ADR-019, every Stripe call across Empire backends goes through this
package. The pinned API version, the idempotency-key convention, the
webhook signature verifier, and the error-mapping logic all live here so
version migrations become one-place changes.

Public surface:

    from empireoe_core.stripe import (
        STRIPE_API_VERSION,
        get_client,                    # platform-level Stripe client
        get_connected_client,          # per-connected-account client
        verify_webhook_signature,      # safe webhook ingest
        idempotency_key_for,           # business-op-keyed idempotency
        fingerprint_payload,           # SHA-256 fingerprint for safe logs
        StripeOperationError,          # normalized error type
    )

Direct ``import stripe`` outside this package is a code-review failure —
backends can add their own architecture guard to enforce that rule.

Backends pass their own settings object that exposes ``STRIPE_SECRET_KEY``
and ``STRIPE_WEBHOOK_SECRET`` (see ``StripeSettings`` protocol). The
library never imports product-specific config modules.
"""

from empireoe_core.stripe.client import (
    STRIPE_API_VERSION,
    StripeOperationError,
    StripeSettings,
    fingerprint_payload,
    get_client,
    get_connected_client,
    idempotency_key_for,
    verify_webhook_signature,
)

__all__ = [
    "STRIPE_API_VERSION",
    "StripeOperationError",
    "StripeSettings",
    "fingerprint_payload",
    "get_client",
    "get_connected_client",
    "idempotency_key_for",
    "verify_webhook_signature",
]
