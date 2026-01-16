"""SQLite user repository implementation."""

from datetime import datetime
from typing import Optional

from werkzeug.security import check_password_hash

from app.models.user import User
from app.repositories.interfaces.user_repository import UserRepositoryInterface
from .database import session_scope
from .tables import UserTable


class SQLiteUserRepository(UserRepositoryInterface):
    """SQLite implementation of user repository."""

    def _to_model(self, row: UserTable) -> User:
        """Convert SQLAlchemy row to User model."""
        if row is None:
            return None
        return User(
            id=str(row.id),
            user=row.user,
            password=row.password,
            is_admin=row.is_admin,
            date_created=row.date_created,
        )

    def get_by_username(self, username: str) -> Optional[User]:
        with session_scope() as session:
            row = session.query(UserTable).filter_by(user=username).first()
            return self._to_model(row) if row else None

    def get_all(self) -> list[User]:
        with session_scope() as session:
            rows = session.query(UserTable).all()
            return [self._to_model(row) for row in rows]

    def add_user(self, username: str, password_hash: str, is_admin: bool = False) -> bool:
        with session_scope() as session:
            user = UserTable(
                user=username,
                password=password_hash,
                is_admin=is_admin,
                date_created=datetime.now(),
            )
            session.add(user)
            return True

    def check_password(self, username: str, password: str) -> bool:
        with session_scope() as session:
            row = session.query(UserTable).filter_by(user=username).first()
            if row is None:
                return False
            return check_password_hash(row.password, password)

    def is_admin(self, username: str) -> bool:
        with session_scope() as session:
            row = session.query(UserTable).filter_by(user=username).first()
            return row.is_admin if row else False
