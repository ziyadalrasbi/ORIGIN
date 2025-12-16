"""Worker settings - consolidated with API settings for consistency."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Worker settings - consistent with API settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: Optional[str] = None
    postgres_user: str = "origin"
    postgres_password: str = "origin_dev_password"
    postgres_db: str = "origin"
    postgres_port: int = 5432

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # MinIO / S3 - NO DEFAULTS (required in non-dev)
    minio_endpoint: str = "localhost:9000"
    minio_access_key: Optional[str] = None  # Required in non-dev, no defaults
    minio_secret_key: Optional[str] = None  # Required in non-dev, no defaults
    minio_bucket: str = "origin-evidence"
    minio_use_ssl: bool = False

    # Environment
    environment: str = "development"
    secret_key: str = "dev-secret-key-change-in-production"
    
    # Webhook encryption (for worker tasks that decrypt secrets)
    webhook_encryption_key_id: Optional[str] = None
    webhook_encryption_provider: str = "local"  # local, aws_kms
    local_encryption_salt: Optional[str] = None
    
    # AWS (for KMS if needed)
    aws_region: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None

    @property
    def database_url_computed(self) -> str:
        """Compute database URL if not explicitly set."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@localhost:{self.postgres_port}/{self.postgres_db}"
        )
    
    def validate_production_settings(self):
        """Validate settings for production environment."""
        env = self.environment.lower()
        if env not in ("development", "test", "dev"):
            # Production settings validation
            if not self.minio_access_key or not self.minio_secret_key:
                raise ValueError(
                    "MINIO_ACCESS_KEY and MINIO_SECRET_KEY are required in production. "
                    "Do not use default credentials."
                )
            if self.webhook_encryption_provider == "local":
                raise ValueError(
                    "WEBHOOK_ENCRYPTION_PROVIDER=local is not allowed in production. "
                    "Use WEBHOOK_ENCRYPTION_PROVIDER=aws_kms."
                )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

