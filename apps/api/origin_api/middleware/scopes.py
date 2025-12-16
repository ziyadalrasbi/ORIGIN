"""API key scope enforcement middleware."""

import logging
from typing import Optional

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from origin_api.db.session import SessionLocal
from origin_api.models import APIKey

logger = logging.getLogger(__name__)

# Map of path patterns to required scopes (method-specific)
# Format: (path_pattern, method) -> required_scopes
SCOPE_MAP = {
    # Ingest
    ("/v1/ingest", "POST"): ["ingest:write"],
    # Evidence packs
    ("/v1/evidence-packs", "POST"): ["evidence:write"],
    ("/v1/evidence-packs", "GET"): ["evidence:read"],
    # Certificates and keys (all GET methods)
    ("/v1/certificates", "GET"): ["certificates:read"],
    ("/v1/keys", "GET"): ["certificates:read"],
    # Webhooks
    ("/v1/webhooks", "POST"): ["webhooks:write"],
    ("/v1/webhooks", "GET"): ["webhooks:read"],
    ("/v1/webhooks", "PUT"): ["webhooks:write"],
    ("/v1/webhooks", "DELETE"): ["webhooks:write"],
    ("/v1/webhooks", "PATCH"): ["webhooks:write"],
    # Admin endpoints (all methods require admin)
    ("/admin", "GET"): ["admin"],
    ("/admin", "POST"): ["admin"],
    ("/admin", "PUT"): ["admin"],
    ("/admin", "DELETE"): ["admin"],
    ("/admin", "PATCH"): ["admin"],
}


def get_required_scope(path: str, method: str) -> Optional[list[str]]:
    """Get required scope for a path and HTTP method."""
    # Normalize path (remove trailing slashes for matching)
    normalized_path = path.rstrip("/")
    
    # Try exact match first
    key = (normalized_path, method)
    if key in SCOPE_MAP:
        return SCOPE_MAP[key]
    
    # Try prefix match for paths starting with pattern
    # Sort by pattern length (longest first) for more specific matches
    sorted_patterns = sorted(SCOPE_MAP.items(), key=lambda x: len(x[0][0]), reverse=True)
    for (pattern, pattern_method), scopes in sorted_patterns:
        if normalized_path.startswith(pattern.rstrip("/")) and pattern_method == method:
            return scopes
    
    return None


class ScopeMiddleware(BaseHTTPMiddleware):
    """Enforce API key scopes per endpoint."""

    async def dispatch(self, request: Request, call_next):
        """Check API key scopes before processing request."""
        # Skip scope check for public endpoints
        if request.url.path in ["/health", "/ready", "/metrics", "/docs", "/openapi.json", "/"]:
            return await call_next(request)

        # Get required scope for this path and method
        method = request.method
        required_scopes = get_required_scope(request.url.path, method)
        
        # If no scope requirement, allow (but admin endpoints must have admin scope)
        if not required_scopes:
            # Admin endpoints always require admin scope
            if request.url.path.startswith("/admin"):
                required_scopes = ["admin"]
            else:
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

