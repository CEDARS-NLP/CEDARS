"""Auth service: password hashing, JWT token management, and user operations."""

from datetime import datetime, timedelta, timezone

from jose import ExpiredSignatureError, JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.models import User
from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


# --- Password Hashing ---


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


# --- JWT Tokens ---


def create_access_token(user_id: str, role: str) -> str:
    """Create a short-lived access token with user ID and role."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": user_id, "role": role, "type": "access", "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """Create a long-lived refresh token with user ID."""
    expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    payload = {"sub": user_id, "type": "refresh", "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    """Decode and validate a JWT token.

    Returns the payload dict if the token is valid.
    Returns None if the token is malformed or has an invalid signature.
    Raises ExpiredSignatureError if the token is well-formed but expired,
    allowing callers to distinguish expiry from other validation failures.
    """
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except ExpiredSignatureError:
        raise  # Propagate so callers can surface a specific "token expired" error
    except JWTError:
        return None


# --- User Operations ---


async def register_user(
    session: AsyncSession, email: str, name: str, password: str
) -> User:
    """Register a new user. Raises ValueError if email already taken."""
    existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        raise ValueError("Email already registered")
    user = User(email=email, name=name, password_hash=hash_password(password))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate_user(
    session: AsyncSession, email: str, password: str
) -> User:
    """Authenticate user by email/password. Raises ValueError on failure."""
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        raise ValueError("Invalid email or password")
    return user


async def refresh_access_token(
    session: AsyncSession, refresh_token: str
) -> tuple[User, str, str]:
    """Validate refresh token, return (user, new_access_token, new_refresh_token).

    Raises ValueError on invalid token, expired token, or inactive user.
    """
    try:
        payload = decode_token(refresh_token)
    except ExpiredSignatureError:
        raise ValueError("Refresh token has expired")
    if not payload or payload.get("type") != "refresh":
        raise ValueError("Invalid refresh token")
    user = await session.get(User, payload["sub"])
    if not user or not user.is_active:
        raise ValueError("User not found or inactive")
    return user, create_access_token(user.id, user.role.value), create_refresh_token(user.id)
