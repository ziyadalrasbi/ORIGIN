"""Rate limiting middleware."""

import time
from typing import Optional

import redis
from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware

from origin_api.settings import get_settings

settings = get_settings()
redis_client = redis.from_url(settings.redis_url, decode_responses=True)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token bucket rate limiting per tenant."""

    async def dispatch(self, request: Request, call_next):
        """Apply rate limiting."""
        # Skip rate limiting for health checks and metrics
        if request.url.path in ["/health", "/ready", "/metrics", "/docs", "/openapi.json"]:
            return await call_next(request)

        # Get tenant from request state (set by auth middleware)
        tenant_id = getattr(request.state, "tenant_id", None)
        if not tenant_id:
            # If no tenant, use IP as fallback
            tenant_id = request.client.host if request.client else "unknown"

        # Rate limit key
        key = f"rate_limit:{tenant_id}"
        now = time.time()

        # Token bucket algorithm
        # Get current state
        pipe = redis_client.pipeline()
        pipe.get(key)
        pipe.get(f"{key}:last_refill")
        results = pipe.execute()

        tokens = float(results[0]) if results[0] else settings.rate_limit_requests_per_minute
        last_refill = float(results[1]) if results[1] else now

        # Refill tokens based on time passed
        time_passed = now - last_refill
        refill_amount = (time_passed / 60.0) * settings.rate_limit_requests_per_minute
        tokens = min(settings.rate_limit_requests_per_minute, tokens + refill_amount)

        # Check if request can be processed
        if tokens < 1:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please try again later.",
                headers={"Retry-After": "60"},
            )

        # Consume token
        tokens -= 1

        # Update state with TTL to prevent key accumulation
        ttl = settings.rate_limit_ttl_seconds
        pipe = redis_client.pipeline()
        pipe.set(key, tokens, ex=ttl)  # Set TTL on tokens key
        pipe.set(f"{key}:last_refill", now, ex=ttl)  # Set TTL on last_refill key
        pipe.execute()

        # Process request
        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(int(tokens))
        response.headers["X-RateLimit-Reset"] = str(int(now + 60))

        return response

