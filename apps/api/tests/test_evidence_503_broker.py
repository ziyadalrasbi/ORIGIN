"""Tests for HTTP 503 responses when broker/Celery is unavailable."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from origin_api.main import app

client = TestClient(app)


class TestBrokerFailure503:
    """Test that broker failures return HTTP 503 with Retry-After."""
    
    @patch("origin_api.routes.evidence.get_celery_app")
    def test_broker_connection_error_returns_503(self, mock_get_celery_app):
        """Test that ConnectionError from broker returns HTTP 503."""
        # Mock Celery app
        mock_celery_app = MagicMock()
        mock_signature = MagicMock()
        mock_signature.apply_async.side_effect = ConnectionError("Broker connection failed")
        mock_celery_app.signature.return_value = mock_signature
        mock_get_celery_app.return_value = mock_celery_app
        
        # Mock database and certificate lookup
        with patch("origin_api.routes.evidence.get_db") as mock_db, \
             patch("origin_api.routes.evidence.get_tenant_by_api_key") as mock_tenant:
            from origin_api.models import DecisionCertificate, Tenant
            mock_tenant_obj = MagicMock(spec=Tenant)
            mock_tenant_obj.id = 1
            mock_tenant.return_value = (mock_tenant_obj, None)
            
            mock_cert = MagicMock(spec=DecisionCertificate)
            mock_cert.id = 1
            mock_cert.certificate_id = "test-cert-123"
            mock_cert.tenant_id = 1
            
            mock_db_session = MagicMock()
            mock_db_session.query.return_value.filter.return_value.first.return_value = mock_cert
            mock_db_session.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = None
            mock_db.return_value.__enter__.return_value = mock_db_session
            
            response = client.post(
                "/v1/evidence-packs",
                headers={"x-api-key": "demo-api-key-12345"},
                json={
                    "certificate_id": "test-cert-123",
                    "format": "json",
                },
            )
            
            # Should return 503
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "failed"
            assert data["error_code"] == "BROKER_UNAVAILABLE"
            assert "Retry-After" in response.headers
            assert response.headers["Retry-After"] == "30"
    
    @patch("origin_api.routes.evidence.get_celery_app")
    def test_broker_timeout_error_returns_503(self, mock_get_celery_app):
        """Test that TimeoutError from broker returns HTTP 503."""
        mock_celery_app = MagicMock()
        mock_signature = MagicMock()
        mock_signature.apply_async.side_effect = TimeoutError("Broker timeout")
        mock_celery_app.signature.return_value = mock_signature
        mock_get_celery_app.return_value = mock_celery_app
        
        with patch("origin_api.routes.evidence.get_db") as mock_db, \
             patch("origin_api.routes.evidence.get_tenant_by_api_key") as mock_tenant:
            from origin_api.models import DecisionCertificate, Tenant
            mock_tenant_obj = MagicMock(spec=Tenant)
            mock_tenant_obj.id = 1
            mock_tenant.return_value = (mock_tenant_obj, None)
            
            mock_cert = MagicMock(spec=DecisionCertificate)
            mock_cert.id = 1
            mock_cert.certificate_id = "test-cert-123"
            mock_cert.tenant_id = 1
            
            mock_db_session = MagicMock()
            mock_db_session.query.return_value.filter.return_value.first.return_value = mock_cert
            mock_db_session.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = None
            mock_db.return_value.__enter__.return_value = mock_db_session
            
            response = client.post(
                "/v1/evidence-packs",
                headers={"x-api-key": "demo-api-key-12345"},
                json={
                    "certificate_id": "test-cert-123",
                    "format": "json",
                },
            )
            
            assert response.status_code == 503
            data = response.json()
            assert data["error_code"] == "BROKER_UNAVAILABLE"
            assert "Retry-After" in response.headers
    
    @patch("origin_api.routes.evidence.get_celery_app")
    def test_kombu_operational_error_returns_503(self, mock_get_celery_app):
        """Test that kombu OperationalError returns HTTP 503."""
        # Simulate kombu OperationalError
        class MockOperationalError(Exception):
            pass
        
        mock_celery_app = MagicMock()
        mock_signature = MagicMock()
        mock_signature.apply_async.side_effect = MockOperationalError("Broker operational error")
        mock_celery_app.signature.return_value = mock_signature
        mock_get_celery_app.return_value = mock_celery_app
        
        with patch("origin_api.routes.evidence.get_db") as mock_db, \
             patch("origin_api.routes.evidence.get_tenant_by_api_key") as mock_tenant:
            from origin_api.models import DecisionCertificate, Tenant
            mock_tenant_obj = MagicMock(spec=Tenant)
            mock_tenant_obj.id = 1
            mock_tenant.return_value = (mock_tenant_obj, None)
            
            mock_cert = MagicMock(spec=DecisionCertificate)
            mock_cert.id = 1
            mock_cert.certificate_id = "test-cert-123"
            mock_cert.tenant_id = 1
            
            mock_db_session = MagicMock()
            mock_db_session.query.return_value.filter.return_value.first.return_value = mock_cert
            mock_db_session.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = None
            mock_db.return_value.__enter__.return_value = mock_db_session
            
            # Patch the exception handler to recognize MockOperationalError
            with patch("origin_api.routes.evidence.type") as mock_type:
                mock_type.return_value.__name__ = "OperationalError"
                
                response = client.post(
                    "/v1/evidence-packs",
                    headers={"x-api-key": "demo-api-key-12345"},
                    json={
                        "certificate_id": "test-cert-123",
                        "format": "json",
                    },
                )
                
                # Should return 503 for broker errors
                assert response.status_code == 503
                data = response.json()
                assert data["error_code"] in ("BROKER_UNAVAILABLE", "TASK_ENQUEUE_FAILED")
                assert "Retry-After" in response.headers


class TestCeleryUnavailable503:
    """Test that Celery unavailability returns HTTP 503."""
    
    @patch("origin_api.routes.evidence.get_celery_app")
    def test_celery_import_error_returns_503(self, mock_get_celery_app):
        """Test that ImportError returns HTTP 503."""
        mock_get_celery_app.side_effect = ImportError("Celery not available")
        
        with patch("origin_api.routes.evidence.get_db") as mock_db, \
             patch("origin_api.routes.evidence.get_tenant_by_api_key") as mock_tenant:
            from origin_api.models import DecisionCertificate, Tenant
            mock_tenant_obj = MagicMock(spec=Tenant)
            mock_tenant_obj.id = 1
            mock_tenant.return_value = (mock_tenant_obj, None)
            
            mock_cert = MagicMock(spec=DecisionCertificate)
            mock_cert.id = 1
            mock_cert.certificate_id = "test-cert-123"
            mock_cert.tenant_id = 1
            
            mock_db_session = MagicMock()
            mock_db_session.query.return_value.filter.return_value.first.return_value = mock_cert
            mock_db_session.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = None
            mock_db.return_value.__enter__.return_value = mock_db_session
            
            response = client.post(
                "/v1/evidence-packs",
                headers={"x-api-key": "demo-api-key-12345"},
                json={
                    "certificate_id": "test-cert-123",
                    "format": "json",
                },
            )
            
            assert response.status_code == 503
            data = response.json()
            assert data["error_code"] == "CELERY_UNAVAILABLE"
            assert "Retry-After" in response.headers

