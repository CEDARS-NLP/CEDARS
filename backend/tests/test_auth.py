"""Tests for auth models."""

from app.auth.models import User, UserRole


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
