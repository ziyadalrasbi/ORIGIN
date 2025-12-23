"""Tests for identity resolver service."""

import pytest
from unittest.mock import Mock, patch

from origin_api.identity.resolver import IdentityResolver


class TestIdentityResolver:
    """Test identity resolver features computation."""

    def test_compute_identity_features_prior_quarantine_count(self):
        """Test that prior_quarantine_count is correctly computed from Upload table."""
        # Arrange: Create mock DB session
        db = Mock()
        tenant_id = 1
        account_id = 100
        account_entity_id = 200
        
        # Mock query chains for device count, relationship count, and upload count
        mock_device_query = Mock()
        mock_device_query.join.return_value = mock_device_query
        mock_device_query.filter.return_value = mock_device_query
        mock_device_query.scalar.return_value = 2  # 2 shared devices
        
        mock_rel_query = Mock()
        mock_rel_query.filter.return_value = mock_rel_query
        mock_rel_query.scalar.return_value = 5  # 5 relationships
        
        mock_upload_query = Mock()
        mock_upload_query.filter.return_value = mock_upload_query
        mock_upload_query.count.return_value = 3  # 3 QUARANTINE uploads
        
        # Mock IdentityEntity query (for extracting account_id from entity)
        mock_entity_query = Mock()
        mock_entity_query.filter.return_value = mock_entity_query
        mock_account_entity = Mock()
        mock_account_entity.id = account_entity_id
        mock_account_entity.attributes_json = {"account_id": account_id}
        mock_entity_query.first.return_value = mock_account_entity
        
        # Configure db.query side effect
        def query_side_effect(model_class):
            if model_class.__name__ == "IdentityEntity":
                return mock_entity_query
            elif model_class.__name__ == "Upload":
                return mock_upload_query
            # For func.count queries
            return mock_device_query if "device" in str(model_class) else mock_rel_query
        
        db.query = Mock(side_effect=query_side_effect)
        
        # Mock func.count
        with patch('origin_api.identity.resolver.func') as mock_func:
            mock_func.count.return_value = mock_device_query
            
            resolver = IdentityResolver(db)
            
            # Act
            features = resolver.compute_identity_features(
                tenant_id=tenant_id,
                account_entity_id=account_entity_id,
                account_id=account_id,
            )
        
        # Assert
        assert features["prior_quarantine_count"] == 3, "Should count 3 QUARANTINE uploads"
        assert features["shared_device_count"] == 2, "Should have 2 shared devices"
        assert features["relationship_count"] == 5, "Should have 5 relationships"
        assert 0 <= features["identity_confidence"] <= 100, "identity_confidence should be in [0, 100]"

    def test_compute_identity_features_no_prior_quarantines(self):
        """Test that prior_quarantine_count is 0 when no QUARANTINE uploads exist."""
        # Arrange
        db = Mock()
        tenant_id = 1
        account_id = 100
        account_entity_id = 200
        
        mock_device_query = Mock()
        mock_device_query.join.return_value = mock_device_query
        mock_device_query.filter.return_value = mock_device_query
        mock_device_query.scalar.return_value = 0
        
        mock_rel_query = Mock()
        mock_rel_query.filter.return_value = mock_rel_query
        mock_rel_query.scalar.return_value = 0
        
        mock_upload_query = Mock()
        mock_upload_query.filter.return_value = mock_upload_query
        mock_upload_query.count.return_value = 0  # No quarantines
        
        mock_entity_query = Mock()
        mock_entity_query.filter.return_value = mock_entity_query
        mock_account_entity = Mock()
        mock_account_entity.attributes_json = {"account_id": account_id}
        mock_entity_query.first.return_value = mock_account_entity
        
        def query_side_effect(model_class):
            if model_class.__name__ == "IdentityEntity":
                return mock_entity_query
            elif model_class.__name__ == "Upload":
                return mock_upload_query
            return mock_device_query
        
        db.query = Mock(side_effect=query_side_effect)
        
        resolver = IdentityResolver(db)
        
        # Act
        with patch('origin_api.identity.resolver.func') as mock_func:
            mock_func.count.return_value = mock_device_query
            features = resolver.compute_identity_features(
                tenant_id=tenant_id,
                account_entity_id=account_entity_id,
                account_id=account_id,
            )
        
        # Assert
        assert features["prior_quarantine_count"] == 0, "Should have 0 prior quarantines"
        assert features["shared_device_count"] == 0, "Should have 0 shared devices"
        assert features["relationship_count"] == 0, "Should have 0 relationships"
        assert features["identity_confidence"] >= 0, "identity_confidence should be non-negative"

    def test_compute_identity_features_without_account_id(self):
        """Test that prior_quarantine_count works when account_id is extracted from entity."""
        # Arrange
        db = Mock()
        tenant_id = 1
        account_id = 100
        account_entity_id = 200
        
        mock_device_query = Mock()
        mock_device_query.join.return_value = mock_device_query
        mock_device_query.filter.return_value = mock_device_query
        mock_device_query.scalar.return_value = 1
        
        mock_rel_query = Mock()
        mock_rel_query.filter.return_value = mock_rel_query
        mock_rel_query.scalar.return_value = 2
        
        mock_upload_query = Mock()
        mock_upload_query.filter.return_value = mock_upload_query
        mock_upload_query.count.return_value = 1  # 1 quarantine
        
        mock_entity_query = Mock()
        mock_entity_query.filter.return_value = mock_entity_query
        mock_account_entity = Mock()
        mock_account_entity.id = account_entity_id
        mock_account_entity.attributes_json = {"account_id": account_id}
        mock_entity_query.first.return_value = mock_account_entity
        
        def query_side_effect(model_class):
            if model_class.__name__ == "IdentityEntity":
                return mock_entity_query
            elif model_class.__name__ == "Upload":
                return mock_upload_query
            return mock_device_query
        
        db.query = Mock(side_effect=query_side_effect)
        
        resolver = IdentityResolver(db)
        
        # Act: Call without account_id (should extract from entity)
        with patch('origin_api.identity.resolver.func') as mock_func:
            mock_func.count.return_value = mock_device_query
            features = resolver.compute_identity_features(
                tenant_id=tenant_id,
                account_entity_id=account_entity_id,
                account_id=None,  # Not provided, should extract from entity
            )
        
        # Assert
        assert features["prior_quarantine_count"] == 1, "Should extract account_id from entity and find 1 quarantine"
        assert features["shared_device_count"] == 1
        assert features["relationship_count"] == 2
        assert 0 <= features["identity_confidence"] <= 100

