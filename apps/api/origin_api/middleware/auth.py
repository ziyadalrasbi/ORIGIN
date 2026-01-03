"""Authentication middleware to extract tenant from API key."""

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from origin_api.auth.api_key import get_tenant_by_api_key
from origin_api.db.session import SessionLocal


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

        # Get tenant and API key object from API key
        db = SessionLocal()
        try:
            result = get_tenant_by_api_key(db, api_key)
            if not result:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Invalid or revoked API key."},
                )
            
            tenant, api_key_obj = result

            if tenant.status != "active":
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": f"Tenant status is {tenant.status}."},
                )

            # Set tenant in request state
            request.state.tenant = tenant
            request.state.tenant_id = tenant.id
            
            # Store API key object for scope extraction (no DB scan needed later)
            if api_key_obj:
                request.state.api_key_obj = api_key_obj

        finally:
            db.close()

        # Process request
        return await call_next(request)

