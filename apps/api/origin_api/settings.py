"""Application settings and configuration."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

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
    redis_port: int = 6379

    # MinIO / S3
    minio_endpoint: str = "localhost:9000"
    minio_access_key: Optional[str] = None  # Required in non-dev
    minio_secret_key: Optional[str] = None  # Required in non-dev
    minio_bucket: str = "origin-evidence"
    minio_use_ssl: bool = False

    # API
    api_port: int = 8000
    secret_key: str = "dev-secret-key-change-in-production"
    environment: str = "development"
    api_host: str = "0.0.0.0"

    # Security
    jwt_secret_key: str = "dev-jwt-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24

    # ML
    mlflow_tracking_uri: str = "file:./ml/mlruns"
    ml_model_registry_path: str = "./ml/models"

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    # Rate Limiting
    rate_limit_requests_per_minute: int = 100
    rate_limit_burst: int = 20
    rate_limit_ttl_seconds: int = 600  # TTL for rate limit keys in Redis

    # Webhooks
    webhook_timeout_seconds: int = 10
    webhook_max_retries: int = 3

    # Legacy API key fallback (deprecated)
    legacy_apikey_fallback: bool = False

    # Signing key
    signing_key_path: str = "./secrets/origin_signing_key.pem"
    signing_key_id: Optional[str] = None  # For KMS
    signing_key_provider: str = "local"  # local, aws_kms, etc.
    
    # AWS (for KMS)
    aws_region: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    
    # Webhook encryption
    webhook_encryption_key_id: Optional[str] = None  # KMS key ID for webhook secret encryption
    webhook_encryption_provider: str = "local"  # local, aws_kms

    # Object storage
    minio_bucket: str = "origin-evidence"
    evidence_signed_url_ttl: int = 3600  # 1 hour

    # CORS
    cors_origins: list[str] = ["*"]
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = ["*"]
    cors_allow_headers: list[str] = ["*"]

    @property
    def database_url_computed(self) -> str:
        """Compute database URL if not explicitly set."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@localhost:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment.lower() == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.environment.lower() == "development"
    
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
            if self.signing_key_provider == "local":
                raise ValueError(
                    "SIGNING_KEY_PROVIDER=local is not allowed in production. "
                    "Use SIGNING_KEY_PROVIDER=aws_kms."
                )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

