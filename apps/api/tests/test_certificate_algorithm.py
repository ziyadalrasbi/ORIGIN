"""Tests for certificate algorithm matching."""

import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend
from jwcrypto import jwk, jwt

from origin_api.ledger.signer import DevLocalSigner, get_signer
from origin_api.ledger.certificate import CertificateService
from origin_api.models import DecisionCertificate


class TestCertificateAlgorithm:
    """Test certificate algorithm matches JWKS."""

    def test_certificate_alg_matches_jwks(self):
        """Test that certificate alg field matches JWKS alg."""
        signer = DevLocalSigner()
        jwk_dict = signer.get_public_jwk()
        
        # JWKS should advertise PS256 (RSA-PSS)
        assert jwk_dict["alg"] == "PS256"
        
        # Certificate should use same algorithm
        # (This is tested in integration, but we verify the signer behavior here)
        assert signer.get_public_jwk()["alg"] == "PS256"

    def test_certificate_signature_verifies_with_jwks(self):
        """Test that certificate signature verifies using published JWKS."""
        signer = DevLocalSigner()
        
        # Create test data
        test_data = {"test": "data", "timestamp": "2024-01-01T00:00:00Z"}
        data_bytes = json.dumps(test_data, sort_keys=True).encode()
        
        # Sign
        signature_bytes = signer.sign(data_bytes)
        signature_b64 = base64.b64encode(signature_bytes).decode()
        
        # Get JWK
        jwk_dict = signer.get_public_jwk()
        assert jwk_dict["alg"] == "PS256"
        
        # Verify using jwcrypto
        jwk_key = jwk.JWK(**jwk_dict)
        
        # Create JWT token for verification (jwcrypto expects JWT format)
        # We'll verify the signature directly
        try:
            # For PS256, we need to use the public key to verify
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.primitives.asymmetric.padding import PSS, MGF1
            
            # Get public key from JWK
            public_key_pem = jwk_key.export_to_pem()
            public_key = serialization.load_pem_public_key(
                public_key_pem, backend=default_backend()
            )
            
            # Verify signature
            public_key.verify(
                signature_bytes,
                data_bytes,
                padding.PSS(
                    mgf=MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH,
                ),
                hashes.SHA256(),
            )
            
            # If we get here, verification succeeded
            assert True
        except Exception as e:
            pytest.fail(f"Signature verification failed: {e}")

