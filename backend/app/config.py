"""Application configuration using Pydantic Settings."""

from pydantic import Field
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
    project_engine_cache_size: int = Field(default=20, ge=1)
    project_db_pool_size: int = Field(default=1, ge=1)
    project_db_max_overflow: int = Field(default=0, ge=0)
    aws_region: str | None = None
    secrets_manager_endpoint_url: str | None = None
    project_database_secret_prefix: str = "user-cedars/project-databases"
    project_provisioning_database_url: str | None = None
    project_provisioning_timeout_seconds: int = Field(default=120, ge=1)

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Auth
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    cookie_secure: bool = False

    # S3-compatible object storage
    s3_endpoint: str = "http://localhost:8333"
    s3_bucket: str = "cedars"
    s3_access_key: str = "rootuser"
    s3_secret_key: str = "rootpassword"
    s3_region: str = ""

    # PINES NLP service
    pines_api_url: str | None = None

    # LLM settings
    allow_cloud_llm: bool = True

    # Build identity: the git commit baked into the image (Dockerfile ARG GIT_SHA), "dev" when unset.
    git_sha: str = "dev"

    # CORS
    cors_origins: str = "http://localhost:5173"

    # NLP / spaCy settings
    # Set to a spaCy model name (e.g. "en_core_web_sm") to use a trained model.
    # Leave blank to use the default blank English model with sentencizer.
    spacy_model: str = ""


settings = Settings()
