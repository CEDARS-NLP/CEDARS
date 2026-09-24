"""Settings for the FastAPI web layer.

Only web-layer configuration lives here (auth/JWT, cookies, CORS). Database,
Redis and S3 connection details are read from the environment directly by
:mod:`app.database` and :mod:`app.queues`, mirroring the original application.
"""
import os
from datetime import timedelta


def _split_csv(value, default):
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings:  # pylint: disable=too-few-public-methods
    """Runtime settings sourced from environment variables."""

    # --- auth / JWT ---
    SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
    JWT_ALGORITHM = "HS256"
    ACCESS_TOKEN_TTL = timedelta(minutes=int(os.getenv("ACCESS_TOKEN_MINUTES", "30")))
    REFRESH_TOKEN_TTL = timedelta(days=int(os.getenv("REFRESH_TOKEN_DAYS", "7")))

    # --- cookies ---
    COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
    COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")
    COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN") or None
    ACCESS_COOKIE_NAME = "cedars_access"
    REFRESH_COOKIE_NAME = "cedars_refresh"

    # --- SSO / OIDC ---
    SSO_ENABLED = os.getenv("SSO_ENABLED", "false").lower() == "true"
    SSO_PROVIDER_NAME = os.getenv("SSO_PROVIDER_NAME", "MSK SSO")
    SSO_ISSUER = os.getenv("SSO_ISSUER", "")
    SSO_AUTHORIZATION_ENDPOINT = os.getenv("SSO_AUTHORIZATION_ENDPOINT", "")
    SSO_TOKEN_ENDPOINT = os.getenv("SSO_TOKEN_ENDPOINT", "")
    SSO_USERINFO_ENDPOINT = os.getenv("SSO_USERINFO_ENDPOINT", "")
    SSO_JWKS_URI = os.getenv("SSO_JWKS_URI", "")
    SSO_CLIENT_ID = os.getenv("SSO_CLIENT_ID", "")
    SSO_CLIENT_SECRET = os.getenv("SSO_CLIENT_SECRET", "")
    SSO_REDIRECT_URI = os.getenv("SSO_REDIRECT_URI", "")
    SSO_SCOPES = os.getenv("SSO_SCOPES", "openid email profile")
    SSO_ALLOWED_EMAIL_DOMAINS = [
        domain.lower()
        for domain in _split_csv(os.getenv("SSO_ALLOWED_EMAIL_DOMAINS"), [])
    ]
    SSO_REQUIRED_CLAIMS = _split_csv(os.getenv("SSO_REQUIRED_CLAIMS"),
                                     ["sub", "email"])
    SSO_GROUPS_CLAIM = os.getenv("SSO_GROUPS_CLAIM", "groups")
    SSO_LOGOUT_ENDPOINT = os.getenv("SSO_LOGOUT_ENDPOINT", "")
    SSO_POST_LOGOUT_REDIRECT_URI = os.getenv("SSO_POST_LOGOUT_REDIRECT_URI", "")

    # --- CORS (dev: allow the Vite dev server by default) ---
    CORS_ORIGINS = _split_csv(os.getenv("CORS_ORIGINS"),
                              ["http://localhost:5173", "http://localhost"])

    # --- misc ---
    ENV = os.getenv("ENV", "local")

    # Password policy (mirrors the original passvalidate configuration)
    PW_MIN_LENGTH = 8
    PW_MIN_UPPERCASE = 1
    PW_MIN_LOWERCASE = 2
    PW_MIN_DIGITS = 2
    PW_MIN_SPECIAL = 1
    PW_SPECIAL_CHARS = "!@#$%^&*[]{}()~`,./<>?;:'\"-_+"


settings = Settings()
