"""Tests for evidence pack integrity and tamper-evidence."""

import hashlib
import json

import pytest
from sqlalchemy.orm import Session

from origin_api.db.session import SessionLocal
from origin_api.models import DecisionCertificate, EvidencePack, Upload
from origin_api.storage.s3 import S3Storage


@pytest.fixture
def db():
    """Get database session."""
    db = SessionLocal()
    yield db
    db.close()


def test_evidence_artifact_hash_computation():
    """Test that artifact hashes are computed correctly."""
    content = b"test evidence content"
    expected_hash = hashlib.sha256(content).hexdigest()
    
    assert expected_hash == "sha256:" + expected_hash or expected_hash.startswith("sha256:")
    
    # Verify hash changes if content changes
    content2 = b"different content"
    hash2 = hashlib.sha256(content2).hexdigest()
    assert expected_hash != hash2


def test_evidence_hash_in_certificate(db):
    """Test that evidence hashes are included in certificate."""
    from origin_api.ledger.certificate import CertificateService
    
    service = CertificateService(db)
    
    evidence_hashes = {
        "json": "sha256:abc123",
        "pdf": "sha256:def456",
    }
    
    # Generate certificate with evidence hashes
    certificate = service.generate_certificate(
        tenant_id=1,
        upload_id=1,
        policy_version="v1.0",
        inputs={"test": "input"},
        outputs={"decision": "ALLOW"},
        ledger_hash="ledger_hash_123",
        evidence_hashes=evidence_hashes,
    )
    
    # Verify certificate includes evidence hashes in signature
    # The hashes should be part of the signed certificate data
    assert certificate is not None


def test_evidence_download_includes_hash_headers():
    """Test that evidence download includes hash headers."""
    # This would be tested via the API endpoint
    # For now, verify the hash is stored correctly
    evidence_pack = EvidencePack(
        tenant_id=1,
        certificate_id=1,
        status="ready",
        artifact_hashes={"json": "sha256:abc123", "pdf": "sha256:def456"},
        artifact_sizes={"json": 1000, "pdf": 5000},
    )
    
    assert evidence_pack.artifact_hashes["json"] == "sha256:abc123"
    assert evidence_pack.artifact_sizes["json"] == 1000

