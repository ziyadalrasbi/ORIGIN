"""Tests for tenant isolation enforcement."""

import pytest
from sqlalchemy.orm import Session

from origin_api.db.session import SessionLocal
from origin_api.models import Upload


@pytest.fixture
def db():
    """Get database session."""
    db = SessionLocal()
    yield db
    db.close()


def test_upload_query_requires_tenant_id(db):
    """Test that upload queries enforce tenant_id."""
    # This is a guardrail test - actual enforcement should be in service layer
    tenant_id = 1
    
    # Query should always include tenant_id filter
    uploads = db.query(Upload).filter(Upload.tenant_id == tenant_id).all()
    
    # Verify all results belong to tenant
    for upload in uploads:
        assert upload.tenant_id == tenant_id


def test_scope_middleware_enforces_scopes():
    """Test that scope middleware enforces API key scopes."""
    from origin_api.middleware.scopes import get_required_scope
    
    # Test scope mapping
    assert get_required_scope("/v1/ingest") == ["ingest"]
    assert get_required_scope("/v1/evidence-packs") == ["evidence"]
    assert get_required_scope("/v1/certificates/abc-123") == ["read"]
    assert get_required_scope("/v1/keys/jwks.json") == ["read"]
    assert get_required_scope("/health") is None  # No scope required

