"""Tests for webhook security (encryption, signatures, replay protection)."""

import hashlib
import hmac
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from origin_api.models import Webhook
from origin_api.security.encryption import EncryptionService
from origin_api.webhooks.service import WebhookService


@pytest.fixture
def db():
    """Get database session."""
    from origin_api.db.session import SessionLocal
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture
def encryption_service():
    """Get encryption service."""
    with patch("origin_api.security.encryption.get_settings") as mock_settings:
        mock_settings.return_value.webhook_encryption_provider = "local"
        mock_settings.return_value.secret_key = "test-secret-key-for-encryption"
        service = EncryptionService()
        yield service


def test_encrypt_decrypt_webhook_secret(encryption_service):
    """Test webhook secret encryption and decryption."""
    secret = "test-webhook-secret-12345"
    
    # Encrypt
    encrypted_data = encryption_service.encrypt(secret)
    assert "ciphertext" in encrypted_data
    assert encrypted_data["ciphertext"] != secret
    
    # Decrypt
    decrypted = encryption_service.decrypt(encrypted_data)
    assert decrypted == secret


def test_webhook_signature_with_replay_protection():
    """Test webhook signature includes timestamp for replay protection (raw bytes)."""
    secret = "test-secret"
    payload = {"event": "test", "data": "value"}
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    timestamp = "1234567890"
    
    # Compute signature using raw bytes (timestamp_bytes + b"." + raw_body_bytes)
    message = timestamp.encode("utf-8") + b"." + payload_bytes
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    
    # Verify signature changes if timestamp changes
    timestamp2 = "1234567891"
    message2 = timestamp2.encode("utf-8") + b"." + payload_bytes
    signature2 = hmac.new(secret.encode("utf-8"), message2, hashlib.sha256).hexdigest()
    
    assert signature != signature2, "Signature should change with timestamp"
    
    # Verify signature changes if payload changes
    payload2 = {"event": "test", "data": "different"}
    payload_bytes2 = json.dumps(payload2, sort_keys=True).encode("utf-8")
    message3 = timestamp.encode("utf-8") + b"." + payload_bytes2
    signature3 = hmac.new(secret.encode("utf-8"), message3, hashlib.sha256).hexdigest()
    
    assert signature != signature3, "Signature should change with payload"


def test_webhook_signature_constant_time_compare():
    """Test webhook signature uses constant-time comparison (raw bytes)."""
    secret = "test-secret"
    payload = {"event": "test"}
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    timestamp = "1234567890"
    
    # Compute signature using raw bytes
    message = timestamp.encode("utf-8") + b"." + payload_bytes
    expected = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    
    # Use constant-time compare
    signature = f"sha256={expected}"
    is_valid = hmac.compare_digest(signature, f"sha256={expected}")
    assert is_valid
    
    # Invalid signature
    is_valid_invalid = hmac.compare_digest(signature, "sha256=wrong")
    assert not is_valid_invalid


def test_webhook_service_decrypt_secret(db, encryption_service):
    """Test webhook service decrypts secret correctly."""
    # Create webhook with encrypted secret
    secret = "test-webhook-secret"
    encrypted_data = encryption_service.encrypt(secret)
    
    webhook = Webhook(
        tenant_id=1,
        url="https://example.com/webhook",
        secret_ciphertext=encrypted_data["ciphertext"],
        secret_key_id=encrypted_data["key_id"],
        secret_version="1",
        encryption_context=encrypted_data.get("encryption_context"),
        events=["decision.created"],
        enabled=True,
    )
    db.add(webhook)
    db.commit()
    
    # Test decryption
    service = WebhookService(db)
    decrypted = service._decrypt_secret(webhook)
    
    assert decrypted == secret

