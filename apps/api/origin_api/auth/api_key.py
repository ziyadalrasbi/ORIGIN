"""API key authentication."""

import hashlib
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from origin_api.db.session import get_db
from origin_api.models import APIKey, Tenant

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_api_key(api_key: str) -> str:
    """Hash an API key."""
    return pwd_context.hash(api_key)


def verify_api_key(api_key: str, hashed: str) -> bool:
    """Verify an API key against its hash."""
    return pwd_context.verify(api_key, hashed)


def get_tenant_by_api_key(db: Session, api_key: str) -> Optional[Tenant]:
    """Get tenant by API key."""
    # Find active API key
    api_key_obj = (
        db.query(APIKey)
        .filter(
            APIKey.is_active == True,  # noqa: E712
            APIKey.revoked_at.is_(None),
        )
        .all()
    )

    # Check each API key hash
    for key_obj in api_key_obj:
        if verify_api_key(api_key, key_obj.hash):
            return db.query(Tenant).filter(Tenant.id == key_obj.tenant_id).first()

    # Fallback: check tenant's api_key_hash (legacy)
    tenants = db.query(Tenant).filter(Tenant.status == "active").all()
    for tenant in tenants:
        if verify_api_key(api_key, tenant.api_key_hash):
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

