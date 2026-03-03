"""Tests for project CRUD, membership, and permission endpoints."""

import pytest


async def register_and_login(client, email, name="Test User", password="pass123"):
    """Helper: register a user, login, and return the auth header dict."""
    await client.post("/api/v1/auth/register", json={
        "email": email, "name": name, "password": password,
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": email, "password": password,
    })
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# --- Project CRUD ---


@pytest.mark.asyncio
async def test_create_project(client):
    headers = await register_and_login(client, "creator@test.com")
    resp = await client.post("/api/v1/projects", json={
        "name": "MI Study",
        "description": "Myocardial infarction detection",
    }, headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "MI Study"
    assert data["description"] == "Myocardial infarction detection"
    assert data["role"] == "admin"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_project_user_is_admin_member(client):
    headers = await register_and_login(client, "admin-check@test.com")
    resp = await client.post("/api/v1/projects", json={
        "name": "Test Project",
    }, headers=headers)
    project_id = resp.json()["id"]

    members_resp = await client.get(
        f"/api/v1/projects/{project_id}/members", headers=headers
    )
    assert members_resp.status_code == 200
    members = members_resp.json()
    assert len(members) == 1
    assert members[0]["role"] == "admin"
    assert members[0]["email"] == "admin-check@test.com"


@pytest.mark.asyncio
async def test_list_projects_returns_only_user_projects(client):
    headers_a = await register_and_login(client, "usera@test.com", "User A")
    headers_b = await register_and_login(client, "userb@test.com", "User B")

    await client.post("/api/v1/projects", json={"name": "Project A"}, headers=headers_a)
    await client.post("/api/v1/projects", json={"name": "Project B"}, headers=headers_b)

    resp_a = await client.get("/api/v1/projects", headers=headers_a)
    assert resp_a.status_code == 200
    projects = resp_a.json()
    assert len(projects) == 1
    assert projects[0]["name"] == "Project A"

    resp_b = await client.get("/api/v1/projects", headers=headers_b)
    projects_b = resp_b.json()
    assert len(projects_b) == 1
    assert projects_b[0]["name"] == "Project B"


@pytest.mark.asyncio
async def test_get_project_as_member(client):
    headers = await register_and_login(client, "member-get@test.com")
    resp = await client.post("/api/v1/projects", json={"name": "Visible"}, headers=headers)
    project_id = resp.json()["id"]

    resp = await client.get(f"/api/v1/projects/{project_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Visible"


@pytest.mark.asyncio
async def test_get_project_as_non_member_returns_403(client):
    headers_owner = await register_and_login(client, "owner-get@test.com")
    headers_other = await register_and_login(client, "other-get@test.com")

    resp = await client.post("/api/v1/projects", json={"name": "Private"}, headers=headers_owner)
    project_id = resp.json()["id"]

    resp = await client.get(f"/api/v1/projects/{project_id}", headers=headers_other)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_project_as_admin(client):
    headers = await register_and_login(client, "update-admin@test.com")
    resp = await client.post("/api/v1/projects", json={"name": "Old Name"}, headers=headers)
    project_id = resp.json()["id"]

    resp = await client.put(f"/api/v1/projects/{project_id}", json={
        "name": "New Name",
        "description": "Updated description",
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"
    assert resp.json()["description"] == "Updated description"


@pytest.mark.asyncio
async def test_update_project_as_annotator_returns_403(client):
    headers_admin = await register_and_login(client, "upd-admin@test.com")
    headers_annotator = await register_and_login(client, "upd-annotator@test.com")

    resp = await client.post("/api/v1/projects", json={"name": "Locked"}, headers=headers_admin)
    project_id = resp.json()["id"]

    # Add annotator
    await client.post(f"/api/v1/projects/{project_id}/members", json={
        "email": "upd-annotator@test.com", "role": "annotator",
    }, headers=headers_admin)

    resp = await client.put(f"/api/v1/projects/{project_id}", json={
        "name": "Hacked",
    }, headers=headers_annotator)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_project_soft_deletes(client):
    headers = await register_and_login(client, "deleter@test.com")
    resp = await client.post("/api/v1/projects", json={"name": "To Delete"}, headers=headers)
    project_id = resp.json()["id"]

    resp = await client.delete(f"/api/v1/projects/{project_id}", headers=headers)
    assert resp.status_code == 204

    # No longer appears in list
    resp = await client.get("/api/v1/projects", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 0

    # Direct get returns 403 (non-member check fails since project is deleted)
    resp = await client.get(f"/api/v1/projects/{project_id}", headers=headers)
    # The project is soft-deleted so get_project returns None -> 404
    # But the membership check happens first in the dependency - member still exists
    # so the dependency passes, then get_project returns None -> 404
    assert resp.status_code == 404


# --- Membership ---


@pytest.mark.asyncio
async def test_add_member(client):
    headers_admin = await register_and_login(client, "mem-admin@test.com")
    headers_new = await register_and_login(client, "mem-new@test.com", "New Member")

    resp = await client.post("/api/v1/projects", json={"name": "Team Project"}, headers=headers_admin)
    project_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/projects/{project_id}/members", json={
        "email": "mem-new@test.com", "role": "annotator",
    }, headers=headers_admin)
    assert resp.status_code == 201
    assert resp.json()["email"] == "mem-new@test.com"
    assert resp.json()["role"] == "annotator"

    # New member can access the project
    resp = await client.get(f"/api/v1/projects/{project_id}", headers=headers_new)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_members(client):
    headers = await register_and_login(client, "list-mem@test.com")
    await register_and_login(client, "list-mem2@test.com", "Member 2")

    resp = await client.post("/api/v1/projects", json={"name": "Multi-member"}, headers=headers)
    project_id = resp.json()["id"]

    await client.post(f"/api/v1/projects/{project_id}/members", json={
        "email": "list-mem2@test.com", "role": "viewer",
    }, headers=headers)

    resp = await client.get(f"/api/v1/projects/{project_id}/members", headers=headers)
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 2
    emails = {m["email"] for m in members}
    assert "list-mem@test.com" in emails
    assert "list-mem2@test.com" in emails


@pytest.mark.asyncio
async def test_remove_member(client):
    headers_admin = await register_and_login(client, "rm-admin@test.com")
    headers_member = await register_and_login(client, "rm-member@test.com", "To Remove")

    resp = await client.post("/api/v1/projects", json={"name": "Shrinking Team"}, headers=headers_admin)
    project_id = resp.json()["id"]

    # Add member
    await client.post(f"/api/v1/projects/{project_id}/members", json={
        "email": "rm-member@test.com", "role": "annotator",
    }, headers=headers_admin)

    # Get the member's user_id
    me_resp = await client.get("/api/v1/auth/me", headers=headers_member)
    member_user_id = me_resp.json()["id"]

    # Remove member
    resp = await client.delete(
        f"/api/v1/projects/{project_id}/members/{member_user_id}",
        headers=headers_admin,
    )
    assert resp.status_code == 204

    # Removed user can no longer access
    resp = await client.get(f"/api/v1/projects/{project_id}", headers=headers_member)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_non_member_cannot_access_project(client):
    headers_owner = await register_and_login(client, "access-owner@test.com")
    headers_outsider = await register_and_login(client, "access-outsider@test.com")

    resp = await client.post("/api/v1/projects", json={"name": "Restricted"}, headers=headers_owner)
    project_id = resp.json()["id"]

    # Cannot get project
    resp = await client.get(f"/api/v1/projects/{project_id}", headers=headers_outsider)
    assert resp.status_code == 403

    # Cannot list members
    resp = await client.get(f"/api/v1/projects/{project_id}/members", headers=headers_outsider)
    assert resp.status_code == 403

    # Cannot add members
    resp = await client.post(f"/api/v1/projects/{project_id}/members", json={
        "email": "someone@test.com",
    }, headers=headers_outsider)
    assert resp.status_code == 403

    # Cannot update
    resp = await client.put(f"/api/v1/projects/{project_id}", json={
        "name": "Hacked",
    }, headers=headers_outsider)
    assert resp.status_code == 403

    # Cannot delete
    resp = await client.delete(f"/api/v1/projects/{project_id}", headers=headers_outsider)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_project_requires_auth(client):
    resp = await client.post("/api/v1/projects", json={"name": "No Auth"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_add_member_nonexistent_email_returns_404(client):
    headers = await register_and_login(client, "add-nonexist@test.com")
    resp = await client.post("/api/v1/projects", json={"name": "Test"}, headers=headers)
    project_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/projects/{project_id}/members", json={
        "email": "nobody@test.com",
    }, headers=headers)
    assert resp.status_code == 404
