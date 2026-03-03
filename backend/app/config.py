"""Application configuration using Pydantic Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """CEDARS v2 backend configuration.

    All settings can be overridden via environment variables prefixed with CEDARS_
    or via a .env file in the project root.
    """

    model_config = SettingsConfigDict(
        env_prefix="CEDARS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+asyncpg://cedars:cedars@localhost:5432/cedars"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Auth
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # S3 / MinIO object storage
    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = ""

    # PINES NLP service
    pines_api_url: str | None = None

    # LLM settings
    allow_cloud_llm: bool = True


settings = Settings()
