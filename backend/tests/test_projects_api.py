"""Tests for project CRUD, membership, and permission endpoints."""

import pytest


async def register_and_login(client, email, name="Test User", password="pass1234"):
    """Helper: register a user and login. Cookies are set automatically by httpx."""
    await client.post("/api/v1/auth/register", json={
        "email": email, "name": name, "password": password,
    })
    await client.post("/api/v1/auth/login", json={
        "email": email, "password": password,
    })


# --- Project CRUD ---


@pytest.mark.asyncio
async def test_create_project(client):
    await register_and_login(client, "creator@test.com")
    resp = await client.post("/api/v1/projects", json={
        "name": "MI Study",
        "description": "Myocardial infarction detection",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "MI Study"
    assert data["description"] == "Myocardial infarction detection"
    assert data["role"] == "admin"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_project_user_is_admin_member(client):
    await register_and_login(client, "admin-check@test.com")
    resp = await client.post("/api/v1/projects", json={
        "name": "Test Project",
    })
    project_id = resp.json()["id"]

    members_resp = await client.get(f"/api/v1/projects/{project_id}/members")
    assert members_resp.status_code == 200
    members = members_resp.json()
    assert len(members) == 1
    assert members[0]["role"] == "admin"
    assert members[0]["email"] == "admin-check@test.com"


@pytest.mark.asyncio
async def test_list_projects_returns_only_user_projects(client_factory):
    async with client_factory() as client_a, client_factory() as client_b:
        await register_and_login(client_a, "usera@test.com", "User A")
        await register_and_login(client_b, "userb@test.com", "User B")

        await client_a.post("/api/v1/projects", json={"name": "Project A"})
        await client_b.post("/api/v1/projects", json={"name": "Project B"})

        resp_a = await client_a.get("/api/v1/projects")
        assert resp_a.status_code == 200
        projects = resp_a.json()
        assert len(projects) == 1
        assert projects[0]["name"] == "Project A"

        resp_b = await client_b.get("/api/v1/projects")
        projects_b = resp_b.json()
        assert len(projects_b) == 1
        assert projects_b[0]["name"] == "Project B"


@pytest.mark.asyncio
async def test_get_project_as_member(client):
    await register_and_login(client, "member-get@test.com")
    resp = await client.post("/api/v1/projects", json={"name": "Visible"})
    project_id = resp.json()["id"]

    resp = await client.get(f"/api/v1/projects/{project_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Visible"


@pytest.mark.asyncio
async def test_get_project_as_non_member_returns_403(client_factory):
    async with client_factory() as client_owner, client_factory() as client_other:
        await register_and_login(client_owner, "owner-get@test.com")
        await register_and_login(client_other, "other-get@test.com")

        resp = await client_owner.post("/api/v1/projects", json={"name": "Private"})
        project_id = resp.json()["id"]

        resp = await client_other.get(f"/api/v1/projects/{project_id}")
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_project_as_admin(client):
    await register_and_login(client, "update-admin@test.com")
    resp = await client.post("/api/v1/projects", json={"name": "Old Name"})
    project_id = resp.json()["id"]

    resp = await client.put(f"/api/v1/projects/{project_id}", json={
        "name": "New Name",
        "description": "Updated description",
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"
    assert resp.json()["description"] == "Updated description"


@pytest.mark.asyncio
async def test_update_project_as_annotator_returns_403(client_factory):
    async with client_factory() as client_admin, client_factory() as client_annotator:
        await register_and_login(client_admin, "upd-admin@test.com")
        await register_and_login(client_annotator, "upd-annotator@test.com")

        resp = await client_admin.post("/api/v1/projects", json={"name": "Locked"})
        project_id = resp.json()["id"]

        # Add annotator
        await client_admin.post(f"/api/v1/projects/{project_id}/members", json={
            "email": "upd-annotator@test.com", "role": "annotator",
        })

        resp = await client_annotator.put(f"/api/v1/projects/{project_id}", json={
            "name": "Hacked",
        })
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_project_soft_deletes(client):
    await register_and_login(client, "deleter@test.com")
    resp = await client.post("/api/v1/projects", json={"name": "To Delete"})
    project_id = resp.json()["id"]

    resp = await client.delete(f"/api/v1/projects/{project_id}")
    assert resp.status_code == 204

    # No longer appears in list
    resp = await client.get("/api/v1/projects")
    assert resp.status_code == 200
    assert len(resp.json()) == 0

    # Direct get returns 403 (non-member check fails since project is deleted)
    resp = await client.get(f"/api/v1/projects/{project_id}")
    # The project is soft-deleted so get_project returns None -> 404
    # But the membership check happens first in the dependency - member still exists
    # so the dependency passes, then get_project returns None -> 404
    assert resp.status_code == 404


# --- LLM API key handling ---


@pytest.mark.asyncio
async def test_llm_api_key_stored_but_never_echoed(client):
    await register_and_login(client, "llmkey@test.com")
    resp = await client.post("/api/v1/projects", json={
        "name": "Gated vLLM",
        "llm_provider": "vllm",
        "llm_model": "google/gemma-4-31B-it",
        "llm_api_base": "http://gateway:8000",
        "llm_api_key": "sk-secret-value",
    })
    assert resp.status_code == 201
    data = resp.json()
    # The raw key must never appear in a response, only a boolean flag.
    assert "llm_api_key" not in data
    assert data["llm_api_key_set"] is True

    project_id = data["id"]
    get_resp = await client.get(f"/api/v1/projects/{project_id}")
    assert "llm_api_key" not in get_resp.json()
    assert get_resp.json()["llm_api_key_set"] is True


@pytest.mark.asyncio
async def test_llm_api_key_preserved_when_update_omits_it(client):
    await register_and_login(client, "llmkey-upd@test.com")
    resp = await client.post("/api/v1/projects", json={
        "name": "Keep Key",
        "llm_provider": "vllm",
        "llm_model": "m",
        "llm_api_key": "sk-keep-me",
    })
    project_id = resp.json()["id"]

    # Update other fields without sending the key.
    upd = await client.put(f"/api/v1/projects/{project_id}", json={"llm_model": "m2"})
    assert upd.status_code == 200
    assert upd.json()["llm_model"] == "m2"
    # Key is still set.
    assert upd.json()["llm_api_key_set"] is True

    # Explicitly clearing with empty string removes it.
    cleared = await client.put(f"/api/v1/projects/{project_id}", json={"llm_api_key": ""})
    assert cleared.status_code == 200
    assert cleared.json()["llm_api_key_set"] is False


# --- Membership ---


@pytest.mark.asyncio
async def test_add_member(client_factory):
    async with client_factory() as client_admin, client_factory() as client_new:
        await register_and_login(client_admin, "mem-admin@test.com")
        await register_and_login(client_new, "mem-new@test.com", "New Member")

        resp = await client_admin.post("/api/v1/projects", json={"name": "Team Project"})
        project_id = resp.json()["id"]

        resp = await client_admin.post(f"/api/v1/projects/{project_id}/members", json={
            "email": "mem-new@test.com", "role": "annotator",
        })
        assert resp.status_code == 201
        assert resp.json()["email"] == "mem-new@test.com"
        assert resp.json()["role"] == "annotator"

        # New member can access the project
        resp = await client_new.get(f"/api/v1/projects/{project_id}")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_list_members(client):
    await register_and_login(client, "list-mem@test.com")

    # Register second user (using same client, then re-login as first user)
    await client.post("/api/v1/auth/register", json={
        "email": "list-mem2@test.com", "name": "Member 2", "password": "pass1234",
    })
    # Re-login as first user
    await client.post("/api/v1/auth/login", json={
        "email": "list-mem@test.com", "password": "pass1234",
    })

    resp = await client.post("/api/v1/projects", json={"name": "Multi-member"})
    project_id = resp.json()["id"]

    await client.post(f"/api/v1/projects/{project_id}/members", json={
        "email": "list-mem2@test.com", "role": "viewer",
    })

    resp = await client.get(f"/api/v1/projects/{project_id}/members")
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 2
    emails = {m["email"] for m in members}
    assert "list-mem@test.com" in emails
    assert "list-mem2@test.com" in emails


@pytest.mark.asyncio
async def test_remove_member(client_factory):
    async with client_factory() as client_admin, client_factory() as client_member:
        await register_and_login(client_admin, "rm-admin@test.com")
        await register_and_login(client_member, "rm-member@test.com", "To Remove")

        resp = await client_admin.post("/api/v1/projects", json={"name": "Shrinking Team"})
        project_id = resp.json()["id"]

        # Add member
        await client_admin.post(f"/api/v1/projects/{project_id}/members", json={
            "email": "rm-member@test.com", "role": "annotator",
        })

        # Get the member's user_id
        me_resp = await client_member.get("/api/v1/auth/me")
        member_user_id = me_resp.json()["id"]

        # Remove member
        resp = await client_admin.delete(
            f"/api/v1/projects/{project_id}/members/{member_user_id}",
        )
        assert resp.status_code == 204

        # Removed user can no longer access
        resp = await client_member.get(f"/api/v1/projects/{project_id}")
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_non_member_cannot_access_project(client_factory):
    async with client_factory() as client_owner, client_factory() as client_outsider:
        await register_and_login(client_owner, "access-owner@test.com")
        await register_and_login(client_outsider, "access-outsider@test.com")

        resp = await client_owner.post("/api/v1/projects", json={"name": "Restricted"})
        project_id = resp.json()["id"]

        # Cannot get project
        resp = await client_outsider.get(f"/api/v1/projects/{project_id}")
        assert resp.status_code == 403

        # Cannot list members
        resp = await client_outsider.get(f"/api/v1/projects/{project_id}/members")
        assert resp.status_code == 403

        # Cannot add members
        resp = await client_outsider.post(f"/api/v1/projects/{project_id}/members", json={
            "email": "someone@test.com",
        })
        assert resp.status_code == 403

        # Cannot update
        resp = await client_outsider.put(f"/api/v1/projects/{project_id}", json={
            "name": "Hacked",
        })
        assert resp.status_code == 403

        # Cannot delete
        resp = await client_outsider.delete(f"/api/v1/projects/{project_id}")
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_project_requires_auth(client):
    resp = await client.post("/api/v1/projects", json={"name": "No Auth"})
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_add_member_nonexistent_email_returns_404(client):
    await register_and_login(client, "add-nonexist@test.com")
    resp = await client.post("/api/v1/projects", json={"name": "Test"})
    project_id = resp.json()["id"]

    resp = await client.post(f"/api/v1/projects/{project_id}/members", json={
        "email": "nobody@test.com",
    })
    assert resp.status_code == 404
