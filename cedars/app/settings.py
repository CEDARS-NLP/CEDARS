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
