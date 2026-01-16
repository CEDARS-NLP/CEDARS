"""User repository interface."""

from abc import ABC, abstractmethod
from typing import Optional

from app.models.user import User


class UserRepositoryInterface(ABC):
    """Abstract interface for user data access."""

    @abstractmethod
    def get_by_username(self, username: str) -> Optional[User]:
        """Get a user by username."""
        pass

    @abstractmethod
    def get_all(self) -> list[User]:
        """Get all users."""
        pass

    @abstractmethod
    def add_user(self, username: str, password_hash: str, is_admin: bool = False) -> bool:
        """Add a new user. Returns True if successful."""
        pass

    @abstractmethod
    def check_password(self, username: str, password: str) -> bool:
        """Verify a user's password."""
        pass

    @abstractmethod
    def is_admin(self, username: str) -> bool:
        """Check if a user is an admin."""
        pass
