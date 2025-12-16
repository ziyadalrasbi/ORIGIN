"""Tests for API key auth performance."""

import time

import pytest
from sqlalchemy.orm import Session

from origin_api.auth.api_key import compute_key_digest, compute_key_prefix, get_tenant_by_api_key
from origin_api.db.session import SessionLocal
from origin_api.models import APIKey, Tenant


@pytest.fixture
def db():
    """Get database session."""
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture
def test_tenant(db: Session):
    """Create test tenant with API key."""
    tenant = Tenant(
        label="test_perf",
        status="active",
    )
    db.add(tenant)
    db.flush()

    api_key = "test-api-key-perf-12345"
    api_key_obj = APIKey(
        tenant_id=tenant.id,
        prefix=compute_key_prefix(api_key),
        digest=compute_key_digest(api_key),
        label="Test Key",
        is_active=True,
    )
    db.add(api_key_obj)
    db.commit()
    return tenant, api_key


def test_auth_lookup_performance(db: Session, test_tenant):
    """Test that auth lookup is O(1) and fast."""
    tenant, api_key = test_tenant

    # Measure lookup time
    start = time.time()
    for _ in range(100):
        result = get_tenant_by_api_key(db, api_key)
        assert result is not None
        assert result.id == tenant.id
    elapsed = time.time() - start

    # Should be fast (< 100ms for 100 lookups)
    assert elapsed < 0.1, f"Lookup too slow: {elapsed}s for 100 lookups"


def test_auth_prefix_digest_correctness(db: Session, test_tenant):
    """Test prefix and digest computation."""
    tenant, api_key = test_tenant

    prefix = compute_key_prefix(api_key)
    digest = compute_key_digest(api_key)

    assert len(prefix) == 8
    assert len(digest) == 64  # SHA256 hex

    # Should find tenant
    result = get_tenant_by_api_key(db, api_key)
    assert result is not None
    assert result.id == tenant.id

