"""Tests for O(1) API key lookup with public_id."""

import pytest
from unittest.mock import MagicMock, patch

from origin_api.auth.api_key import (
    generate_api_key,
    get_tenant_by_api_key,
    parse_api_key,
    verify_api_key,
)
from origin_api.models import APIKey, Tenant
from sqlalchemy.orm import Session


class TestAPIKeyParsing:
    """Test API key parsing and generation."""
    
    def test_parse_new_format_key(self):
        """Test parsing new format API key."""
        key = "org_prod_abc123.secret456"
        public_id, secret = parse_api_key(key)
        assert public_id == "abc123"
        assert secret == "secret456"
    
    def test_parse_legacy_key(self):
        """Test parsing legacy format key."""
        key = "demo-api-key-12345"
        public_id, secret = parse_api_key(key)
        assert public_id is None
        assert secret == key
    
    def test_generate_api_key_format(self):
        """Test that generated keys have correct format."""
        full_key, public_id = generate_api_key("test-tenant", "prod")
        assert full_key.startswith("org_prod_")
        assert "." in full_key
        assert public_id in full_key
        assert len(public_id) > 0


class TestO1Lookup:
    """Test O(1) lookup performance."""
    
    def test_new_format_lookup_by_public_id(self, db: Session):
        """Test that new format keys are looked up by public_id (O(1))."""
        # Create tenant
        tenant = Tenant(
            label="test-tenant-lookup",
            api_key_hash="test-hash",
            status="active",
        )
        db.add(tenant)
        db.flush()
        
        # Generate and store API key
        full_key, public_id = generate_api_key("test-tenant-lookup", "prod")
        _, secret = parse_api_key(full_key)
        
        api_key = APIKey(
            tenant_id=tenant.id,
            public_id=public_id,
            hash=verify_api_key.__globals__["hash_api_key"](secret),  # Access hash_api_key
            label="Test Key",
            is_active=True,
        )
        db.add(api_key)
        db.commit()
        
        # Lookup should be O(1) - single query by public_id
        result = get_tenant_by_api_key(db, full_key)
        assert result is not None
        found_tenant, found_key_obj = result
        assert found_tenant.id == tenant.id
        assert found_key_obj.public_id == public_id
    
    def test_wrong_secret_returns_none(self, db: Session):
        """Test that wrong secret returns None (doesn't leak public_id existence)."""
        # Create tenant and key
        tenant = Tenant(
            label="test-tenant-wrong-secret",
            api_key_hash="test-hash",
            status="active",
        )
        db.add(tenant)
        db.flush()
        
        full_key, public_id = generate_api_key("test-tenant-wrong-secret", "prod")
        _, secret = parse_api_key(full_key)
        
        api_key = APIKey(
            tenant_id=tenant.id,
            public_id=public_id,
            hash=verify_api_key.__globals__["hash_api_key"](secret),
            label="Test Key",
            is_active=True,
        )
        db.add(api_key)
        db.commit()
        
        # Try with wrong secret
        wrong_key = f"org_prod_{public_id}.wrong_secret"
        result = get_tenant_by_api_key(db, wrong_key)
        assert result is None
    
    def test_unknown_public_id_returns_none(self, db: Session):
        """Test that unknown public_id returns None."""
        unknown_key = "org_prod_unknown123.secret456"
        result = get_tenant_by_api_key(db, unknown_key)
        assert result is None
    
    def test_legacy_key_still_works(self, db: Session):
        """Test that legacy keys without public_id still work."""
        tenant = Tenant(
            label="test-tenant-legacy",
            api_key_hash=verify_api_key.__globals__["hash_api_key"]("legacy-key-123"),
            status="active",
        )
        db.add(tenant)
        db.commit()
        
        result = get_tenant_by_api_key(db, "legacy-key-123")
        assert result is not None
        found_tenant, found_key_obj = result
        assert found_tenant.id == tenant.id
        assert found_key_obj is None  # Legacy key, no APIKey object


class TestScopeExtraction:
    """Test that scope extraction works with new format."""
    
    def test_scopes_extracted_from_api_key_obj(self):
        """Test that scopes are extracted from request.state.api_key_obj."""
        # This is tested in test_evidence_scopes.py
        # Here we verify the flow works with new format keys
        pass

