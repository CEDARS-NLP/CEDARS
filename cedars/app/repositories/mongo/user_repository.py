"""MongoDB user repository implementation."""

from datetime import datetime
from typing import Optional

from werkzeug.security import check_password_hash

from app.database import mongo
from app.models.user import User
from app.repositories.interfaces.user_repository import UserRepositoryInterface


class MongoUserRepository(UserRepositoryInterface):
    """MongoDB implementation of user repository."""

    @property
    def collection(self):
        return mongo.db["USERS"]

    def _to_model(self, doc: dict) -> User:
        """Convert MongoDB document to User model."""
        if doc is None:
            return None
        doc["id"] = str(doc.pop("_id", None))
        return User(**doc)

    def get_by_username(self, username: str) -> Optional[User]:
        doc = self.collection.find_one({"user": username})
        return self._to_model(doc) if doc else None

    def get_all(self) -> list[User]:
        cursor = self.collection.find({})
        return [self._to_model(doc) for doc in cursor]

    def add_user(self, username: str, password_hash: str, is_admin: bool = False) -> bool:
        info = {
            "user": username,
            "password": password_hash,
            "is_admin": is_admin,
            "date_created": datetime.now(),
        }
        result = self.collection.insert_one(info)
        return result.inserted_id is not None

    def check_password(self, username: str, password: str) -> bool:
        user = self.collection.find_one({"user": username})
        if user is None:
            return False
        return check_password_hash(user["password"], password)

    def is_admin(self, username: str) -> bool:
        user = self.collection.find_one({"user": username})
        return user.get("is_admin", False) if user else False
