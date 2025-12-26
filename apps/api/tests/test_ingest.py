"""Tests for ingest endpoint."""

import pytest
from fastapi.testclient import TestClient

from origin_api.main import app

client = TestClient(app)


@pytest.fixture
def api_key():
    """Get test API key."""
    return "demo-api-key-12345"


def test_ingest_basic(api_key):
    """Test basic ingest."""
    response = client.post(
        "/v1/ingest",
        headers={
            "x-api-key": api_key,
            "idempotency-key": "test-123",
        },
        json={
            "account_external_id": "user-001",
            "account_type": "user",
            "upload_external_id": "upload-001",
            "metadata": {"title": "Test Upload"},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "ingestion_id" in data
    assert "decision" in data
    assert data["decision"] in ["ALLOW", "REVIEW", "QUARANTINE", "REJECT"]
    assert "triggered_rules" in data
    assert "decision_rationale" in data
    assert "ml_signals" in data
    assert "risk_score" in data["ml_signals"]
    assert "assurance_score" in data["ml_signals"]
    assert "primary_label" in data["ml_signals"]
    assert "class_probabilities" in data["ml_signals"]
    assert isinstance(data["ml_signals"]["class_probabilities"], dict)


def test_ingest_missing_api_key():
    """Test ingest without API key."""
    response = client.post(
        "/v1/ingest",
        json={
            "account_external_id": "user-001",
            "upload_external_id": "upload-001",
        },
    )
    assert response.status_code == 401


def test_ingest_idempotency(api_key):
    """Test idempotency."""
    idempotency_key = "test-idempotency-123"
    
    # First request
    response1 = client.post(
        "/v1/ingest",
        headers={
            "x-api-key": api_key,
            "idempotency-key": idempotency_key,
        },
        json={
            "account_external_id": "user-002",
            "upload_external_id": "upload-002",
        },
    )
    assert response1.status_code == 200
    ingestion_id1 = response1.json()["ingestion_id"]

    # Second request with same idempotency key
    response2 = client.post(
        "/v1/ingest",
        headers={
            "x-api-key": api_key,
            "idempotency-key": idempotency_key,
        },
        json={
            "account_external_id": "user-002",
            "upload_external_id": "upload-002",
        },
    )
    assert response2.status_code == 200
    ingestion_id2 = response2.json()["ingestion_id"]
    
    # Should return same ingestion_id
    assert ingestion_id1 == ingestion_id2

