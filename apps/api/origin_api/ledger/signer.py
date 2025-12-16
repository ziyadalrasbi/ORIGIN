"""Signing abstraction for decision certificates (KMS-ready)."""

import base64
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend

from origin_api.settings import get_settings

settings = get_settings()


class Signer(ABC):
    """Abstract signer interface."""

    @abstractmethod
    def sign(self, data: bytes) -> bytes:
        """Sign data and return signature bytes."""
        pass

    @abstractmethod
    def get_public_jwk(self) -> dict:
        """Get public key in JWK format."""
        pass

    @abstractmethod
    def get_key_id(self) -> str:
        """Get key identifier."""
        pass


class DevLocalSigner(Signer):
    """Local development signer using RSA keypair from file."""

    def __init__(self, key_path: Optional[str] = None):
        """Initialize local signer."""
        self.key_path = Path(key_path or settings.signing_key_path)
        self._private_key = None
        self._public_key = None
        self._key_id = "local-dev-key-1"
        self._load_or_generate_key()

    def _load_or_generate_key(self):
        """Load or generate RSA keypair."""
        if self.key_path.exists():
            # Load existing key
            with open(self.key_path, "rb") as f:
                self._private_key = serialization.load_pem_private_key(
                    f.read(), password=None, backend=default_backend()
                )
        else:
            # Generate new key
            self._private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend(),
            )
            # Save key
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.key_path, "wb") as f:
                f.write(
                    self._private_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                )

        self._public_key = self._private_key.public_key()

    def sign(self, data: bytes) -> bytes:
        """Sign data with RSA-PSS."""
        signature = self._private_key.sign(
            data,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        return signature

    def get_public_jwk(self) -> dict:
        """Get public key in JWK format."""
        public_numbers = self._public_key.public_numbers()
        n = public_numbers.n
        e = public_numbers.e

        # Convert to base64url
        def int_to_base64url(value: int) -> str:
            byte_length = (value.bit_length() + 7) // 8
            bytes_value = value.to_bytes(byte_length, "big")
            return base64.urlsafe_b64encode(bytes_value).decode("utf-8").rstrip("=")

        return {
            "kty": "RSA",
            "kid": self._key_id,
            "use": "sig",
            "alg": "RS256",
            "n": int_to_base64url(n),
            "e": int_to_base64url(e),
        }

    def get_key_id(self) -> str:
        """Get key identifier."""
        return self._key_id


class KmsSigner(Signer):
    """AWS KMS signer (placeholder for production)."""

    def __init__(self, key_id: str):
        """Initialize KMS signer."""
        self.key_id = key_id
        # TODO: Initialize AWS KMS client
        raise NotImplementedError("KMS signer not yet implemented")

    def sign(self, data: bytes) -> bytes:
        """Sign using KMS."""
        # TODO: Use boto3 KMS client
        raise NotImplementedError

    def get_public_jwk(self) -> dict:
        """Get public key from KMS."""
        # TODO: Retrieve public key from KMS
        raise NotImplementedError

    def get_key_id(self) -> str:
        """Get key identifier."""
        return self.key_id


def get_signer() -> Signer:
    """Get signer instance based on settings."""
    provider = settings.signing_key_provider.lower()

    if provider == "local":
        return DevLocalSigner()
    elif provider == "aws_kms":
        if not settings.signing_key_id:
            raise ValueError("signing_key_id required for AWS KMS")
        return KmsSigner(settings.signing_key_id)
    else:
        raise ValueError(f"Unknown signing provider: {provider}")

