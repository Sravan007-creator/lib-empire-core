"""Pinned Stripe SDK wrapper for all Empire backends (ADR-019).

Why this file exists:

* The Stripe API is versioned. Without an explicit ``api_version`` pin,
  Stripe defaults to the version that was current when the platform
  account was created — invisible drift that breaks tests months later.
* The Stripe Python SDK has shipped breaking changes between major
  versions (8.x → 15.x removed dict-access on ``StripeObject``, for
  example). One pin in this library means one place to bump.
* Every product backend in the portfolio currently pins Stripe to a
  different version range. This file is the single source of truth.

Bumping the pin: change ``STRIPE_API_VERSION`` here, run the full test
suite (every Stripe-touching test should be parametrized over this
version), update the ``stripe`` SDK pin in ``pyproject.toml``'s
``[stripe]`` extra, then file a follow-up to pull the new
``empireoe-core`` version in every product backend.

Settings injection: the library does NOT import any product-specific
config module. Callers pass a ``StripeSettings``-shaped object (anything
with ``STRIPE_SECRET_KEY`` and ``STRIPE_WEBHOOK_SECRET`` attributes —
typically the backend's own pydantic ``Settings`` instance).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Protocol, runtime_checkable

import stripe

logger = logging.getLogger("empireoe_core.stripe")

# Pinned API version. Locks the response shape we code against. See
# ADR-019 for the bump procedure. The two-string form (date + named
# release) matches Stripe's documented identifier syntax exactly.
STRIPE_API_VERSION: str = "2024-12-18.acacia"


# ---------------------------------------------------------------------------
# Settings protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class StripeSettings(Protocol):
    """Shape of the settings object backends pass into this module.

    Any object exposing these two attributes works — typically the
    backend's pydantic ``Settings`` instance. The library deliberately
    does not import product-specific config so it stays portable across
    all 7 product backends.
    """

    STRIPE_SECRET_KEY: str
    STRIPE_WEBHOOK_SECRET: str


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StripeOperationError(Exception):
    """Normalized error wrapper. All Stripe-side failures funnel through here.

    Carries the original Stripe error code + HTTP status so callers can
    branch on permanent vs transient failures without importing the
    Stripe SDK directly.
    """

    def __init__(
        self,
        message: str,
        *,
        stripe_code: str | None = None,
        http_status: int | None = None,
        original: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.stripe_code = stripe_code
        self.http_status = http_status
        self.original = original


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


def get_client(settings: StripeSettings) -> stripe.StripeClient:
    """Return a Stripe client authenticated with the platform secret key.

    Use for platform-account operations: account onboarding, listing
    connected accounts, platform-level reporting.
    """
    secret_key = getattr(settings, "STRIPE_SECRET_KEY", "") or ""
    if not secret_key:
        raise StripeOperationError(
            "STRIPE_SECRET_KEY not configured — Stripe operations disabled."
        )
    return stripe.StripeClient(
        api_key=secret_key,
        stripe_version=STRIPE_API_VERSION,
    )


def get_connected_client(
    stripe_account_id: str,
    settings: StripeSettings,
) -> stripe.StripeClient:
    """Return a client scoped to a connected (Standard or Express) account.

    Use for per-brand operations: creating a customer for a brand's
    client, charging a customer on the brand's connected account, etc.
    Requests automatically include the ``Stripe-Account: acct_…`` header.
    """
    if not stripe_account_id or not stripe_account_id.startswith("acct_"):
        raise StripeOperationError(
            f"Invalid stripe_account_id {stripe_account_id!r} — must start with 'acct_'."
        )
    secret_key = getattr(settings, "STRIPE_SECRET_KEY", "") or ""
    if not secret_key:
        raise StripeOperationError(
            "STRIPE_SECRET_KEY not configured — Stripe operations disabled."
        )
    return stripe.StripeClient(
        api_key=secret_key,
        stripe_version=STRIPE_API_VERSION,
        stripe_account=stripe_account_id,
    )


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def idempotency_key_for(
    *,
    operation: str,
    entity_type: str,
    entity_id: int | str,
    suffix: str | None = None,
) -> str:
    """Build a deterministic idempotency key for a business operation.

    Stripe uses this header to dedupe writes within a 24-hour window. The
    key is constructed from the operation name + the entity it's acting
    on, so retrying the same conceptual write produces the same key (and
    Stripe returns the cached response instead of re-charging).

    Example:
        >>> idempotency_key_for(
        ...     operation="create_invoice",
        ...     entity_type="engagement",
        ...     entity_id=42,
        ... )
        'bos:create_invoice:engagement:42'

    The ``bos:`` prefix is preserved across all Empire backends so a
    single Stripe account can host multiple products without key
    collisions; the operation/entity tuple distinguishes them.
    """
    parts = ["bos", operation, entity_type, str(entity_id)]
    if suffix:
        parts.append(suffix)
    return ":".join(parts)


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------


def verify_webhook_signature(
    payload: bytes,
    signature_header: str,
    secret: str,
    *,
    tolerance_seconds: int = 300,
) -> dict[str, Any]:
    """Verify a Stripe webhook signature and return the parsed event.

    Wraps ``stripe.Webhook.construct_event`` so callers don't need to
    import the SDK. Raises ``StripeOperationError`` on any failure with
    a stable error code:

    * ``invalid_signature`` — signature didn't verify
    * ``replay_too_old``   — timestamp is outside the tolerance window
                             (Stripe SDK reports this as a
                             SignatureVerificationError; mapped to
                             ``invalid_signature`` for callers)
    * ``invalid_payload``  — body wasn't valid JSON

    The 5-minute default tolerance matches Stripe's recommended ceiling
    for replay protection.
    """
    if not secret:
        raise StripeOperationError(
            "Stripe webhook secret not configured.",
            stripe_code="invalid_signature",
        )
    try:
        event = stripe.Webhook.construct_event(
            payload,
            signature_header,
            secret,
            tolerance=tolerance_seconds,
        )
    except stripe.SignatureVerificationError as exc:
        raise StripeOperationError(
            "Stripe webhook signature verification failed.",
            stripe_code="invalid_signature",
            http_status=401,
            original=exc,
        ) from exc
    except ValueError as exc:
        raise StripeOperationError(
            f"Stripe webhook payload invalid: {exc}",
            stripe_code="invalid_payload",
            http_status=400,
            original=exc,
        ) from exc

    # Return the parsed payload as a plain dict so downstream code never
    # needs to import the Stripe SDK.
    #
    # We deliberately return ``json.loads(payload)`` rather than calling
    # ``event.to_dict()`` or ``dict(event)``:
    #
    # * ``construct_event`` already proved the payload is valid JSON and the
    #   signature is authentic, so re-parsing is safe and O(1) in practice.
    # * ``to_dict()`` is deprecated in Stripe SDK ≥ 15 and raises
    #   ``AttributeError`` when the event object has a non-standard shape
    #   (e.g. platform events without a top-level ``object`` key).
    # * ``dict(event)`` in SDK ≥ 15 returns a shallow copy that may omit
    #   nested ``data.object`` fields depending on the SDK's internal type.
    #
    # The raw payload is the canonical source of truth; using it here
    # insulates callers from any future Stripe SDK model changes.
    import json as _json  # local to avoid circular at module level

    return _json.loads(payload)


# ---------------------------------------------------------------------------
# Helpers exposed for testability
# ---------------------------------------------------------------------------


def fingerprint_payload(payload: bytes) -> str:
    """SHA-256 fingerprint of a webhook payload, for safe logging without
    leaking PII. Truncated to 16 hex chars."""
    return hashlib.sha256(payload).hexdigest()[:16]
