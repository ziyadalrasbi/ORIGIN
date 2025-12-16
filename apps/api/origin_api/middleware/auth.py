"""Authentication middleware to extract tenant from API key."""

import ipaddress
import json
import logging
from typing import Optional

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from origin_api.auth.api_key import get_tenant_by_api_key
from origin_api.db.session import SessionLocal

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """Extract and validate tenant from API key."""

    async def dispatch(self, request: Request, call_next):
        """Process request with tenant extraction."""
        # Skip auth for health checks, docs, and metrics
        if request.url.path in ["/health", "/ready", "/metrics", "/docs", "/openapi.json", "/"]:
            return await call_next(request)

        # Skip auth for admin endpoints (they'll have their own auth)
        if request.url.path.startswith("/admin"):
            return await call_next(request)

        # Get API key from header
        api_key = request.headers.get("x-api-key")
        if not api_key:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing API key. Provide x-api-key header."},
            )

        # Get tenant from API key
        db = SessionLocal()
        try:
            tenant = get_tenant_by_api_key(db, api_key)
            if not tenant:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Invalid or revoked API key."},
                )

            if tenant.status != "active":
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": f"Tenant status is {tenant.status}."},
                )

            # Check IP allowlist if configured
            if tenant.ip_allowlist:
                client_ip = request.client.host if request.client else None
                if client_ip and not self._check_ip_allowlist(client_ip, tenant.ip_allowlist):
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={"detail": "IP address not allowed"},
                    )

            # Set tenant in request state
            request.state.tenant = tenant
            request.state.tenant_id = tenant.id

            # Structured logging
            correlation_id = getattr(request.state, "correlation_id", None)
            logger.info(
                "Authenticated request",
                extra={
                    "tenant_id": tenant.id,
                    "correlation_id": correlation_id,
                    "path": request.url.path,
                },
            )

        finally:
            db.close()

    def _check_ip_allowlist(self, client_ip: str, allowlist_json: str) -> bool:
        """Check if client IP is in allowlist."""
        try:
            allowlist = json.loads(allowlist_json) if isinstance(allowlist_json, str) else allowlist_json
            client_ip_obj = ipaddress.ip_address(client_ip)
            
            for allowed in allowlist:
                try:
                    network = ipaddress.ip_network(allowed, strict=False)
                    if client_ip_obj in network:
                        return True
                except ValueError:
                    # Try exact match
                    if client_ip == allowed:
                        return True
            return False
        except Exception as e:
            logger.warning(f"Error checking IP allowlist: {e}")
            return True  # Fail open for misconfiguration

        # Process request
        return await call_next(request)

