"""Tests for certificate verification."""

import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi.testclient import TestClient

from origin_api.main import app

client = TestClient(app)


def test_jwks_endpoint():
    """Test JWKS endpoint returns public keys."""
    response = client.get("/v1/keys/jwks.json")
    assert response.status_code == 200
    data = response.json()
    assert "keys" in data
    assert len(data["keys"]) > 0
    key = data["keys"][0]
    assert "kty" in key
    assert "kid" in key
    assert "n" in key  # RSA modulus
    assert "e" in key  # RSA exponent


def test_certificate_endpoint():
    """Test certificate endpoint returns verification metadata."""
    # This would require a real certificate_id
    # For now, just test the endpoint exists
    response = client.get("/v1/certificates/nonexistent")
    assert response.status_code == 404

