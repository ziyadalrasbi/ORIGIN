"""API key authentication."""

import base64
import hashlib
import secrets
from typing import Optional, tuple

import bcrypt
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from origin_api.db.session import get_db
from origin_api.models import APIKey, Tenant

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)


def hash_api_key(api_key: str) -> str:
    """Hash an API key using bcrypt."""
    # Bcrypt has 72-byte limit, truncate if necessary
    api_key_bytes = api_key.encode('utf-8')
    if len(api_key_bytes) > 72:
        api_key_bytes = api_key_bytes[:72]
    return bcrypt.hashpw(api_key_bytes, bcrypt.gensalt()).decode('utf-8')


def verify_api_key(api_key: str, hashed: str) -> bool:
    """Verify an API key against its hash."""
    try:
        # Bcrypt has 72-byte limit, truncate if necessary
        api_key_bytes = api_key.encode('utf-8')
        if len(api_key_bytes) > 72:
            api_key_bytes = api_key_bytes[:72]
        return bcrypt.checkpw(api_key_bytes, hashed.encode('utf-8'))
    except Exception:
        return False


def parse_api_key(api_key: str) -> tuple[Optional[str], str]:
    """
    Parse API key into (public_id, secret) tuple.
    
    Format: "org_<env>_<public_id>.<secret>"
    Returns: (public_id, secret) or (None, api_key) for legacy keys
    """
    if "." not in api_key:
        # Legacy key format (no public_id)
        return (None, api_key)
    
    parts = api_key.rsplit(".", 1)  # Split on last dot only
    if len(parts) != 2:
        return (None, api_key)
    
    prefix_and_public_id = parts[0]
    secret = parts[1]
    
    # Extract public_id from prefix (format: org_<env>_<public_id>)
    if "_" in prefix_and_public_id:
        public_id = prefix_and_public_id.rsplit("_", 1)[-1]
        return (public_id, secret)
    
    return (None, api_key)


def generate_api_key(tenant_label: str, environment: str = "prod") -> tuple[str, str]:
    """
    Generate a new API key in format: "org_<env>_<public_id>.<secret>"
    
    Returns:
        Tuple of (full_api_key, public_id)
    """
    # Generate public_id (urlsafe base64, 16 bytes = 22 chars)
    public_id_bytes = secrets.token_bytes(16)
    public_id = base64.urlsafe_b64encode(public_id_bytes).decode('utf-8').rstrip('=')
    
    # Generate secret (urlsafe base64, 32 bytes = 44 chars)
    secret_bytes = secrets.token_bytes(32)
    secret = base64.urlsafe_b64encode(secret_bytes).decode('utf-8').rstrip('=')
    
    # Format: org_<env>_<public_id>.<secret>
    full_key = f"org_{environment}_{public_id}.{secret}"
    
    return (full_key, public_id)


def get_tenant_by_api_key(db: Session, api_key: str) -> Optional[tuple[Tenant, Optional[APIKey]]]:
    """
    Get tenant and API key object by API key (O(1) lookup for new format).
    
    New format: "org_<env>_<public_id>.<secret>" -> lookup by public_id, verify secret
    Legacy format: full key -> fallback to scanning tenant.api_key_hash
    
    Returns:
        Tuple of (Tenant, APIKey) or (Tenant, None) for legacy keys.
        Returns None if not found.
    """
    # Parse API key
    public_id, secret = parse_api_key(api_key)
    
    if public_id:
        # New format: O(1) lookup by public_id
        key_obj = (
            db.query(APIKey)
            .filter(
                APIKey.public_id == public_id,
                APIKey.is_active == True,  # noqa: E712
                APIKey.revoked_at.is_(None),
            )
            .first()
        )
        
        if key_obj:
            # Verify secret against hash
            if verify_api_key(secret, key_obj.hash):
                tenant = db.query(Tenant).filter(Tenant.id == key_obj.tenant_id).first()
                if tenant:
                    return (tenant, key_obj)
            # Wrong secret - don't leak that public_id exists
            return None
    
    # Legacy format: fallback to tenant.api_key_hash (for backward compatibility)
    tenants = db.query(Tenant).filter(Tenant.status == "active").all()
    for tenant in tenants:
        if verify_api_key(api_key, tenant.api_key_hash):
            return (tenant, None)  # Legacy key, no APIKey object
    
    # Also check legacy APIKey records (without public_id) - one more fallback
    # This is still O(n) but only for legacy keys
    legacy_keys = (
        db.query(APIKey)
        .filter(
            APIKey.public_id.is_(None),  # Only legacy keys
            APIKey.is_active == True,  # noqa: E712
            APIKey.revoked_at.is_(None),
        )
        .all()
    )
    
    for key_obj in legacy_keys:
        if verify_api_key(api_key, key_obj.hash):
            tenant = db.query(Tenant).filter(Tenant.id == key_obj.tenant_id).first()
            if tenant:
                return (tenant, key_obj)
    
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

