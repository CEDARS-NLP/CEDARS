"""Tests for admin queue monitoring API."""
import pytest
from app.auth.models import UserRole


async def _make_admin(client, app):
    """Register, login, and promote to platform admin."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "admin@test.com", "name": "Admin", "password": "testpass123"},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "testpass123"},
    )
    from app.common.database import get_session
    from app.auth.models import User
    from sqlalchemy import update

    async for session in app.dependency_overrides[get_session]():
        await session.execute(
            update(User)
            .where(User.email == "admin@test.com")
            .values(role=UserRole.PLATFORM_ADMIN)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_get_queues(app, client):
    """Admin can list queue stats."""
    await _make_admin(client, app)
    resp = await client.get("/api/v1/admin/queues")
    assert resp.status_code == 200
    data = resp.json()
    assert "queues" in data


@pytest.mark.asyncio
async def test_get_queues_forbidden_for_regular_user(app, auth_client):
    """Regular users cannot access admin endpoints."""
    resp = await auth_client.get("/api/v1/admin/queues")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_workers(app, client):
    """Admin can list worker status."""
    await _make_admin(client, app)
    resp = await client.get("/api/v1/admin/workers")
    assert resp.status_code == 200
    data = resp.json()
    assert "workers" in data


@pytest.mark.asyncio
async def test_list_jobs(app, client):
    """Admin can list background jobs."""
    await _make_admin(client, app)
    resp = await client.get("/api/v1/admin/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
