"""Encryption service for webhook secrets and sensitive data."""

import base64
import logging
import secrets
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from origin_api.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class EncryptionService:
    """Encryption service for sensitive data."""

    def __init__(self):
        """Initialize encryption service."""
        self.provider = settings.webhook_encryption_provider.lower()
        self._kms_client = None
        self._fernet = None
        self._initialize()

    def _initialize(self):
        """Initialize encryption backend."""
        # Enforce KMS in non-dev environments
        env = settings.environment.lower()
        if env not in ("development", "test", "dev") and self.provider == "local":
            raise ValueError(
                f"Local encryption provider not allowed in {env} environment. "
                "Set WEBHOOK_ENCRYPTION_PROVIDER=aws_kms and configure KMS keys."
            )
        
        if self.provider == "aws_kms":
            if not settings.webhook_encryption_key_id:
                raise ValueError("WEBHOOK_ENCRYPTION_KEY_ID required for AWS KMS encryption")
            if not settings.aws_region:
                raise ValueError("AWS_REGION required for AWS KMS encryption")
            
            try:
                self._kms_client = boto3.client(
                    "kms",
                    region_name=settings.aws_region,
                    aws_access_key_id=settings.aws_access_key_id,
                    aws_secret_access_key=settings.aws_secret_access_key,
                )
                # Validate key exists
                self._kms_client.describe_key(KeyId=settings.webhook_encryption_key_id)
                logger.info(f"KMS encryption initialized with key {settings.webhook_encryption_key_id}")
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code == "NotFoundException":
                    raise ValueError(f"KMS encryption key {settings.webhook_encryption_key_id} not found")
                raise ValueError(f"Failed to initialize KMS encryption: {e}")
        elif self.provider == "local":
            # Use Fernet with a key derived from secret_key and per-installation salt
            if not settings.local_encryption_salt:
                raise ValueError(
                    "LOCAL_ENCRYPTION_SALT required when WEBHOOK_ENCRYPTION_PROVIDER=local. "
                    "Generate a random 32-byte salt per installation."
                )
            
            # Decode salt from base64 or use as-is if it's bytes
            try:
                salt_bytes = base64.b64decode(settings.local_encryption_salt)
            except Exception:
                # If not base64, use as string and encode
                salt_bytes = settings.local_encryption_salt.encode()[:32].ljust(32, b'\0')
            
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt_bytes,
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(settings.secret_key.encode()))
            self._fernet = Fernet(key)
            logger.info("Local Fernet encryption initialized with per-installation salt")
        else:
            raise ValueError(f"Unknown encryption provider: {self.provider}")

    def encrypt(self, plaintext: str, encryption_context: Optional[dict] = None) -> dict:
        """Encrypt plaintext and return ciphertext metadata."""
        if self.provider == "aws_kms":
            try:
                response = self._kms_client.encrypt(
                    KeyId=settings.webhook_encryption_key_id,
                    Plaintext=plaintext.encode(),
                    EncryptionContext=encryption_context or {},
                )
                ciphertext = response["CiphertextBlob"]
                return {
                    "ciphertext": base64.b64encode(ciphertext).decode(),
                    "key_id": response["KeyId"],
                    "encryption_context": encryption_context or {},
                }
            except ClientError as e:
                raise ValueError(f"KMS encryption failed: {e}")
        else:
            # Local Fernet
            encrypted = self._fernet.encrypt(plaintext.encode())
            return {
                "ciphertext": encrypted.decode(),
                "key_id": "local",
                "encryption_context": encryption_context or {},
            }

    def decrypt(self, ciphertext_data: dict) -> str:
        """Decrypt ciphertext and return plaintext."""
        ciphertext = ciphertext_data["ciphertext"]
        key_id = ciphertext_data.get("key_id")

        if self.provider == "aws_kms":
            try:
                ciphertext_blob = base64.b64decode(ciphertext)
                response = self._kms_client.decrypt(
                    CiphertextBlob=ciphertext_blob,
                    EncryptionContext=ciphertext_data.get("encryption_context", {}),
                )
                return response["Plaintext"].decode()
            except ClientError as e:
                raise ValueError(f"KMS decryption failed: {e}")
        else:
            # Local Fernet
            decrypted = self._fernet.decrypt(ciphertext.encode())
            return decrypted.decode()

    def generate_secret(self) -> str:
        """Generate a random webhook secret."""
        return secrets.token_urlsafe(32)


# Global encryption service instance
_encryption_service: Optional[EncryptionService] = None


def get_encryption_service() -> EncryptionService:
    """Get encryption service instance."""
    global _encryption_service
    if _encryption_service is None:
        _encryption_service = EncryptionService()
    return _encryption_service

