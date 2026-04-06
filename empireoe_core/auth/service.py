"""Service-to-service authentication via signed JWTs.

When one backend needs to call another (e.g., esa-ai calls BOS for contacts),
it creates a service JWT with its own identity. The receiving backend validates
the JWT using the shared SERVICE_SECRET_KEY.

Usage (caller):
    from empireoe_core.auth.service import create_service_token
    token = create_service_token("esa-ai", service_secret)
    headers = {"Authorization": f"Bearer {token}", "X-Service-Name": "esa-ai"}
    response = await httpx.get(f"{BOS_URL}/api/v1/contacts", headers=headers)

Usage (receiver):
    from empireoe_core.auth.service import verify_service_token
    
    async def get_service_caller(authorization: str = Header(...)) -> dict:
        token = authorization.replace("Bearer ", "")
        return verify_service_token(token, service_secret)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from jwt.exceptions import PyJWTError as JWTError

ALGORITHM = "HS256"
SERVICE_TOKEN_EXPIRE_MINUTES = 5  # Short-lived — services should request fresh tokens


def create_service_token(
    service_name: str,
    service_secret: str,
    *,
    expires_minutes: int = SERVICE_TOKEN_EXPIRE_MINUTES,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a short-lived JWT identifying the calling service."""
    payload = {
        "sub": service_name,
        "type": "service",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=expires_minutes),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, service_secret, algorithm=ALGORITHM)


def verify_service_token(token: str, service_secret: str) -> dict[str, Any]:
    """Verify a service JWT and return the payload.
    
    Raises ValueError if the token is invalid, expired, or not a service token.
    """
    try:
        payload = jwt.decode(token, service_secret, algorithms=[ALGORITHM])
        if payload.get("type") != "service":
            raise ValueError("Not a service token")
        if "sub" not in payload:
            raise ValueError("Service token missing subject")
        return payload
    except JWTError as exc:
        raise ValueError(f"Invalid service token: {exc}") from exc

