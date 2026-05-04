# empireoe-core

Shared Python backend library for all Empire FastAPI backends.

## What it provides

- **Auth** -- JWT token creation/verification, PBKDF2-SHA256 password hashing, password complexity validation
- **RBAC** -- `require_roles()` FastAPI dependency for role-based access control
- **Database** -- Async SQLAlchemy engine + session factory
- **Health checks** -- `/health`, `/health/live`, `/health/ready` router
- **Signals** -- In-process pub/sub event system for audit trails
- **Tenant isolation** -- `scope_query()` helper + protected field stripping
- **Config** -- Base pydantic-settings class with common fields
- **AI gateway** -- Single `chat_completion()` for OpenAI / Groq / Anthropic with cost-tracking logs, optional PII redaction, and typed errors (`AIServiceUnavailable`, `AIRateLimited`, `AIBadResponse`)

## Installation

```bash
pip install -e .     # from local checkout
```

## Usage

```python
from empireoe_core.auth import create_access_token, require_roles, hash_password
from empireoe_core.db import create_engine_from_url, create_session_factory
from empireoe_core.api import create_health_router
from empireoe_core.signals import publish_signal, SignalEnvelope
from empireoe_core.config import EmpireBaseSettings
from empireoe_core.tenant import scope_query
from empireoe_core.ai import chat_completion, AIServiceUnavailable
```

### AI gateway

```python
from empireoe_core.ai import chat_completion

text = await chat_completion(
    [{"role": "user", "content": "Say hi"}],
    system="You are a job advisor.",
    max_tokens=200,
    redact_pii=True,
)
```

Provider is selected via `AI_PROVIDER` env (`openai` / `groq` / `anthropic`). The matching `*_API_KEY` must be set. Default model can be overridden via `AI_MODEL_DEFAULT` or per-call `model=`.
