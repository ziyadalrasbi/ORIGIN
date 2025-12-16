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
from origin_api.routes import admin, evidence, ingest, keys, webhooks
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


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "origin-api",
        "version": "0.1.0",
    }


@app.get("/ready")
async def readiness_check():
    """Readiness check endpoint."""
    # TODO: Check database, Redis, MinIO connections
    return {
        "status": "ready",
        "service": "origin-api",
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "ORIGIN API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }

