"""Correlation ID middleware."""

import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Add correlation ID to requests and responses."""

    async def dispatch(self, request: Request, call_next):
        """Process request with correlation ID."""
        # Get correlation ID from header or generate new one
        correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())

        # Add to request state
        request.state.correlation_id = correlation_id

        # Process request
        response: Response = await call_next(request)

        # Add correlation ID to response header
        response.headers["x-correlation-id"] = correlation_id

        return response

