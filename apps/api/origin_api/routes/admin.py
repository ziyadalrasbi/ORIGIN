"""Admin routes for tenant and policy management."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from origin_api.auth.api_key import compute_key_digest, compute_key_prefix, hash_api_key_bcrypt
from origin_api.db.session import get_db
from origin_api.models import APIKey, PolicyProfile, Tenant

router = APIRouter(prefix="/admin", tags=["admin"])


class TenantCreate(BaseModel):
    """Tenant creation request."""

    label: str
    api_key: str


class TenantResponse(BaseModel):
    """Tenant response."""

    id: int
    label: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class APIKeyRotateRequest(BaseModel):
    """API key rotation request."""

    new_api_key: str
    label: Optional[str] = None


@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    tenant_data: TenantCreate,
    db: Session = Depends(get_db),
):
    """Create a new tenant."""
    # Check if tenant already exists
    existing = db.query(Tenant).filter(Tenant.label == tenant_data.label).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tenant with label '{tenant_data.label}' already exists",
        )

    # Create tenant
    tenant = Tenant(
        label=tenant_data.label,
        api_key_hash=None,  # Legacy, deprecated
        status="active",
    )
    db.add(tenant)
    db.flush()

    # Create API key with new scalable format
    api_key = APIKey(
        tenant_id=tenant.id,
        prefix=compute_key_prefix(tenant_data.api_key),
        digest=compute_key_digest(tenant_data.api_key),
        hash=None,  # Legacy, deprecated
        label="Initial API Key",
        scopes='["ingest", "evidence", "read"]',
        is_active=True,
    )
    db.add(api_key)

    # Create default policy profile
    policy_profile = PolicyProfile(
        tenant_id=tenant.id,
        name="default",
        version="ORIGIN-CORE-v1.0",
        thresholds_json={
            "risk_threshold_review": 30,
            "risk_threshold_quarantine": 70,
            "risk_threshold_reject": 90,
            "assurance_threshold_allow": 80,
        },
        weights_json={},
        is_active=True,
    )
    db.add(policy_profile)
    tenant.policy_profile_id = policy_profile.id

    db.commit()
    db.refresh(tenant)

    return tenant


@router.post("/tenants/{tenant_id}/rotate-api-key", status_code=status.HTTP_200_OK)
async def rotate_api_key(
    tenant_id: int,
    request: APIKeyRotateRequest,
    db: Session = Depends(get_db),
):
    """Rotate API key for a tenant."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} not found",
        )

    # Revoke old API keys
    db.query(APIKey).filter(
        APIKey.tenant_id == tenant_id,
        APIKey.is_active == True,  # noqa: E712
    ).update({"is_active": False, "revoked_at": datetime.utcnow()})

    # Create new API key with scalable format
    new_api_key = APIKey(
        tenant_id=tenant.id,
        prefix=compute_key_prefix(request.new_api_key),
        digest=compute_key_digest(request.new_api_key),
        hash=None,  # Legacy, deprecated
        label=request.label or "Rotated API Key",
        scopes='["ingest", "evidence", "read"]',
        is_active=True,
    )
    db.add(new_api_key)

    # Update tenant's rotated_at timestamp
    tenant.rotated_at = datetime.utcnow()

    db.commit()

    return {
        "message": "API key rotated successfully",
        "tenant_id": tenant_id,
        "rotated_at": tenant.rotated_at,
    }

