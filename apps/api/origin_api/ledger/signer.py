"""Signing abstraction for decision certificates (KMS-ready)."""

import base64
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import load_der_public_key

from origin_api.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


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
            "alg": "PS256",  # RSA-PSS SHA-256 (matches actual signing algorithm)
            "n": int_to_base64url(n),
            "e": int_to_base64url(e),
        }

    def get_key_id(self) -> str:
        """Get key identifier."""
        return self._key_id


class KmsSigner(Signer):
    """AWS KMS signer for production."""

    def __init__(self, key_id: str):
        """Initialize KMS signer."""
        self.key_id = key_id
        self._kms_client = None
        self._public_key_cache = None
        self._key_metadata = None
        self._initialize_kms()

    def _initialize_kms(self):
        """Initialize AWS KMS client and validate configuration."""
        try:
            # Initialize KMS client
            self._kms_client = boto3.client("kms", region_name=settings.aws_region)

            # Validate key exists and get metadata
            try:
                response = self._kms_client.describe_key(KeyId=self.key_id)
                self._key_metadata = response["KeyMetadata"]
                
                # Validate key spec (must be RSA)
                key_spec = self._key_metadata.get("KeySpec", "")
                if "RSA" not in key_spec:
                    raise ValueError(
                        f"KMS key {self.key_id} must be RSA key spec, got {key_spec}"
                    )

                # Validate key usage (must be SIGN_VERIFY)
                key_usage = self._key_metadata.get("KeyUsage", "")
                if key_usage != "SIGN_VERIFY":
                    raise ValueError(
                        f"KMS key {self.key_id} must have SIGN_VERIFY usage, got {key_usage}"
                    )

                logger.info(
                    f"KMS signer initialized for key {self.key_id}",
                    extra={"key_arn": self._key_metadata.get("Arn")},
                )
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code == "NotFoundException":
                    raise ValueError(f"KMS key {self.key_id} not found")
                elif error_code == "AccessDeniedException":
                    raise ValueError(f"Access denied to KMS key {self.key_id}")
                else:
                    raise ValueError(f"Failed to access KMS key {self.key_id}: {e}")

        except BotoCoreError as e:
            raise ValueError(f"Failed to initialize KMS client: {e}")

    def sign(self, data: bytes) -> bytes:
        """Sign data using KMS."""
        try:
            # Use RSASSA_PSS_SHA_256 for signing
            response = self._kms_client.sign(
                KeyId=self.key_id,
                Message=data,
                MessageType="RAW",
                SigningAlgorithm="RSASSA_PSS_SHA_256",
            )
            return response["Signature"]
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "NotFoundException":
                raise ValueError(f"KMS key {self.key_id} not found")
            elif error_code == "AccessDeniedException":
                raise ValueError(f"Access denied to KMS key {self.key_id}")
            else:
                raise ValueError(f"KMS signing failed: {e}")

    def get_public_jwk(self) -> dict:
        """Get public key from KMS in JWK format."""
        if self._public_key_cache:
            return self._public_key_cache

        try:
            # Get public key from KMS
            response = self._kms_client.get_public_key(KeyId=self.key_id)
            public_key_der = response["PublicKey"]

            # Parse DER public key
            public_key = load_der_public_key(public_key_der, backend=default_backend())

            # Extract RSA public numbers
            if not isinstance(public_key, rsa.RSAPublicKey):
                raise ValueError(f"KMS key {self.key_id} is not RSA")

            public_numbers = public_key.public_numbers()
            n = public_numbers.n
            e = public_numbers.e

            # Convert to base64url
            def int_to_base64url(value: int) -> str:
                byte_length = (value.bit_length() + 7) // 8
                bytes_value = value.to_bytes(byte_length, "big")
                return base64.urlsafe_b64encode(bytes_value).decode("utf-8").rstrip("=")

            # Build kid from key ID and version
            key_version = response.get("KeyVersionId", "default")
            kid = f"{self.key_id}:{key_version}"

            jwk = {
                "kty": "RSA",
                "kid": kid,
                "use": "sig",
                "alg": "PS256",  # RSA-PSS SHA-256 (matches actual signing algorithm RSASSA_PSS_SHA_256)
                "n": int_to_base64url(n),
                "e": int_to_base64url(e),
            }

            # Cache the JWK
            self._public_key_cache = jwk

            return jwk

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "NotFoundException":
                raise ValueError(f"KMS key {self.key_id} not found")
            elif error_code == "AccessDeniedException":
                raise ValueError(f"Access denied to KMS key {self.key_id}")
            else:
                raise ValueError(f"Failed to get KMS public key: {e}")

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
            raise ValueError("SIGNING_KEY_ID required for AWS KMS")
        if not settings.aws_region:
            raise ValueError("AWS_REGION required for AWS KMS")
        return KmsSigner(settings.signing_key_id)
    else:
        raise ValueError(f"Unknown signing provider: {provider}")
