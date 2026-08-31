"""P1 smoke tests: authentication + multi-project management."""

GOOD_PASSWORD = "Abcdef12!!"


def _register(client, username, password=GOOD_PASSWORD, is_admin=False):
    return client.post("/api/v1/auth/register", json={
        "username": username,
        "password": password,
        "confirm_password": password,
    })


def test_health(client):
    assert client.get("/api/v1/health").json() == {"status": "ok"}


def test_user_registration_does_not_assign_global_admin(client):
    resp = _register(client, "AdminUser")
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"username": "AdminUser", "is_admin": False}


def test_password_policy_rejects_weak(client):
    resp = _register(client, "WeakUser", password="weak")
    assert resp.status_code == 400


def test_duplicate_username_rejected(client):
    _register(client, "AdminUser")
    resp = _register(client, "AdminUser")
    assert resp.status_code == 400


def test_login_me_and_logout(client):
    _register(client, "AdminUser")
    resp = client.post("/api/v1/auth/login",
                       json={"username": "AdminUser", "password": GOOD_PASSWORD})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message"] == "Login successful."
    assert body["user"] == {"username": "AdminUser", "is_admin": False}

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "AdminUser"

    assert client.post("/api/v1/auth/logout").status_code == 200
    # After logout the access cookie is cleared -> /me is unauthorized.
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_refresh_issues_new_access(client):
    _register(client, "AdminUser")
    client.post("/api/v1/auth/login",
                json={"username": "AdminUser", "password": GOOD_PASSWORD})
    # Drop the access cookie but keep the refresh cookie.
    client.cookies.delete("cedars_access")
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/auth/refresh").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


def test_project_lifecycle(client):
    _register(client, "AdminUser")
    client.post("/api/v1/auth/login",
                json={"username": "AdminUser", "password": GOOD_PASSWORD})

    # Create
    resp = client.post("/api/v1/projects",
                       json={"name": "Cohort A", "description": "first project"})
    assert resp.status_code == 201, resp.text
    project = resp.json()
    assert project["name"] == "Cohort A"
    assert project["role"] == "admin"
    assert project["owner"] == "AdminUser"
    pid = project["id"]

    # List
    listed = client.get("/api/v1/projects").json()
    assert [p["id"] for p in listed] == [pid]

    # Get
    got = client.get(f"/api/v1/projects/{pid}").json()
    assert got["id"] == pid and got["name"] == "Cohort A"

    # Update
    upd = client.put(f"/api/v1/projects/{pid}",
                     json={"name": "Cohort A2", "description": "renamed"})
    assert upd.status_code == 200, upd.text
    assert upd.json()["name"] == "Cohort A2"
    assert upd.json()["description"] == "renamed"

    # Unknown project -> 404
    assert client.get("/api/v1/projects/does-not-exist").status_code == 404


def test_project_membership_is_project_scoped(client):
    _register(client, "AdminUser")
    _register(client, "PlainUser")
    client.post("/api/v1/auth/login",
                json={"username": "AdminUser", "password": GOOD_PASSWORD})
    created = client.post("/api/v1/projects",
                          json={"name": "Cohort A"}).json()
    pid = created["id"]

    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login",
                json={"username": "PlainUser", "password": GOOD_PASSWORD})
    assert client.get("/api/v1/projects").json() == []
    assert client.get(f"/api/v1/projects/{pid}").status_code == 403

    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login",
                json={"username": "AdminUser", "password": GOOD_PASSWORD})
    added = client.post(f"/api/v1/projects/{pid}/members",
                        json={"username": "PlainUser", "role": "annotator"})
    assert added.status_code == 201, added.text
    assert added.json()["role"] == "annotator"

    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login",
                json={"username": "PlainUser", "password": GOOD_PASSWORD})
    listed = client.get("/api/v1/projects").json()
    assert [(p["id"], p["role"]) for p in listed] == [(pid, "annotator")]
    assert client.put(f"/api/v1/projects/{pid}",
                      json={"description": "blocked"}).status_code == 403

    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login",
                json={"username": "AdminUser", "password": GOOD_PASSWORD})
    promoted = client.patch(f"/api/v1/projects/{pid}/members/PlainUser",
                            json={"role": "admin"})
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["role"] == "admin"

    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login",
                json={"username": "PlainUser", "password": GOOD_PASSWORD})
    updated = client.put(f"/api/v1/projects/{pid}",
                         json={"description": "allowed"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["description"] == "allowed"


def test_any_registered_user_can_create_project(client):
    _register(client, "AdminUser")
    _register(client, "PlainUser")
    client.post("/api/v1/auth/login",
                json={"username": "PlainUser", "password": GOOD_PASSWORD})
    resp = client.post("/api/v1/projects", json={"name": "Cohort B"})
    assert resp.status_code == 201, resp.text
    project = resp.json()
    assert project["owner"] == "PlainUser"
    assert project["role"] == "admin"
