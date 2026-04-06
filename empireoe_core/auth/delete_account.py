"""Shared delete-account handler for Google Play data-deletion compliance.

Every Empire product API needs a DELETE /auth/delete-account endpoint.
This module provides the service function and a FastAPI router factory
so each API can wire it in with one line.

Service usage::

    from empireoe_core.auth.delete_account import delete_account_service

    user = await delete_account_service(
        db=db,
        user_model=User,
        user_id=actor["id"],
        organization_id=actor["org_id"],
    )

Router factory usage::

    from empireoe_core.auth.delete_account import create_delete_account_router

    router = create_delete_account_router(
        user_model=User,
        audit_model=AuditEvent,        # optional — for audit trail
        get_current_user=get_current_user,  # your FastAPI dependency
    )
    app.include_router(router, prefix="/api/v1/auth", tags=["auth"])
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from empireoe_core.db import get_db

logger = logging.getLogger(__name__)


async def delete_account_service(
    db: AsyncSession,
    *,
    user_model: type,
    user_id: int,
    organization_id: int,
    scrub_fields: dict[str, Any] | None = None,
) -> Any:
    """Soft-delete a user account with PII scrubbing and token revocation.

    Args:
        db: Async database session.
        user_model: The SQLAlchemy User model class for this product API.
        user_id: ID of the user requesting deletion.
        organization_id: Must match the user's org (tenant isolation).
        scrub_fields: Optional extra fields to overwrite (e.g. {"phone": None}).

    Returns:
        The updated user model instance.

    Raises:
        ValueError: If user not found, already inactive, or org mismatch.
    """
    stmt = (
        select(user_model)
        .where(user_model.id == user_id)
        .where(user_model.organization_id == organization_id)
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        raise ValueError(f"User {user_id} not found in organization {organization_id}")

    if not getattr(user, "is_active", True):
        raise ValueError(f"User {user_id} is already deactivated")

    # Scrub PII
    if hasattr(user, "name"):
        user.name = "Deleted User"
    if hasattr(user, "email"):
        user.email = f"deleted_{user.id}@deleted.invalid"
    if hasattr(user, "phone"):
        user.phone = None
    if hasattr(user, "avatar_url"):
        user.avatar_url = None

    # Deactivate
    if hasattr(user, "is_active"):
        user.is_active = False

    # Revoke tokens by bumping version
    if hasattr(user, "token_version"):
        user.token_version = int(user.token_version or 1) + 1

    # Clear MFA secrets if present
    if hasattr(user, "totp_secret"):
        user.totp_secret = None
    if hasattr(user, "mfa_enabled"):
        user.mfa_enabled = False

    # Apply any extra scrub fields
    if scrub_fields:
        for field, value in scrub_fields.items():
            if hasattr(user, field):
                setattr(user, field, value)

    await db.commit()

    logger.info(
        "Account deleted for user %d (org %d)",
        user_id,
        organization_id,
    )
    return user


def create_delete_account_router(
    *,
    user_model: type,
    audit_model: type | None = None,
    get_current_user: Any,
    cookie_name: str | None = None,
    scrub_fields: dict[str, Any] | None = None,
) -> APIRouter:
    """Create a FastAPI router with DELETE /delete-account.

    Args:
        user_model: SQLAlchemy User model for this product API.
        audit_model: Optional AuditEvent model — if provided, an audit
            record is written on successful deletion.
        get_current_user: FastAPI dependency that returns a dict with
            at least ``id`` and ``org_id`` keys.
        cookie_name: Optional session cookie to clear on deletion.
        scrub_fields: Extra fields to overwrite during PII scrubbing.

    Returns:
        A FastAPI APIRouter to include in the app.
    """
    router = APIRouter()

    @router.delete("/delete-account")
    async def delete_account(
        request: Request,
        response: Response,
        user: dict = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> dict[str, str]:
        """Delete the authenticated user's account (Google Play compliance).

        Soft-deletes the account by scrubbing PII, deactivating, and
        revoking all tokens. This action is irreversible.
        """
        user_id = int(user["id"])
        org_id = int(user["org_id"])

        try:
            await delete_account_service(
                db,
                user_model=user_model,
                user_id=user_id,
                organization_id=org_id,
                scrub_fields=scrub_fields,
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            ) from None

        # Record audit trail if model provided
        if audit_model is not None:
            from empireoe_core.audit import record_action

            ip = request.client.host if request.client else "unknown"
            await record_action(
                db,
                model=audit_model,
                event_type="user.account_deleted",
                actor_user_id=user_id,
                organization_id=org_id,
                entity_type="user",
                entity_id=str(user_id),
                payload_json={
                    "ip": ip,
                    "endpoint": "/auth/delete-account",
                },
            )
            await db.commit()

        # Clear session cookie if configured
        if cookie_name:
            response.delete_cookie(key=cookie_name, path="/")

        return {"message": "Account deleted successfully"}

    return router
