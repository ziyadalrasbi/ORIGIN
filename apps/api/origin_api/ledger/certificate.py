"""Decision certificate generation and signing."""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from sqlalchemy.orm import Session

from origin_api.models import DecisionCertificate, Upload
from origin_api.settings import get_settings

settings = get_settings()


class CertificateService:
    """Generate and sign decision certificates."""

    def __init__(self, db: Session):
        """Initialize certificate service."""
        self.db = db
        self._private_key = None
        self._load_or_generate_key()

    def _load_or_generate_key(self):
        """Load or generate signing key."""
        # In production, load from secure storage
        # For MVP, generate a key (not secure for production!)
        from cryptography.hazmat.backends import default_backend

        # Generate a key pair (in production, use a proper key management system)
        self._private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )

    def _hash_inputs(self, inputs: dict) -> str:
        """Hash policy inputs."""
        inputs_str = json.dumps(inputs, sort_keys=True)
        return hashlib.sha256(inputs_str.encode()).hexdigest()

    def _hash_outputs(self, outputs: dict) -> str:
        """Hash decision outputs."""
        outputs_str = json.dumps(outputs, sort_keys=True)
        return hashlib.sha256(outputs_str.encode()).hexdigest()

    def _sign(self, data: bytes) -> str:
        """Sign data with private key."""
        signature = self._private_key.sign(
            data,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        # Encode as base64 for storage
        import base64
        return base64.b64encode(signature).decode()

    def generate_certificate(
        self,
        tenant_id: int,
        upload_id: int,
        policy_version: str,
        inputs: dict,
        outputs: dict,
        ledger_hash: str,
    ) -> DecisionCertificate:
        """Generate signed decision certificate."""
        certificate_id = str(uuid.uuid4())

        # Hash inputs and outputs
        inputs_hash = self._hash_inputs(inputs)
        outputs_hash = self._hash_outputs(outputs)

        # Create certificate data
        certificate_data = {
            "certificate_id": certificate_id,
            "tenant_id": tenant_id,
            "upload_id": upload_id,
            "policy_version": policy_version,
            "inputs_hash": inputs_hash,
            "outputs_hash": outputs_hash,
            "ledger_hash": ledger_hash,
            "issued_at": datetime.utcnow().isoformat(),
        }

        # Sign certificate
        certificate_bytes = json.dumps(certificate_data, sort_keys=True).encode()
        signature = self._sign(certificate_bytes)

        # Create certificate record
        certificate = DecisionCertificate(
            tenant_id=tenant_id,
            upload_id=upload_id,
            certificate_id=certificate_id,
            issued_at=datetime.utcnow(),
            policy_version=policy_version,
            inputs_hash=inputs_hash,
            outputs_hash=outputs_hash,
            ledger_hash=ledger_hash,
            signature=signature,
        )

        self.db.add(certificate)
        self.db.flush()

        return certificate

