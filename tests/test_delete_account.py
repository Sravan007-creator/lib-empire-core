"""Tests for the shared delete-account handler."""


import pytest
import pytest_asyncio
from sqlalchemy import Boolean, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from empireoe_core.auth.delete_account import (
    create_delete_account_router,
    delete_account_service,
)
from empireoe_core.db import create_session_factory
from empireoe_core.models import AuditEventBase


class _TestBase(DeclarativeBase):
    pass


class Organization(_TestBase):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))


class User(_TestBase):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), default="Test User")
    email: Mapped[str] = mapped_column(String(255), unique=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    totp_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    bio: Mapped[str | None] = mapped_column(String(500), nullable=True)


class AuditEvent(AuditEventBase, _TestBase):
    __tablename__ = "audit_events"


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    factory = create_session_factory(engine)
    async with factory() as session:
        session.add(Organization(id=1, name="Org A"))
        session.add(Organization(id=2, name="Org B"))
        await session.flush()
        yield session


async def _seed_user(db, *, user_id=1, org_id=1, email="alice@example.com",
                     is_active=True, token_version=1, totp_secret=None,
                     mfa_enabled=False, phone="+971501234567",
                     avatar_url="https://cdn.example.com/avatar.jpg", bio="Hello world"):
    user = User(id=user_id, organization_id=org_id, name="Alice", email=email,
                phone=phone, avatar_url=avatar_url, is_active=is_active,
                token_version=token_version, totp_secret=totp_secret,
                mfa_enabled=mfa_enabled, bio=bio)
    db.add(user)
    await db.flush()
    return user


class TestDeleteAccountService:

    async def test_happy_path(self, db):
        user = await _seed_user(db)
        result = await delete_account_service(db, user_model=User, user_id=user.id, organization_id=1)
        assert result.is_active is False
        assert result.name == "Deleted User"
        assert result.email == f"deleted_{user.id}@deleted.invalid"
        assert result.phone is None
        assert result.avatar_url is None
        assert result.token_version == 2

    async def test_tenant_isolation_blocks_cross_org(self, db):
        user = await _seed_user(db, org_id=1)
        with pytest.raises(ValueError, match="not found in organization 2"):
            await delete_account_service(db, user_model=User, user_id=user.id, organization_id=2)
        await db.refresh(user)
        assert user.is_active is True

    async def test_already_inactive_raises(self, db):
        user = await _seed_user(db, is_active=False)
        with pytest.raises(ValueError, match="already deactivated"):
            await delete_account_service(db, user_model=User, user_id=user.id, organization_id=1)

    async def test_nonexistent_user_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            await delete_account_service(db, user_model=User, user_id=9999, organization_id=1)

    async def test_token_version_bumped(self, db):
        user = await _seed_user(db, token_version=5)
        result = await delete_account_service(db, user_model=User, user_id=user.id, organization_id=1)
        assert result.token_version == 6

    async def test_mfa_cleared(self, db):
        user = await _seed_user(db, totp_secret="JBSWY3DPEHPK3PXP", mfa_enabled=True)
        result = await delete_account_service(db, user_model=User, user_id=user.id, organization_id=1)
        assert result.totp_secret is None
        assert result.mfa_enabled is False

    async def test_extra_scrub_fields(self, db):
        user = await _seed_user(db, bio="Hello world")
        result = await delete_account_service(db, user_model=User, user_id=user.id, organization_id=1, scrub_fields={"bio": None})


class TestDeleteAccountRouter:

    @pytest_asyncio.fixture
    async def app(self, engine):
        from fastapi import FastAPI, Request
        from empireoe_core.db import set_session_factory, get_db
        factory = create_session_factory(engine)
        set_session_factory(factory)
        _app = FastAPI()
        async with factory() as session:
            session.add(Organization(id=1, name="Org A"))
            session.add(Organization(id=2, name="Org B"))
            session.add(User(id=10, organization_id=1, name="Bob", email="bob@example.com", is_active=True, token_version=1))
            session.add(User(id=20, organization_id=2, name="Carol", email="carol@example.com", is_active=True, token_version=1))
            await session.commit()

        async def mock_get_current_user(request: Request):
            uid = request.headers.get("X-Test-User-Id", "10")
            oid = request.headers.get("X-Test-Org-Id", "1")
            return {"id": uid, "org_id": oid, "role": "STAFF"}

        router = create_delete_account_router(user_model=User, audit_model=AuditEvent,
                                              get_current_user=mock_get_current_user, cookie_name="session_token")
        _app.include_router(router, prefix="/api/v1/auth", tags=["auth"])
        return _app

    async def test_delete_returns_200(self, app):
        from httpx import ASGITransport, AsyncClient
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/api/v1/auth/delete-account", headers={"X-Test-User-Id": "10", "X-Test-Org-Id": "1"})
        assert resp.status_code == 200
        assert resp.json() == {"message": "Account deleted successfully"}

    async def test_delete_wrong_org_returns_404(self, app):
        from httpx import ASGITransport, AsyncClient
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/api/v1/auth/delete-account", headers={"X-Test-User-Id": "10", "X-Test-Org-Id": "2"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "User not found"

    async def test_delete_nonexistent_user_returns_404(self, app):
        from httpx import ASGITransport, AsyncClient
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/api/v1/auth/delete-account", headers={"X-Test-User-Id": "9999", "X-Test-Org-Id": "1"})
        assert resp.status_code == 404

    async def test_audit_event_recorded(self, app, engine):
        from httpx import ASGITransport, AsyncClient
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.delete("/api/v1/auth/delete-account", headers={"X-Test-User-Id": "20", "X-Test-Org-Id": "2"})
        factory = create_session_factory(engine)
        async with factory() as session:
            result = await session.execute(select(AuditEvent).where(AuditEvent.event_type == "user.account_deleted"))
            events = result.scalars().all()
            assert len(events) == 1
            assert events[0].actor_user_id == 20
            assert events[0].organization_id == 2
            assert events[0].entity_type == "user"
