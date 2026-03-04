"""Tests for auth API endpoints: register, login, and /me."""

import pytest


@pytest.mark.asyncio
async def test_register_user(client):
    response = await client.post("/api/v1/auth/register", json={
        "email": "newuser@test.com",
        "name": "New User",
        "password": "securepass123",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@test.com"
    assert data["role"] == "user"
    assert "id" in data


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    await client.post("/api/v1/auth/register", json={
        "email": "dupe@test.com", "name": "First", "password": "pass1234"
    })
    response = await client.post("/api/v1/auth/register", json={
        "email": "dupe@test.com", "name": "Second", "password": "pass4567"
    })
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_login_user(client):
    await client.post("/api/v1/auth/register", json={
        "email": "login@test.com", "name": "Login User", "password": "securepass123"
    })
    response = await client.post("/api/v1/auth/login", json={
        "email": "login@test.com", "password": "securepass123"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Login successful"
    assert data["user"]["email"] == "login@test.com"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/api/v1/auth/register", json={
        "email": "wrong@test.com", "name": "Wrong", "password": "securepass123"
    })
    response = await client.post("/api/v1/auth/login", json={
        "email": "wrong@test.com", "password": "wrongpass"
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user(client):
    await client.post("/api/v1/auth/register", json={
        "email": "me@test.com", "name": "Me", "password": "pass1234"
    })
    await client.post("/api/v1/auth/login", json={
        "email": "me@test.com", "password": "pass1234"
    })
    # Cookies are set automatically by httpx from Set-Cookie headers
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "me@test.com"


@pytest.mark.asyncio
async def test_protected_route_without_token(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code in (401, 403)
