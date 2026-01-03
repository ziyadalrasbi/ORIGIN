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
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin123"
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
    
    # Provenance (for auditability)
    git_commit_sha: Optional[str] = None  # Set via GIT_COMMIT_SHA env var
    feature_schema_version: str = "v1.0"  # Feature schema version
    risk_model_version: Optional[str] = None  # Semantic version or timestamp
    anomaly_model_version: Optional[str] = None  # Semantic version or timestamp

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    # Rate Limiting
    rate_limit_requests_per_minute: int = 100
    rate_limit_burst: int = 20

    # Webhooks
    webhook_timeout_seconds: int = 10
    webhook_max_retries: int = 3

    # CORS
    cors_origins: list[str] = ["*"]
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = ["*"]
    cors_allow_headers: list[str] = ["*"]
    
    # Storage
    storage_mode: str = "object"  # "object" or "filesystem"
    evidence_pack_timeout_minutes: int = 5  # Timeout for async evidence pack generation

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


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

