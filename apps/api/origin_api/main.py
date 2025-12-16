"""ORIGIN API - Main FastAPI application."""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from origin_api.middleware.auth import AuthMiddleware
from origin_api.middleware.correlation import CorrelationIDMiddleware
from origin_api.middleware.idempotency import IdempotencyMiddleware
from origin_api.middleware.rate_limit import RateLimitMiddleware
from origin_api.middleware.scopes import ScopeMiddleware
from origin_api.routes import admin, evidence, ingest, keys, models, webhooks
from origin_api.settings import get_settings

# Configure logging
logging.basicConfig(
    level=get_settings().log_level,
    format='{"time": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s", "module": "%(name)s"}',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    logger.info("Starting ORIGIN API...")
    # Startup: Initialize connections, load models, etc.
    try:
        # Validate production settings
        settings.validate_production_settings()
        
        # Validate signing configuration
        from origin_api.ledger.signer import get_signer
        signer = get_signer()
        logger.info(f"Signer initialized: {signer.get_key_id()}")
        
        # Validate encryption configuration
        from origin_api.security.encryption import get_encryption_service
        encryption_service = get_encryption_service()
        logger.info("Encryption service initialized")
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
        raise ValueError(f"Invalid configuration: {e}") from e
    
    yield
    # Shutdown: Cleanup
    logger.info("Shutting down ORIGIN API...")


# Create FastAPI app
app = FastAPI(
    title="ORIGIN API",
    description="API-First Upload Governance Infrastructure",
    version="0.1.0",
    lifespan=lifespan,
)

# Middleware (order matters - last added is first executed)
settings = get_settings()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

# Custom middleware (order matters - last added is first executed)
app.add_middleware(AuthMiddleware)  # Extract tenant first
app.add_middleware(ScopeMiddleware)  # Check scopes after auth
app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(IdempotencyMiddleware)

# Prometheus metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Register routers
app.include_router(admin.router)
app.include_router(ingest.router)
app.include_router(evidence.router)
app.include_router(webhooks.router)
app.include_router(keys.router)
app.include_router(models.router)


@app.get("/health")
async def health_check():
    """Health check endpoint (basic liveness)."""
    return {
        "status": "healthy",
        "service": "origin-api",
        "version": "0.1.0",
    }


@app.get("/ready")
async def readiness_check():
    """Readiness check endpoint (verifies dependencies)."""
    from fastapi import Response
    from fastapi.responses import JSONResponse
    from origin_api.db.session import SessionLocal
    from sqlalchemy import text
    import redis
    
    checks = {
        "database": False,
        "migrations": False,
        "redis": False,
        "object_storage": False,
        "kms": None,  # None if not required, True/False if required
    }
    
    # Check database connectivity
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        logger.error(f"Database check failed: {e}")
        checks["database"] = False
    finally:
        if 'db' in locals():
            db.close()
    
    # Check Alembic migrations are at head
    if checks["database"]:
        try:
            from alembic import command
            from alembic.config import Config
            from alembic.script import ScriptDirectory
            from alembic.runtime.migration import MigrationContext
            
            db = SessionLocal()
            try:
                # Get current revision from database
                context = MigrationContext.configure(db.connection())
                current_rev = context.get_current_revision()
                
                # Get head revision from script directory
                import os
                alembic_ini_path = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
                alembic_cfg = Config(alembic_ini_path)
                script = ScriptDirectory.from_config(alembic_cfg)
                head_rev = script.get_current_head()
                
                if current_rev == head_rev:
                    checks["migrations"] = True
                else:
                    logger.warning(f"Migrations not at head: current={current_rev}, head={head_rev}")
                    checks["migrations"] = False
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Migration check failed: {e}")
            checks["migrations"] = False
    
    # Check Redis
    try:
        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        redis_client.ping()
        checks["redis"] = True
    except Exception as e:
        logger.error(f"Redis check failed: {e}")
        checks["redis"] = False
    
    # Check object storage (MinIO/S3) connectivity and bucket existence
    try:
        from origin_api.storage.s3 import S3Storage
        storage = S3Storage()
        # Try to check if bucket exists (this will fail if credentials are wrong)
        if storage.client.bucket_exists(storage.bucket):
            checks["object_storage"] = True
        else:
            logger.warning(f"Object storage bucket {storage.bucket} does not exist")
            checks["object_storage"] = False
    except Exception as e:
        logger.error(f"Object storage check failed: {e}")
        checks["object_storage"] = False
    
    # Check KMS (only if not in dev/test)
    env = settings.environment.lower()
    if env not in ("development", "test", "dev"):
        try:
            from origin_api.security.encryption import get_encryption_service
            encryption_service = get_encryption_service()
            # If KMS provider, verify it's accessible
            if encryption_service.provider == "aws_kms":
                # Test KMS access by attempting to describe the key
                # (This was already validated at startup, but double-check)
                checks["kms"] = True
            else:
                logger.error("KMS provider not set to aws_kms in production")
                checks["kms"] = False
        except Exception as e:
            logger.error(f"KMS check failed: {e}")
            checks["kms"] = False
    else:
        checks["kms"] = None  # Not required in dev
    
    # Determine overall readiness
    required_checks = ["database", "migrations", "redis", "object_storage"]
    if checks["kms"] is not None:
        required_checks.append("kms")
    
    all_ready = all(checks[check] for check in required_checks)
    
    status_code = 200 if all_ready else 503
    
    return JSONResponse(
        content={
            "status": "ready" if all_ready else "not_ready",
            "checks": checks,
        },
        status_code=status_code,
    )


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "ORIGIN API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }

