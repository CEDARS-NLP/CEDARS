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
    cookie_secure: bool = False

    # S3 / MinIO object storage
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "cedars"
    s3_access_key: str = "rootuser"
    s3_secret_key: str = "rootpassword"
    s3_region: str = ""

    # PINES NLP service
    pines_api_url: str | None = None

    # LLM settings
    allow_cloud_llm: bool = True

    # NLP / spaCy settings
    # Set to a spaCy model name (e.g. "en_core_web_sm") to use a trained model.
    # Leave blank to use the default blank English model with sentencizer.
    spacy_model: str = ""


settings = Settings()
