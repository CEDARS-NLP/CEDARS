"""Tests for auth models and service."""

from app.auth.models import User, UserRole
from app.auth.service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


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


def test_decode_tampered_token():
    """A token with a modified payload should fail verification."""
    token = create_access_token(user_id="user-123", role="user")
    # Tamper with the token by changing a character in the payload
    parts = token.split(".")
    parts[1] = parts[1][:5] + "X" + parts[1][6:]
    tampered = ".".join(parts)
    assert decode_token(tampered) is None
