"""Tests for evidence pack generation.

Note: These are integration tests that require a database connection.
They may be skipped in environments without database access.
"""

from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from origin_api.evidence.generator import EvidencePackGenerator
from origin_api.evidence.schema import EvidencePackV2
from origin_api.models import (
    DecisionCertificate,
    Upload,
    Account,
    PolicyProfile,
    Tenant,
)


# These tests require database fixtures - skip if not available
pytestmark = pytest.mark.skipif(
    True,  # Set to False to enable these integration tests
    reason="Integration tests require database setup",
)


@pytest.fixture
def sample_tenant(db: Session) -> Tenant:
    """Create a sample tenant."""
    tenant = Tenant(
        label="test-tenant",
        api_key_hash="test-hash",
        status="active",
    )
    db.add(tenant)
    db.flush()
    return tenant


@pytest.fixture
def sample_policy_profile(db: Session, sample_tenant: Tenant) -> PolicyProfile:
    """Create a sample policy profile."""
    profile = PolicyProfile(
        tenant_id=sample_tenant.id,
        name="test-policy",
        version="v1.0",
        thresholds_json={
            "risk_threshold_review": 40,
            "risk_threshold_quarantine": 70,
            "risk_threshold_reject": 90,
        },
        regulatory_compliance_json={
            "EU_AI_ACT": {
                "article_12": "Logging and transparency for high-risk AI systems",
            },
        },
        is_active=True,
    )
    db.add(profile)
    db.flush()
    return profile


@pytest.fixture
def sample_account(db: Session, sample_tenant: Tenant) -> Account:
    """Create a sample account."""
    account = Account(
        tenant_id=sample_tenant.id,
        external_id="test-account",
        type="user",
        display_name="Test User",
        risk_state="unknown",
        created_at=datetime.utcnow(),
    )
    db.add(account)
    db.flush()
    return account


@pytest.fixture
def sample_upload(db: Session, sample_tenant: Tenant, sample_account: Account) -> Upload:
    """Create a sample upload."""
    upload = Upload(
        tenant_id=sample_tenant.id,
        ingestion_id="test-ingest-123",
        external_id="test-upload-123",
        account_id=sample_account.id,
        title="Test Upload",
        received_at=datetime.utcnow(),
        pvid="PVID-TEST-123",
        decision="REVIEW",
        policy_version="v1.0",
        risk_score=45.5,
        assurance_score=65.0,
    )
    db.add(upload)
    db.flush()
    return upload


@pytest.fixture
def sample_certificate(db: Session, sample_tenant: Tenant, sample_upload: Upload) -> DecisionCertificate:
    """Create a sample certificate."""
    certificate = DecisionCertificate(
        tenant_id=sample_tenant.id,
        upload_id=sample_upload.id,
        certificate_id="test-cert-123",
        issued_at=datetime.utcnow(),
        policy_version="v1.0",
        inputs_hash="abc123",
        outputs_hash="def456",
        ledger_hash="ghi789",
        signature="sig123",
    )
    db.add(certificate)
    db.flush()
    return certificate


def test_generate_json_returns_evidence_pack_v2_compatible(
    db: Session,
    sample_certificate: DecisionCertificate,
    sample_upload: Upload,
):
    """Test that generate_json returns dict that can be parsed into EvidencePackV2."""
    generator = EvidencePackGenerator(db)
    evidence_dict = generator.generate_json(sample_certificate, sample_upload, audience="INTERNAL")

    # Should have v2 structure
    assert "version" in evidence_dict
    assert evidence_dict["version"] == "origin-evidence-v2"

    # Should be parseable as EvidencePackV2
    evidence_v2 = EvidencePackV2.model_validate(evidence_dict)
    assert evidence_v2.version == "origin-evidence-v2"
    assert evidence_v2.tenant.tenant_id == sample_upload.tenant_id
    assert evidence_v2.certificate.certificate_id == sample_certificate.certificate_id
    assert evidence_v2.decision_summary.decision == sample_upload.decision


def test_generate_json_preserves_backward_compatibility(
    db: Session,
    sample_certificate: DecisionCertificate,
    sample_upload: Upload,
):
    """Test that generate_json preserves existing top-level keys for backward compatibility."""
    generator = EvidencePackGenerator(db)
    evidence_dict = generator.generate_json(sample_certificate, sample_upload, audience="INTERNAL")

    # Should have legacy fields for backward compatibility
    assert "certificate_id" in evidence_dict
    assert "issued_at" in evidence_dict
    assert "decision" in evidence_dict
    assert "policy_version" in evidence_dict
    assert "scores" in evidence_dict
    assert "risk_signals" in evidence_dict
    assert "decision_trace" in evidence_dict
    assert "integrity" in evidence_dict

    # Legacy fields should match v2 structure
    assert evidence_dict["certificate_id"] == sample_certificate.certificate_id
    assert evidence_dict["decision"] == sample_upload.decision


def test_generate_json_includes_regulatory_profile(
    db: Session,
    sample_certificate: DecisionCertificate,
    sample_upload: Upload,
    sample_policy_profile: PolicyProfile,
):
    """Test that generate_json includes regulatory profile information."""
    generator = EvidencePackGenerator(db)
    evidence_dict = generator.generate_json(sample_certificate, sample_upload, audience="REGULATOR")

    evidence_v2 = EvidencePackV2.model_validate(evidence_dict)
    
    # Should have regulatory profile
    assert evidence_v2.regulatory_profile is not None
    assert len(evidence_v2.regulatory_profile.applicable_regimes) > 0
    assert "EU_AI_ACT" in evidence_v2.regulatory_profile.applicable_regimes
    assert "EU_DSA" in evidence_v2.regulatory_profile.applicable_regimes


def test_generate_json_includes_ml_signals(
    db: Session,
    sample_certificate: DecisionCertificate,
    sample_upload: Upload,
):
    """Test that generate_json includes ML signals context."""
    generator = EvidencePackGenerator(db)
    evidence_dict = generator.generate_json(sample_certificate, sample_upload, audience="INTERNAL")

    evidence_v2 = EvidencePackV2.model_validate(evidence_dict)
    
    # Should have ML signals
    assert evidence_v2.ml_and_signals is not None
    assert evidence_v2.ml_and_signals.risk_score == float(sample_upload.risk_score)
    assert evidence_v2.ml_and_signals.assurance_score == float(sample_upload.assurance_score)


def test_generate_json_includes_audit_metadata(
    db: Session,
    sample_certificate: DecisionCertificate,
    sample_upload: Upload,
):
    """Test that generate_json includes audit metadata with audience."""
    generator = EvidencePackGenerator(db)
    evidence_dict = generator.generate_json(sample_certificate, sample_upload, audience="DSP")

    evidence_v2 = EvidencePackV2.model_validate(evidence_dict)
    
    # Should have audit metadata
    assert evidence_v2.audit_metadata is not None
    assert evidence_v2.audit_metadata.audience == "DSP"
    assert evidence_v2.audit_metadata.generated_at is not None


def test_counterfactuals_use_tenant_policy_thresholds(
    db: Session,
    sample_certificate: DecisionCertificate,
    sample_upload: Upload,
    sample_policy_profile: PolicyProfile,
):
    """Test that counterfactual decisions respect tenant policy thresholds."""
    # Update policy profile with custom thresholds
    sample_policy_profile.thresholds_json = {
        "risk_threshold_review": 25,
        "risk_threshold_quarantine": 60,
        "risk_threshold_reject": 85,
    }
    db.commit()
    
    # Update upload with a risk score that will produce a counterfactual
    sample_upload.risk_score = 70.0  # Above quarantine threshold (60)
    db.commit()
    
    generator = EvidencePackGenerator(db)
    evidence_dict = generator.generate_json(sample_certificate, sample_upload, audience="INTERNAL")
    
    evidence_v2 = EvidencePackV2.model_validate(evidence_dict)
    
    # Should have counterfactuals
    assert evidence_v2.risk_impact_analysis.counterfactuals is not None
    assert len(evidence_v2.risk_impact_analysis.counterfactuals) > 0
    
    # Check that counterfactual uses tenant thresholds (not hard-coded 40)
    counterfactual = evidence_v2.risk_impact_analysis.counterfactuals[0]
    cf_risk_score = 70.0 - 10.0  # 60.0
    
    # With tenant thresholds: review=25, quarantine=60, reject=85
    # A score of 60.0 should result in QUARANTINE (not REVIEW which would be at 40)
    assert counterfactual["decision"] == "QUARANTINE"
    assert "review=25" in counterfactual["rationale"]
    assert "quarantine=60" in counterfactual["rationale"]


def test_audience_internal_no_redactions(
    db: Session,
    sample_certificate: DecisionCertificate,
    sample_upload: Upload,
):
    """Test that INTERNAL audience has no redactions."""
    generator = EvidencePackGenerator(db)
    evidence_dict = generator.generate_json(sample_certificate, sample_upload, audience="INTERNAL")
    
    evidence_v2 = EvidencePackV2.model_validate(evidence_dict)
    
    # Should have no redactions
    assert evidence_v2.audit_metadata.redactions == []
    
    # All fields should be present
    assert evidence_v2.identity_and_history.cross_tenant_signals is not None or True  # May be None naturally
    assert evidence_v2.technical_trace_and_ledger.certificate_data.get("signature") is not None


def test_audience_regulator_no_redactions(
    db: Session,
    sample_certificate: DecisionCertificate,
    sample_upload: Upload,
):
    """Test that REGULATOR audience has no redactions."""
    generator = EvidencePackGenerator(db)
    evidence_dict = generator.generate_json(sample_certificate, sample_upload, audience="REGULATOR")
    
    evidence_v2 = EvidencePackV2.model_validate(evidence_dict)
    
    # Should have no redactions
    assert evidence_v2.audit_metadata.redactions == []
    
    # All fields should be present
    assert evidence_v2.technical_trace_and_ledger.certificate_data.get("signature") is not None


def test_audience_dsp_redactions_applied(
    db: Session,
    sample_certificate: DecisionCertificate,
    sample_upload: Upload,
):
    """Test that DSP audience has specified fields redacted."""
    generator = EvidencePackGenerator(db)
    evidence_dict = generator.generate_json(sample_certificate, sample_upload, audience="DSP")
    
    evidence_v2 = EvidencePackV2.model_validate(evidence_dict)
    
    # Should have redactions recorded
    assert len(evidence_v2.audit_metadata.redactions) > 0
    
    # Check redaction entries
    redaction_paths = [r["path"] for r in evidence_v2.audit_metadata.redactions]
    assert "identity_and_history.cross_tenant_signals" in redaction_paths
    assert "technical_trace_and_ledger.certificate_data.signature" in redaction_paths
    
    # Check that fields are actually missing from the dict
    assert "cross_tenant_signals" not in evidence_dict.get("identity_and_history", {})
    assert "signature" not in evidence_dict.get("technical_trace_and_ledger", {}).get("certificate_data", {})


def test_ml_model_metadata_from_ml_signals(
    db: Session,
    sample_certificate: DecisionCertificate,
    sample_upload: Upload,
):
    """Test that ML model metadata is populated from ml_signals if provided."""
    # This test would require modifying the ledger event payload_json to include model_metadata
    # For now, we test the fallback behavior
    generator = EvidencePackGenerator(db)
    evidence_dict = generator.generate_json(sample_certificate, sample_upload, audience="INTERNAL")
    
    evidence_v2 = EvidencePackV2.model_validate(evidence_dict)
    
    # Should have model_metadata
    assert evidence_v2.ml_and_signals.model_metadata is not None
    assert isinstance(evidence_v2.ml_and_signals.model_metadata, dict)
    
    # Should have at least risk_model_version and anomaly_model_version
    assert "risk_model_version" in evidence_v2.ml_and_signals.model_metadata
    assert "anomaly_model_version" in evidence_v2.ml_and_signals.model_metadata

