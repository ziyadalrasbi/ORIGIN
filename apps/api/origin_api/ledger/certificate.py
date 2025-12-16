"""Decision certificate generation and signing."""

import base64
import hashlib
import json
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from origin_api.models import DecisionCertificate, Upload
from origin_api.ledger.signer import get_signer

signer = get_signer()


class CertificateService:
    """Generate and sign decision certificates."""

    def __init__(self, db: Session):
        """Initialize certificate service."""
        self.db = db
        self.signer = get_signer()

    def _hash_inputs(self, inputs: dict) -> str:
        """Hash policy inputs."""
        inputs_str = json.dumps(inputs, sort_keys=True)
        return hashlib.sha256(inputs_str.encode()).hexdigest()

    def _hash_outputs(self, outputs: dict) -> str:
        """Hash decision outputs."""
        outputs_str = json.dumps(outputs, sort_keys=True)
        return hashlib.sha256(outputs_str.encode()).hexdigest()

    def generate_certificate(
        self,
        tenant_id: int,
        upload_id: int,
        policy_version: str,
        inputs: dict,
        outputs: dict,
        ledger_hash: str,
        evidence_hashes: Optional[dict] = None,
    ) -> DecisionCertificate:
        """Generate signed decision certificate."""
        certificate_id = str(uuid.uuid4())

        # Hash inputs and outputs
        inputs_hash = self._hash_inputs(inputs)
        outputs_hash = self._hash_outputs(outputs)

        # Create certificate data (include evidence hashes if provided)
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
        
        # Include evidence artifact hashes for tamper-evident verification
        if evidence_hashes:
            certificate_data["evidence_hashes"] = evidence_hashes

        # Sign certificate
        certificate_bytes = json.dumps(certificate_data, sort_keys=True).encode()
        signature_bytes = self.signer.sign(certificate_bytes)
        signature = base64.b64encode(signature_bytes).decode()

        # Get key ID
        key_id = self.signer.get_key_id()

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
            key_id=key_id,
            alg="RS256",
            signature_encoding="base64",
        )

        self.db.add(certificate)
        self.db.flush()

        return certificate
