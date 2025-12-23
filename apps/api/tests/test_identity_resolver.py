"""Tests for identity resolver service."""

from unittest.mock import Mock, patch

from origin_api.identity.resolver import IdentityResolver
from origin_api.models import IdentityEntity, Upload


class TestIdentityResolver:
    """Test identity resolver features computation."""

    def test_compute_identity_features_prior_quarantine_count(self):
        """Prior quarantine count is derived from uploads."""
        db = Mock()
        tenant_id = 1
        account_id = 100
        account_entity_id = 200

        mock_device_query = Mock()
        mock_device_query.join.return_value = mock_device_query
        mock_device_query.filter.return_value = mock_device_query
        mock_device_query.scalar.return_value = 2

        mock_rel_query = Mock()
        mock_rel_query.filter.return_value = mock_rel_query
        mock_rel_query.scalar.return_value = 5

        mock_upload_query = Mock()
        mock_upload_query.filter.return_value = mock_upload_query
        mock_upload_query.count.return_value = 3

        mock_entity_query = Mock()
        mock_entity_query.filter.return_value = mock_entity_query
        mock_account_entity = Mock()
        mock_account_entity.id = account_entity_id
        mock_account_entity.attributes_json = {"account_id": account_id}
        mock_entity_query.first.return_value = mock_account_entity

        def query_side_effect(model_class):
            if model_class == IdentityEntity:
                return mock_entity_query
            if model_class == Upload:
                return mock_upload_query
            return mock_device_query

        db.query = Mock(side_effect=query_side_effect)

        resolver = IdentityResolver(db)

        with patch("origin_api.identity.resolver.func") as mock_func:
            mock_func.count.return_value = mock_device_query
            features = resolver.compute_identity_features(
                tenant_id=tenant_id,
                account_entity_id=account_entity_id,
                account_id=account_id,
            )

        assert features["prior_quarantine_count"] == 3
        assert features["shared_device_count"] == 2
        assert features["relationship_count"] == 5
        assert 0 <= features["identity_confidence"] <= 100

    def test_compute_identity_features_no_prior_quarantines(self):
        """No quarantines yields zero count and non-negative confidence."""
        db = Mock()
        tenant_id = 1
        account_id = 100
        account_entity_id = 200

        mock_device_query = Mock()
        mock_device_query.join.return_value = mock_device_query
        mock_device_query.filter.return_value = mock_device_query
        mock_device_query.scalar.return_value = 0

        mock_upload_query = Mock()
        mock_upload_query.filter.return_value = mock_upload_query
        mock_upload_query.count.return_value = 0

        mock_entity_query = Mock()
        mock_entity_query.filter.return_value = mock_entity_query
        mock_account_entity = Mock()
        mock_account_entity.id = account_entity_id
        mock_account_entity.attributes_json = {"account_id": account_id}
        mock_entity_query.first.return_value = mock_account_entity

        def query_side_effect(model_class):
            if model_class == IdentityEntity:
                return mock_entity_query
            if model_class == Upload:
                return mock_upload_query
            return mock_device_query

        db.query = Mock(side_effect=query_side_effect)

        resolver = IdentityResolver(db)

        with patch("origin_api.identity.resolver.func") as mock_func:
            mock_func.count.return_value = mock_device_query
            features = resolver.compute_identity_features(
                tenant_id=tenant_id,
                account_entity_id=account_entity_id,
                account_id=account_id,
            )

        assert features["prior_quarantine_count"] == 0
        assert features["shared_device_count"] == 0
        assert features["relationship_count"] == 0
        assert features["identity_confidence"] >= 0

    def test_compute_identity_features_without_account_id(self):
        """Account id extracted from entity attributes when not provided."""
        db = Mock()
        tenant_id = 1
        account_id = 100
        account_entity_id = 200

        mock_device_query = Mock()
        mock_device_query.join.return_value = mock_device_query
        mock_device_query.filter.return_value = mock_device_query
        mock_device_query.scalar.return_value = 1

        mock_upload_query = Mock()
        mock_upload_query.filter.return_value = mock_upload_query
        mock_upload_query.count.return_value = 1

        mock_entity_query = Mock()
        mock_entity_query.filter.return_value = mock_entity_query
        mock_account_entity = Mock()
        mock_account_entity.id = account_entity_id
        mock_account_entity.attributes_json = {"account_id": account_id}
        mock_entity_query.first.return_value = mock_account_entity

        def query_side_effect(model_class):
            if model_class == IdentityEntity:
                return mock_entity_query
            if model_class == Upload:
                return mock_upload_query
            return mock_device_query

        db.query = Mock(side_effect=query_side_effect)

        resolver = IdentityResolver(db)

        with patch("origin_api.identity.resolver.func") as mock_func:
            mock_func.count.return_value = mock_device_query
            features = resolver.compute_identity_features(
                tenant_id=tenant_id,
                account_entity_id=account_entity_id,
                account_id=None,
            )

        assert features["prior_quarantine_count"] == 1
        assert features["shared_device_count"] == 1
        assert features["relationship_count"] >= 0
        assert 0 <= features["identity_confidence"] <= 100

