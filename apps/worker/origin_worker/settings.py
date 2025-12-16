"""Worker settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Worker settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str
    postgres_user: str = "origin"
    postgres_password: str = "origin_dev_password"
    postgres_db: str = "origin"
    postgres_port: int = 5432

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # MinIO / S3
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin123"
    minio_bucket: str = "origin-evidence"
    minio_use_ssl: bool = False

    # Environment
    environment: str = "development"
    secret_key: str = "dev-secret-key-change-in-production"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

