"""Tests for EvidencePackV2 schema."""

from datetime import datetime

import pytest

from origin_api.evidence.schema import (
    EvidencePackV2,
    TenantContext,
    CertificateContext,
    UploadContext,
    DecisionSummary,
    MLSignalsContext,
    RegulatoryProfile,
    RiskImpactAnalysis,
    IdentityHistoryContext,
    GovernanceContext,
    TechnicalTraceContext,
    AuditMetadata,
)


def test_evidence_pack_v2_minimal_construction():
    """Test that a minimal EvidencePackV2 can be constructed."""
    evidence = EvidencePackV2(
        version="origin-evidence-v2",
        tenant=TenantContext(tenant_id=1),
        certificate=CertificateContext(
            certificate_id="test-cert-123",
            issued_at=datetime.utcnow(),
            policy_version="v1.0",
            inputs_hash="abc123",
            outputs_hash="def456",
            ledger_hash="ghi789",
            signature="sig123",
        ),
        upload=UploadContext(
            ingestion_id="ingest-123",
            external_id="ext-123",
            received_at=datetime.utcnow(),
        ),
        decision_summary=DecisionSummary(decision="ALLOW"),
        ml_and_signals=MLSignalsContext(risk_score=20.0, assurance_score=80.0),
        regulatory_profile=RegulatoryProfile(),
        risk_impact_analysis=RiskImpactAnalysis(risk_band="LOW"),
        identity_and_history=IdentityHistoryContext(),
        governance_and_accountability=GovernanceContext(),
        technical_trace_and_ledger=TechnicalTraceContext(),
        audit_metadata=AuditMetadata(generated_at=datetime.utcnow()),
    )

    assert evidence.version == "origin-evidence-v2"
    assert evidence.tenant.tenant_id == 1
    assert evidence.certificate.certificate_id == "test-cert-123"
    assert evidence.decision_summary.decision == "ALLOW"
    assert evidence.ml_and_signals.risk_score == 20.0


def test_evidence_pack_v2_from_current_evidence_fields():
    """Test that EvidencePackV2 can be constructed from current evidence fields."""
    # Simulate current evidence pack structure
    current_evidence = {
        "certificate_id": "cert-123",
        "issued_at": datetime.utcnow().isoformat(),
        "decision": "REVIEW",
        "risk_score": 45.5,
        "assurance_score": 65.0,
        "triggered_rules": ["MODEL_PRIMARY_LABEL", "GUARDRAIL_ANOMALY"],
        "reason_codes": ["MODEL_PRIMARY_LABEL_REVIEW", "ANOMALY_HIGH_RISK"],
        "rationale": "Model primary label REVIEW with risk_score=45.5",
        "ml_signals": {
            "risk_score": 45.5,
            "assurance_score": 65.0,
            "anomaly_score": 25.0,
            "synthetic_likelihood": 30.0,
            "identity_confidence": 70.0,
            "primary_label": "REVIEW",
            "class_probabilities": {"ALLOW": 0.3, "REVIEW": 0.6, "QUARANTINE": 0.1},
        },
        "integrity": {
            "inputs_hash": "abc123",
            "outputs_hash": "def456",
            "ledger_hash": "ghi789",
            "signature": "sig123",
        },
    }

    # Build EvidencePackV2 from current structure
    evidence = EvidencePackV2(
        version="origin-evidence-v2",
        tenant=TenantContext(tenant_id=1, tenant_name="test-tenant"),
        certificate=CertificateContext(
            certificate_id=current_evidence["certificate_id"],
            issued_at=datetime.fromisoformat(current_evidence["issued_at"].replace("Z", "+00:00")),
            policy_version="v1.0",
            inputs_hash=current_evidence["integrity"]["inputs_hash"],
            outputs_hash=current_evidence["integrity"]["outputs_hash"],
            ledger_hash=current_evidence["integrity"]["ledger_hash"],
            signature=current_evidence["integrity"]["signature"],
        ),
        upload=UploadContext(
            ingestion_id="ingest-123",
            external_id="ext-123",
            received_at=datetime.utcnow(),
        ),
        decision_summary=DecisionSummary(
            decision=current_evidence["decision"],
            triggered_rules=current_evidence["triggered_rules"],
            reason_codes=current_evidence["reason_codes"],
            decision_rationale=current_evidence["rationale"],
            human_review_required=True,
        ),
        ml_and_signals=MLSignalsContext(
            risk_score=current_evidence["ml_signals"]["risk_score"],
            assurance_score=current_evidence["ml_signals"]["assurance_score"],
            anomaly_score=current_evidence["ml_signals"].get("anomaly_score"),
            synthetic_likelihood=current_evidence["ml_signals"].get("synthetic_likelihood"),
            identity_confidence=current_evidence["ml_signals"].get("identity_confidence"),
            primary_label=current_evidence["ml_signals"].get("primary_label"),
            class_probabilities=current_evidence["ml_signals"].get("class_probabilities"),
        ),
        regulatory_profile=RegulatoryProfile(),
        risk_impact_analysis=RiskImpactAnalysis(risk_band="MEDIUM"),
        identity_and_history=IdentityHistoryContext(),
        governance_and_accountability=GovernanceContext(),
        technical_trace_and_ledger=TechnicalTraceContext(),
        audit_metadata=AuditMetadata(generated_at=datetime.utcnow()),
    )

    assert evidence.decision_summary.decision == "REVIEW"
    assert evidence.ml_and_signals.risk_score == 45.5
    assert evidence.ml_and_signals.primary_label == "REVIEW"
    assert len(evidence.decision_summary.triggered_rules) == 2


def test_evidence_pack_v2_extra_fields_ignored():
    """Test that unknown/excess fields are tolerated."""
    # Create dict with extra fields
    evidence_dict = {
        "version": "origin-evidence-v2",
        "tenant": {"tenant_id": 1},
        "certificate": {
            "certificate_id": "cert-123",
            "issued_at": datetime.utcnow().isoformat(),
            "policy_version": "v1.0",
            "inputs_hash": "abc123",
            "outputs_hash": "def456",
            "ledger_hash": "ghi789",
            "signature": "sig123",
        },
        "upload": {
            "ingestion_id": "ingest-123",
            "external_id": "ext-123",
            "received_at": datetime.utcnow().isoformat(),
        },
        "decision_summary": {"decision": "ALLOW"},
        "ml_and_signals": {"risk_score": 20.0, "assurance_score": 80.0},
        "regulatory_profile": {},
        "risk_impact_analysis": {"risk_band": "LOW"},
        "identity_and_history": {},
        "governance_and_accountability": {},
        "technical_trace_and_ledger": {},
        "audit_metadata": {"generated_at": datetime.utcnow().isoformat()},
        # Extra fields that should be ignored
        "legacy_field": "should be ignored",
        "old_structure": {"nested": "data"},
    }

    # Should parse successfully with extra fields ignored
    evidence = EvidencePackV2.model_validate(evidence_dict)
    assert evidence.version == "origin-evidence-v2"
    assert not hasattr(evidence, "legacy_field")


def test_regulatory_profile_defaults():
    """Test that RegulatoryProfile has sensible defaults."""
    profile = RegulatoryProfile()
    assert "EU_AI_ACT" in profile.applicable_regimes
    assert "EU_DSA" in profile.applicable_regimes
    assert profile.control_objectives == []
    assert profile.systemic_risk_tags == []


def test_decision_summary_human_review_required():
    """Test that human_review_required is set correctly."""
    summary = DecisionSummary(decision="REVIEW", human_review_required=True)
    assert summary.human_review_required is True

    summary = DecisionSummary(decision="ALLOW", human_review_required=False)
    assert summary.human_review_required is False


def test_ml_signals_context_model_metadata():
    """Test that MLSignalsContext can have model_metadata populated."""
    # Test with provided model_metadata
    ml_signals = MLSignalsContext(
        risk_score=50.0,
        assurance_score=70.0,
        model_metadata={
            "risk_model_version": "v2.1.0",
            "anomaly_model_version": "v1.5.0",
        },
    )
    assert ml_signals.model_metadata["risk_model_version"] == "v2.1.0"
    assert ml_signals.model_metadata["anomaly_model_version"] == "v1.5.0"
    
    # Test with empty model_metadata (default)
    ml_signals_empty = MLSignalsContext(
        risk_score=50.0,
        assurance_score=70.0,
    )
    assert ml_signals_empty.model_metadata == {}

