# CLAUDE.md — empireoe-core (CONFIDENTIAL)

## Classification
This is a CONFIDENTIAL backend library. Owned exclusively by Nidin Nover.

## What This Is
Shared Python package for all Empire FastAPI backends: auth, RBAC, tenant isolation, DB sessions, health checks, signals, base config.

## Rules
- Never share this code or architecture with frontend developers
- Never reference this package name in frontend repos
- All functions that touch data MUST accept organization_id as required int
