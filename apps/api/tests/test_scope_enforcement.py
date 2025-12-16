"""Tests for scope enforcement on all endpoints."""

import pytest
from fastapi.testclient import TestClient

from origin_api.main import app
from origin_api.models import APIKey, Tenant
from origin_api.auth.api_key import compute_key_digest, compute_key_prefix


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def tenant_with_api_key(db):
    """Create tenant with API key."""
    tenant = Tenant(
        label="test-tenant",
        status="active",
    )
    db.add(tenant)
    db.flush()
    
    api_key = APIKey(
        tenant_id=tenant.id,
        prefix=compute_key_prefix("test-key-12345"),
        digest=compute_key_digest("test-key-12345"),
        scopes='["read"]',  # Only read scope
        is_active=True,
    )
    db.add(api_key)
    db.commit()
    
    return tenant, api_key, "test-key-12345"


def test_ingest_requires_ingest_write_scope(client, db, tenant_with_api_key):
    """Test that /v1/ingest requires ingest:write scope."""
    tenant, api_key, raw_key = tenant_with_api_key
    
    # Try with read-only scope (should fail)
    response = client.post(
        "/v1/ingest",
        json={
            "account_external_id": "acc-1",
            "upload_external_id": "up-1",
        },
        headers={"x-api-key": raw_key},
    )
    assert response.status_code == 403
    assert "Insufficient permissions" in response.json()["detail"]
    
    # Update API key to have ingest:write scope
    api_key.scopes = '["ingest:write"]'
    db.commit()
    
    # Should now succeed (or fail for other reasons, but not 403)
    response = client.post(
        "/v1/ingest",
        json={
            "account_external_id": "acc-1",
            "upload_external_id": "up-1",
        },
        headers={"x-api-key": raw_key},
    )
    assert response.status_code != 403  # May be 200, 400, etc., but not 403


def test_evidence_requires_evidence_scope(client, db, tenant_with_api_key):
    """Test that evidence endpoints require evidence scope."""
    tenant, api_key, raw_key = tenant_with_api_key
    
    # Try POST /v1/evidence-packs with read-only scope (should fail)
    response = client.post(
        "/v1/evidence-packs",
        json={"certificate_id": "test-cert", "format": "json"},
        headers={"x-api-key": raw_key},
    )
    assert response.status_code == 403
    
    # Try GET /v1/evidence-packs with read-only scope (should fail - needs evidence:read)
    response = client.get(
        "/v1/evidence-packs/test-cert",
        headers={"x-api-key": raw_key},
    )
    assert response.status_code == 403
    
    # Update to have evidence:read scope
    api_key.scopes = '["evidence:read"]'
    db.commit()
    
    # GET should work now
    response = client.get(
        "/v1/evidence-packs/test-cert",
        headers={"x-api-key": raw_key},
    )
    assert response.status_code != 403  # May be 404, but not 403


def test_admin_requires_admin_scope(client, db, tenant_with_api_key):
    """Test that /admin endpoints require admin scope."""
    tenant, api_key, raw_key = tenant_with_api_key
    
    # Try admin endpoint with read-only scope (should fail)
    response = client.post(
        "/admin/tenants",
        json={"label": "new-tenant", "api_key": "new-key"},
        headers={"x-api-key": raw_key},
    )
    assert response.status_code == 403
    
    # Update to have admin scope
    api_key.scopes = '["admin"]'
    db.commit()
    
    # Should now work (or fail for other reasons, but not 403)
    response = client.post(
        "/admin/tenants",
        json={"label": "new-tenant-2", "api_key": "new-key-2"},
        headers={"x-api-key": raw_key},
    )
    assert response.status_code != 403


def test_webhooks_require_webhooks_scope(client, db, tenant_with_api_key):
    """Test that webhook endpoints require webhooks scope."""
    tenant, api_key, raw_key = tenant_with_api_key
    
    # Try POST /v1/webhooks with read-only scope (should fail)
    response = client.post(
        "/v1/webhooks",
        json={"url": "https://example.com/webhook", "events": ["decision.created"]},
        headers={"x-api-key": raw_key},
    )
    assert response.status_code == 403
    
    # Try GET /v1/webhooks/{id}/deliveries with read-only scope (should fail - needs webhooks:read)
    response = client.get(
        "/v1/webhooks/1/deliveries",
        headers={"x-api-key": raw_key},
    )
    assert response.status_code == 403

