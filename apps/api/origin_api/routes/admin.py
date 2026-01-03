"""Admin routes for tenant and policy management."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from origin_api.auth.api_key import generate_api_key, hash_api_key, parse_api_key
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
        api_key_hash=hash_api_key(tenant_data.api_key),
        status="active",
    )
    db.add(tenant)
    db.flush()

    # Create API key
    api_key = APIKey(
        tenant_id=tenant.id,
        hash=hash_api_key(tenant_data.api_key),
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
            "risk_threshold_review": 40,
            "risk_threshold_quarantine": 70,
            "risk_threshold_reject": 90,
            "assurance_threshold_allow": 80,
            "anomaly_threshold": 30,
            "synthetic_threshold": 70,
        },
        weights_json={},
        decision_mode="score_first",
        regulatory_compliance_json={
            "DSA": {
                "article_14": "Content moderation obligations - risk_score thresholds map to moderation tiers",
                "article_15": "Transparency reporting - decision_rationale provides audit trail",
                "article_16": "Risk assessment - risk_score, anomaly_score, synthetic_likelihood inform assessment",
                "mapped_thresholds": {
                    "risk_threshold_reject": "Article 14 - Immediate removal threshold",
                    "risk_threshold_quarantine": "Article 14 - Restriction threshold",
                    "risk_threshold_review": "Article 16 - Risk assessment trigger",
                }
            },
            "OSA": {
                "section_9": "Duty to assess risk - risk_score and assurance_score inform risk assessment",
                "section_10": "Duty to prevent harm - QUARANTINE/REJECT decisions prevent harmful content",
                "section_19": "Transparency reporting - evidence packs provide decision audit trail",
                "mapped_thresholds": {
                    "risk_threshold_reject": "Section 10 - Harmful content removal",
                    "synthetic_threshold": "Section 9 - AI-generated content detection",
                    "anomaly_threshold": "Section 9 - Anomalous behavior detection",
                }
            },
            "AI_Act": {
                "article_50": "Transparency obligations - synthetic_likelihood detects AI-generated content",
                "article_52": "High-risk AI systems - risk_score thresholds identify high-risk content",
                "mapped_thresholds": {
                    "synthetic_threshold": "Article 50 - AI content disclosure threshold",
                    "risk_threshold_quarantine": "Article 52 - High-risk content identification",
                }
            }
        },
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

    # Parse or generate new API key
    public_id = None
    api_key_hash = None
    
    if request.new_api_key:
        if "." in request.new_api_key and request.new_api_key.startswith("org_"):
            # New format
            public_id, secret = parse_api_key(request.new_api_key)
            api_key_hash = hash_api_key(secret)
        else:
            # Legacy format
            api_key_hash = hash_api_key(request.new_api_key)
    else:
        # Generate new key
        full_key, public_id = generate_api_key(tenant.label, "prod")
        _, secret = parse_api_key(full_key)
        api_key_hash = hash_api_key(secret)
        request.new_api_key = full_key
    
    # Create new API key
    new_api_key = APIKey(
        tenant_id=tenant.id,
        public_id=public_id,
        hash=api_key_hash,
        label=request.label or "Rotated API Key",
        scopes='["ingest", "evidence", "read"]',
        is_active=True,
    )
    db.add(new_api_key)

    # Update tenant's api_key_hash (legacy support)
    tenant.api_key_hash = api_key_hash
    tenant.rotated_at = datetime.utcnow()

    db.commit()

    return {
        "message": "API key rotated successfully",
        "tenant_id": tenant_id,
        "rotated_at": tenant.rotated_at,
    }

