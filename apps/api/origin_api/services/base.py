"""Base service class with tenant isolation guardrails."""

from typing import Optional

from sqlalchemy.orm import Session


class BaseService:
    """Base service with tenant isolation enforcement."""

    def __init__(self, db: Session, tenant_id: Optional[int] = None):
        """Initialize service with tenant context."""
        self.db = db
        self.tenant_id = tenant_id

    def _enforce_tenant(self, tenant_id: Optional[int] = None) -> int:
        """Enforce tenant_id is set and return it."""
        tenant_id = tenant_id or self.tenant_id
        if not tenant_id:
            raise ValueError("tenant_id must be provided for tenant-isolated operations")
        return tenant_id

    def _ensure_tenant_filter(self, query, tenant_id: Optional[int] = None):
        """Ensure query has tenant_id filter."""
        tenant_id = self._enforce_tenant(tenant_id)
        # Check if query already has tenant_id filter
        # This is a guardrail - actual enforcement should be in model queries
        return query.filter(getattr(query.column_descriptions[0]["entity"], "tenant_id") == tenant_id)

