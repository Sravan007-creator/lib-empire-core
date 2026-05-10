"""empireoe-core — shared backend library for Empire FastAPI backends."""
__version__ = "0.3.0"

# Auth
from empireoe_core.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
    validate_password_complexity,
    require_roles,
    create_service_token,
    verify_service_token,
    create_delete_account_router,
    delete_account_service,
)

# Config
from empireoe_core.config import EmpireBaseSettings

# Database
from empireoe_core.db import (
    Base,
    create_async_engine_from_url,
    create_session_factory,
    get_db,
    set_session_factory,
)

# Models / Mixins
from empireoe_core.models import AuditEventBase, TenantMixin, TimestampMixin

# Tenant isolation
from empireoe_core.tenant import scope_query, strip_protected_fields, PROTECTED_FIELDS

# Audit
from empireoe_core.audit import record_action

# Pagination
from empireoe_core.pagination import PaginatedResponse, PaginationParams, paginate

# Health
from empireoe_core.health import create_health_router

# Sentry
from empireoe_core.sentry import init_sentry

# Middleware
from empireoe_core.middleware import setup_cors, setup_request_logging

# Lead routing
from empireoe_core.lead_router import Assignee, route_lead, should_notify

# AI gateway
from empireoe_core.ai import (
    AIBadResponse,
    AIError,
    AIRateLimited,
    AIServiceUnavailable,
    AISettings,
    ChatResult,
    TokenUsage,
    chat_completion,
    chat_completion_with_usage,
    redact_pii,
)

__all__ = [
    # Auth
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "verify_password",
    "validate_password_complexity",
    "require_roles",
    "create_service_token",
    "verify_service_token",
    "create_delete_account_router",
    "delete_account_service",
    # Config
    "EmpireBaseSettings",
    # Database
    "Base",
    "create_async_engine_from_url",
    "create_session_factory",
    "get_db",
    "set_session_factory",
    # Models
    "AuditEventBase",
    "TenantMixin",
    "TimestampMixin",
    # Tenant
    "scope_query",
    "strip_protected_fields",
    "PROTECTED_FIELDS",
    # Audit
    "record_action",
    # Pagination
    "PaginatedResponse",
    "PaginationParams",
    "paginate",
    # Health
    "create_health_router",
    # Sentry
    "init_sentry",
    # Middleware
    "setup_cors",
    "setup_request_logging",
    # AI gateway
    "AIError",
    "AIServiceUnavailable",
    "AIRateLimited",
    "AIBadResponse",
    "AISettings",
    "ChatResult",
    "TokenUsage",
    "chat_completion",
    "chat_completion_with_usage",
    "redact_pii",
    # Lead routing
    "Assignee",
    "route_lead",
    "should_notify",
]
