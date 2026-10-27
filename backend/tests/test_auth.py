"""Tests for auth models and service."""

import jwt
import pytest

from app.auth.models import User, UserRole
from app.auth.service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.config import settings


def test_user_role_enum():
    assert UserRole.PLATFORM_ADMIN.value == "platform_admin"
    assert UserRole.USER.value == "user"


def test_user_model_creation():
    user = User(
        email="test@example.com",
        name="Test User",
        password_hash="hashed",
        role=UserRole.PLATFORM_ADMIN,
    )
    assert user.email == "test@example.com"
    assert user.name == "Test User"
    assert user.role == UserRole.PLATFORM_ADMIN


def test_user_model_defaults():
    user = User(
        email="default@example.com",
        name="Default User",
        password_hash="hashed",
    )
    assert user.role == UserRole.USER
    assert user.is_active is True
    assert user.id is not None
    assert user.created_at is not None


# --- Password Hashing Tests ---


def test_hash_password_returns_different_string():
    password = "secure-password-123"
    hashed = hash_password(password)
    assert hashed != password


def test_verify_password_correct():
    password = "secure-password-123"
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True


def test_verify_password_incorrect():
    hashed = hash_password("secure-password-123")
    assert verify_password("wrong-password", hashed) is False


def test_hash_password_unique_each_call():
    """Each call should produce a different hash (due to salting)."""
    password = "same-password"
    hash1 = hash_password(password)
    hash2 = hash_password(password)
    assert hash1 != hash2
    assert verify_password(password, hash1) is True
    assert verify_password(password, hash2) is True


# --- JWT Token Tests ---


def test_create_and_decode_access_token():
    token = create_access_token(user_id="user-123", role="user")
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == "user-123"
    assert payload["role"] == "user"
    assert payload["type"] == "access"
    assert "exp" in payload


def test_create_and_decode_refresh_token():
    token = create_refresh_token(user_id="user-123")
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == "user-123"
    assert payload["type"] == "refresh"
    assert "exp" in payload


def test_decode_invalid_token():
    payload = decode_token("invalid-token")
    assert payload is None


def test_decode_existing_python_jose_token(monkeypatch):
    """Accept an HS256 token issued by python-jose before the migration."""
    monkeypatch.setattr(settings, "secret_key", "legacy-token-test-key-with-at-least-32-bytes")
    token = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiJsZWdhY3ktdXNlciIsInJvbGUiOiJ1c2VyIiwidHlwZSI6ImFjY2VzcyIs"
        "ImV4cCI6NDEwMjQ0NDgwMH0.EI5p-mn3Y9GnwjWgAMCJkbMQ5nWg3WJE2hAsz2lQJ_U"
    )
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == "legacy-user"
    assert payload["type"] == "access"


def test_decode_expired_token_preserves_expiry_error():
    token = jwt.encode(
        {"sub": "user-123", "type": "access", "exp": 1},
        settings.secret_key,
        algorithm="HS256",
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(token)


@pytest.mark.parametrize("algorithm", ["HS384", "HS512", "none"])
def test_decode_rejects_unexpected_algorithm(algorithm):
    token = jwt.encode(
        {"sub": "user-123", "type": "access"},
        "" if algorithm == "none" else settings.secret_key,
        algorithm=algorithm,
    )
    assert decode_token(token) is None


def test_decode_rejects_wrong_signing_key():
    token = jwt.encode(
        {"sub": "user-123", "type": "access"},
        "a-different-signing-key-for-tests-only",
        algorithm="HS256",
    )
    assert decode_token(token) is None


def test_decode_tampered_token():
    """A token with a modified payload should fail verification."""
    token = create_access_token(user_id="user-123", role="user")
    # Tamper with the token by changing a character in the payload
    parts = token.split(".")
    parts[1] = parts[1][:5] + "X" + parts[1][6:]
    tampered = ".".join(parts)
    assert decode_token(tampered) is None
