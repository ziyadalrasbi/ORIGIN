"""Tests for KMS signer."""

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from origin_api.ledger.signer import KmsSigner


@pytest.fixture
def mock_kms_client():
    """Mock KMS client."""
    client = MagicMock()
    
    # Mock describe_key
    client.describe_key.return_value = {
        "KeyMetadata": {
            "KeyId": "test-key-id",
            "KeySpec": "RSA_2048",
            "KeyUsage": "SIGN_VERIFY",
            "Arn": "arn:aws:kms:us-east-1:123456789012:key/test-key-id",
        }
    }
    
    # Mock sign
    client.sign.return_value = {
        "Signature": b"fake_signature_bytes",
        "SigningAlgorithm": "RSASSA_PSS_SHA_256",
    }
    
    # Mock get_public_key
    # Create a mock DER public key (simplified)
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    public_key_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    
    client.get_public_key.return_value = {
        "PublicKey": public_key_der,
        "KeyId": "test-key-id",
        "KeyVersionId": "v1",
    }
    
    return client


@patch("boto3.client")
def test_kms_signer_initialization(mock_boto_client, mock_kms_client):
    """Test KMS signer initialization."""
    mock_boto_client.return_value = mock_kms_client
    
    signer = KmsSigner("test-key-id")
    
    assert signer.key_id == "test-key-id"
    mock_kms_client.describe_key.assert_called_once_with(KeyId="test-key-id")


@patch("boto3.client")
def test_kms_signer_sign(mock_boto_client, mock_kms_client):
    """Test KMS signer signing."""
    mock_boto_client.return_value = mock_kms_client
    
    signer = KmsSigner("test-key-id")
    data = b"test data to sign"
    
    signature = signer.sign(data)
    
    assert signature == b"fake_signature_bytes"
    mock_kms_client.sign.assert_called_once_with(
        KeyId="test-key-id",
        Message=data,
        MessageType="RAW",
        SigningAlgorithm="RSASSA_PSS_SHA_256",
    )


@patch("boto3.client")
def test_kms_signer_get_public_jwk(mock_boto_client, mock_kms_client):
    """Test KMS signer JWK generation."""
    mock_boto_client.return_value = mock_kms_client
    
    signer = KmsSigner("test-key-id")
    
    jwk = signer.get_public_jwk()
    
    assert jwk["kty"] == "RSA"
    assert jwk["kid"] == "test-key-id:v1"
    assert jwk["use"] == "sig"
    assert jwk["alg"] == "RS256"
    assert "n" in jwk
    assert "e" in jwk
    
    mock_kms_client.get_public_key.assert_called_once_with(KeyId="test-key-id")


@patch("boto3.client")
def test_kms_signer_key_not_found(mock_boto_client):
    """Test KMS signer handles key not found."""
    from botocore.exceptions import ClientError
    
    mock_client = MagicMock()
    error_response = {"Error": {"Code": "NotFoundException", "Message": "Key not found"}}
    mock_client.describe_key.side_effect = ClientError(error_response, "DescribeKey")
    mock_boto_client.return_value = mock_client
    
    with pytest.raises(ValueError, match="KMS key.*not found"):
        KmsSigner("nonexistent-key-id")

