"""Role-based access control guards for FastAPI endpoints.

Usage:
    @router.get("/", dependencies=[Depends(require_roles("CEO", "ADMIN"))])
    async def my_endpoint(actor: dict = Depends(require_roles("CEO", "ADMIN"))):
        org_id = int(actor["org_id"])
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from fastapi import Depends, HTTPException, status

Role = Literal[
    "CEO", "ADMIN", "MANAGER", "STAFF",
    "OWNER", "TECH_LEAD", "OPS_MANAGER",
    "DEVELOPER", "VIEWER", "EMPLOYEE",
]

# Override this in your app to provide the actual user extraction logic
_get_current_user: Callable[..., Awaitable[dict[str, Any]]] | None = None


def set_user_dependency(dep: Callable[..., Awaitable[dict[str, Any]]]) -> None:
    """Set the FastAPI dependency that extracts the current user from the request."""
    global _get_current_user
    _get_current_user = dep


def require_roles(*allowed_roles: str) -> Callable[..., Awaitable[dict[str, Any]]]:
    async def _guard(user: dict[str, Any] = Depends(_get_current_user)) -> dict[str, Any]:
        if user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role {user.get('role')!r} not in {allowed_roles}",
            )
        return user
    return _guard


def require_ceo_executive_roles() -> Callable[..., Awaitable[dict[str, Any]]]:
    return require_roles("CEO", "ADMIN")


def require_sensitive_financial_roles() -> Callable[..., Awaitable[dict[str, Any]]]:
    return require_roles("CEO", "ADMIN", "OPS_MANAGER")
