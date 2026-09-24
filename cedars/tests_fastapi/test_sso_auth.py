"""SSO auth foundation tests."""

from werkzeug.security import generate_password_hash

from app.security import (create_access_token, decode_token, hash_password,
                          verify_password)


GOOD_PASSWORD = "Abcdef12!!"


def _register(client, username, password=GOOD_PASSWORD):
    return client.post("/api/v1/auth/register", json={
        "username": username,
        "password": password,
        "confirm_password": password,
    })


def test_password_verification_supports_bcrypt_and_legacy_werkzeug():
    bcrypt_hash = hash_password(GOOD_PASSWORD)
    legacy_hash = generate_password_hash(GOOD_PASSWORD)

    assert verify_password(GOOD_PASSWORD, bcrypt_hash)
    assert verify_password(GOOD_PASSWORD, legacy_hash)
    assert not verify_password("wrong", bcrypt_hash)
    assert not verify_password(GOOD_PASSWORD, None)


def test_python_jose_token_round_trip():
    token = create_access_token("SsoUser", False)

    payload = decode_token(token, "access")

    assert payload["sub"] == "SsoUser"
    assert payload["is_admin"] is False
    assert payload["type"] == "access"


def test_sso_config_endpoint(client, monkeypatch):
    from app.routers import auth

    monkeypatch.setattr(auth.settings, "SSO_ENABLED", True)
    monkeypatch.setattr(auth.settings, "SSO_PROVIDER_NAME", "MSK SSO")
    monkeypatch.setattr(auth.settings, "SSO_AUTHORIZATION_ENDPOINT", "https://sso.example.org/auth")
    monkeypatch.setattr(auth.settings, "SSO_CLIENT_ID", "cedars")
    monkeypatch.setattr(auth.settings, "SSO_REDIRECT_URI", "https://cedars.example.org/api/v1/auth/sso/callback")

    resp = client.get("/api/v1/auth/sso/config")

    assert resp.status_code == 200
    assert resp.json() == {
        "enabled": True,
        "provider_name": "MSK SSO",
        "login_url": "/api/v1/auth/sso/login",
    }


def test_sso_login_redirect_sets_state_and_nonce(client, monkeypatch):
    from app.routers import auth

    monkeypatch.setattr(auth.settings, "SSO_ENABLED", True)
    monkeypatch.setattr(auth.settings, "SSO_AUTHORIZATION_ENDPOINT", "https://sso.example.org/auth")
    monkeypatch.setattr(auth.settings, "SSO_CLIENT_ID", "cedars")
    monkeypatch.setattr(auth.settings, "SSO_REDIRECT_URI", "https://cedars.example.org/api/v1/auth/sso/callback")
    monkeypatch.setattr(auth.settings, "SSO_SCOPES", "openid email profile")

    resp = client.get("/api/v1/auth/sso/login", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"].startswith("https://sso.example.org/auth?")
    assert "response_type=code" in resp.headers["location"]
    assert "client_id=cedars" in resp.headers["location"]
    assert auth.SSO_STATE_COOKIE_NAME in resp.cookies
    assert auth.SSO_NONCE_COOKIE_NAME in resp.cookies


def test_sso_login_requires_minimum_config(client, monkeypatch):
    from app.routers import auth

    monkeypatch.setattr(auth.settings, "SSO_ENABLED", True)
    monkeypatch.setattr(auth.settings, "SSO_AUTHORIZATION_ENDPOINT", "")

    resp = client.get("/api/v1/auth/sso/login", follow_redirects=False)

    assert resp.status_code == 503


def test_local_registration_rejects_sso_domain(client, monkeypatch):
    from app.routers import auth

    monkeypatch.setattr(auth.settings, "SSO_ALLOWED_EMAIL_DOMAINS", ["mskcc.org"])

    resp = _register(client, "user@mskcc.org")

    assert resp.status_code == 400
    assert resp.json()["detail"] == auth.SSO_DOMAIN_MESSAGE


def test_local_login_rejects_sso_domain(client, monkeypatch):
    from app.routers import auth

    monkeypatch.setattr(auth.settings, "SSO_ALLOWED_EMAIL_DOMAINS", ["mskcc.org"])

    resp = client.post("/api/v1/auth/login", json={
        "username": "user@mskcc.org",
        "password": GOOD_PASSWORD,
    })

    assert resp.status_code == 401
    assert resp.json()["detail"] == auth.SSO_DOMAIN_MESSAGE


def test_non_sso_domain_local_registration_still_works(client, monkeypatch):
    from app.routers import auth

    monkeypatch.setattr(auth.settings, "SSO_ALLOWED_EMAIL_DOMAINS", ["mskcc.org"])

    resp = _register(client, "local@example.org")

    assert resp.status_code == 201, resp.text
    assert resp.json() == {"username": "local@example.org", "is_admin": False}