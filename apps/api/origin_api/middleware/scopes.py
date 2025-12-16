"""API key scope enforcement middleware."""

import logging
from typing import Optional

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from origin_api.db.session import SessionLocal
from origin_api.models import APIKey

logger = logging.getLogger(__name__)

# Map of path patterns to required scopes
SCOPE_MAP = {
    "/v1/ingest": ["ingest"],
    "/v1/evidence-packs": ["evidence"],
    "/v1/evidence-packs/": ["evidence"],  # For paths starting with this
    "/v1/certificates/": ["read"],
    "/v1/keys/": ["read"],
    "/v1/webhooks": ["read"],  # Webhook management requires read
}


def get_required_scope(path: str) -> Optional[list[str]]:
    """Get required scope for a path."""
    # Exact match
    if path in SCOPE_MAP:
        return SCOPE_MAP[path]
    
    # Prefix match
    for pattern, scopes in SCOPE_MAP.items():
        if path.startswith(pattern):
            return scopes
    
    return None


class ScopeMiddleware(BaseHTTPMiddleware):
    """Enforce API key scopes per endpoint."""

    async def dispatch(self, request: Request, call_next):
        """Check API key scopes before processing request."""
        # Skip scope check for public endpoints
        if request.url.path in ["/health", "/ready", "/metrics", "/docs", "/openapi.json", "/"]:
            return await call_next(request)

        # Skip scope check for admin endpoints
        if request.url.path.startswith("/admin"):
            return await call_next(request)

        # Get required scope for this path
        required_scopes = get_required_scope(request.url.path)
        if not required_scopes:
            # No scope requirement for this path
            return await call_next(request)

        # Get API key from header
        api_key = request.headers.get("x-api-key")
        if not api_key:
            return await call_next(request)  # Auth middleware will handle this

        # Get API key object to check scopes
        db = SessionLocal()
        try:
            from origin_api.auth.api_key import compute_key_prefix, compute_key_digest
            import hmac

            prefix = compute_key_prefix(api_key)
            digest = compute_key_digest(api_key)

            api_key_obj = (
                db.query(APIKey)
                .filter(
                    APIKey.prefix == prefix,
                    APIKey.is_active == True,  # noqa: E712
                    APIKey.revoked_at.is_(None),
                )
                .first()
            )

            if api_key_obj and api_key_obj.digest and hmac.compare_digest(api_key_obj.digest, digest):
                # Parse scopes from JSON string
                import json
                scopes = json.loads(api_key_obj.scopes) if api_key_obj.scopes else []

                # Check if API key has required scope
                has_scope = any(scope in scopes for scope in required_scopes)
                if not has_scope:
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={
                            "detail": f"Insufficient permissions. Required scopes: {required_scopes}, "
                            f"API key has: {scopes}",
                        },
                    )

        finally:
            db.close()

        return await call_next(request)

