"""API key authentication with scalable prefix+digest lookup."""

import hashlib
import hmac
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from origin_api.db.session import get_db
from origin_api.models import APIKey, Tenant
from origin_api.settings import get_settings

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()


def compute_key_prefix(raw_key: str) -> str:
    """Compute prefix (first 8 chars) of API key."""
    return raw_key[:8] if len(raw_key) >= 8 else raw_key


def compute_key_digest(raw_key: str) -> str:
    """Compute HMAC-SHA256 digest of API key."""
    secret = settings.secret_key.encode()
    return hmac.new(secret, raw_key.encode(), hashlib.sha256).hexdigest()


def hash_api_key_bcrypt(api_key: str) -> str:
    """Hash an API key using bcrypt (legacy only)."""
    return pwd_context.hash(api_key)


def verify_api_key_bcrypt(api_key: str, hashed: str) -> bool:
    """Verify an API key against bcrypt hash (legacy only)."""
    return pwd_context.verify(api_key, hashed)


def get_tenant_by_api_key(db: Session, api_key: str) -> Optional[Tenant]:
    """Get tenant by API key using scalable prefix+digest lookup."""
    if not api_key or len(api_key) < 8:
        return None

    # Compute prefix and digest
    prefix = compute_key_prefix(api_key)
    digest = compute_key_digest(api_key)

    # Query with indexed prefix lookup (O(1) with index)
    api_key_obj = (
        db.query(APIKey)
        .filter(
            APIKey.prefix == prefix,
            APIKey.is_active == True,  # noqa: E712
            APIKey.revoked_at.is_(None),
        )
        .first()
    )

    if api_key_obj:
        # Constant-time comparison of digest
        if api_key_obj.digest and hmac.compare_digest(api_key_obj.digest, digest):
            # Update last_used_at
            api_key_obj.last_used_at = datetime.utcnow()
            db.commit()
            return db.query(Tenant).filter(Tenant.id == api_key_obj.tenant_id).first()

    # Legacy fallback (only if feature flag enabled)
    if settings.legacy_apikey_fallback:
        tenants = db.query(Tenant).filter(Tenant.status == "active").all()
        for tenant in tenants:
            if tenant.api_key_hash and verify_api_key_bcrypt(api_key, tenant.api_key_hash):
                return tenant

    return None


async def get_current_tenant(
    x_api_key: Optional[str] = Security(api_key_header),
    db: Session = next(get_db()),
) -> Tenant:
    """Get current tenant from API key."""
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide x-api-key header.",
        )

    tenant = get_tenant_by_api_key(db, x_api_key)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key.",
        )

    if tenant.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant status is {tenant.status}.",
        )

    return tenant
