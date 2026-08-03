"""Authentication routes: register / login / logout / refresh / me.

Ports the working parts of the original Flask ``auth`` blueprint (username +
password, password policy, first-user-is-admin) to FastAPI with JWT cookies.
The deprecated OIDC and Superbio-token flows are intentionally omitted.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from passvalidate import PasswordPolicy
from werkzeug.security import check_password_hash, generate_password_hash

from .. import db
from ..schemas import (LoginRequest, LoginResponse, MessageResponse,
                       RegisterRequest, UserOut)
from ..security import (CurrentUser, clear_auth_cookies, decode_token,
                        get_current_user, set_auth_cookies)
from ..settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])

RESERVED_USERNAMES = {"cedars", "pines"}


def _password_policy() -> PasswordPolicy:
    return PasswordPolicy(
        min_length=settings.PW_MIN_LENGTH,
        min_uppercase=settings.PW_MIN_UPPERCASE,
        min_lowercase=settings.PW_MIN_LOWERCASE,
        min_digits=settings.PW_MIN_DIGITS,
        min_special=settings.PW_MIN_SPECIAL,
        special_chars=settings.PW_SPECIAL_CHARS,
        allow_spaces=False,
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest):
    """Register a new user (first registered user always becomes an admin)."""
    username = (payload.username or "").strip()
    password = payload.password or ""
    is_admin = payload.is_admin

    password_ok, password_issues = _password_policy().check_password(password)
    existing_user = db.get_user(username)

    if password != payload.confirm_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Passwords do not match.")
    if not username or not password.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Username and password are required.")
    if existing_user or username.lower() in RESERVED_USERNAMES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Username already exists or reserved. Please choose a different one.")
    if password_ok is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "\n".join(password_issues))

    # Preserve the original behavior: the first registered user is an admin.
    if len(db.get_project_users()) == 0:
        is_admin = True

    db.add_user(username=username,
                password=generate_password_hash(password),
                is_admin=is_admin)
    return UserOut(username=username, is_admin=is_admin)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, response: Response):
    """Authenticate a user and set the access + refresh cookies."""
    username = (payload.username or "").strip()
    password = payload.password or ""
    if not username or not password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Username and password are required.")

    user = db.get_user(username)
    if user and check_password_hash(user["password"], password):
        is_admin = bool(user.get("is_admin"))
        set_auth_cookies(response, username, is_admin)
        return LoginResponse(message="Login successful.",
                             user=UserOut(username=username, is_admin=is_admin))

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials.")


@router.post("/logout", response_model=MessageResponse)
def logout(response: Response):
    """Clear the auth cookies."""
    clear_auth_cookies(response)
    return MessageResponse(message="Logout successful.")


@router.post("/refresh", response_model=MessageResponse)
def refresh(request: Request, response: Response):
    """Issue fresh cookies from a valid refresh cookie."""
    token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    payload = decode_token(token, "refresh")
    user = db.get_user(payload["sub"])
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer exists")
    set_auth_cookies(response, user["user"], bool(user.get("is_admin")))
    return MessageResponse(message="Token refreshed.")


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return UserOut(username=user.username, is_admin=user.is_admin)
