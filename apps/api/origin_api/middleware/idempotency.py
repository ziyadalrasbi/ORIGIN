"""Idempotency middleware."""

import hashlib
import json
from typing import Optional

import redis
from fastapi import HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

from origin_api.settings import get_settings

settings = get_settings()
redis_client = redis.from_url(settings.redis_url, decode_responses=False)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Idempotency key handling for POST/PUT requests."""

    async def dispatch(self, request: Request, call_next):
        """Handle idempotency."""
        # Only apply to POST/PUT/PATCH
        if request.method not in ["POST", "PUT", "PATCH"]:
            return await call_next(request)

        # Get idempotency key from header
        idempotency_key = request.headers.get("idempotency-key")
        if not idempotency_key:
            return await call_next(request)

        # Create cache key
        tenant_id = getattr(request.state, "tenant_id", "unknown")
        cache_key = f"idempotency:{tenant_id}:{idempotency_key}"

        # Check if we've seen this request before
        cached_response = redis_client.get(cache_key)
        if cached_response:
            # Return cached response
            import pickle
            response_data = pickle.loads(cached_response)
            response = Response(
                content=response_data["body"],
                status_code=response_data["status_code"],
                headers=dict(response_data["headers"]),
            )
            response.headers["X-Idempotency-Key"] = idempotency_key
            response.headers["X-Idempotency-Replayed"] = "true"
            return response

        # Process request
        response = await call_next(request)

        # Cache successful responses (2xx)
        # Note: For simplicity, we only cache responses with status 200-299
        # Streaming responses are not cached
        if 200 <= response.status_code < 300 and hasattr(response, "body"):
            import pickle
            try:
                body = response.body
                if isinstance(body, bytes):
                    response_data = {
                        "body": body,
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                    }
                    # Cache for 24 hours
                    redis_client.setex(cache_key, 86400, pickle.dumps(response_data))
            except Exception:
                # If we can't cache, continue without caching
                pass

        # Add idempotency headers
        if not hasattr(response, "headers"):
            response = Response(
                content=getattr(response, "body", b""),
                status_code=response.status_code,
                headers=dict(getattr(response, "headers", {})),
            )
        response.headers["X-Idempotency-Key"] = idempotency_key
        return response

