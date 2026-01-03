"""Evidence Pack v2 schema for regulator-grade Decision Dossier.

This module defines the EvidencePackV2 schema aligned with EU AI Act and DSA
transparency/logging expectations. The schema supports:

- AI Act Art. 12-13: Logging and transparency requirements for high-risk AI systems
- DSA Art. 14-15: Systemic risk assessment and transparency obligations
- Comprehensive audit trails for regulatory compliance

The schema is designed to be backward compatible with existing evidence pack
structures while adding new regulatory-aligned fields.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ============================================================================
# Enums
# ============================================================================


class EvidenceAudience(str, Enum):
    """Evidence pack audience types."""

    INTERNAL = "INTERNAL"
    DSP = "DSP"
    REGULATOR = "REGULATOR"


class EvidenceFormat(str, Enum):
    """Evidence pack format types."""

    JSON = "json"
    PDF = "pdf"
    HTML = "html"


class RedactionRecord(BaseModel):
    """Redaction record for audit metadata."""

    path: str
    reason: str
    applied_for_audience: str


# ============================================================================
# Nested Context Models
# ============================================================================


class TenantContext(BaseModel):
    """Tenant context for multi-tenant deployments."""

    tenant_id: int
    tenant_name: Optional[str] = None
    jurisdiction: List[str] = Field(default_factory=list)  # e.g., ["EU", "US"]


class CertificateContext(BaseModel):
    """Decision certificate context with integrity hashes."""

    certificate_id: str
    issued_at: datetime
    policy_version: str
    inputs_hash: str
    outputs_hash: str
    ledger_hash: str
    signature: str
    signature_algorithm: str = "RSA-PSS-SHA256"
    key_fingerprint: Optional[str] = None


class UploadContext(BaseModel):
    """Upload/ingestion context."""

    ingestion_id: str
    external_id: str
    received_at: datetime
    pvid: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None
    content_ref: Optional[str] = None
    account_id: Optional[int] = None
    account_type: Optional[str] = None
    account_created_at: Optional[datetime] = None


class ReviewPlaybook(BaseModel):
    """Review playbook with actionable guidance (F1)."""
    
    recommended_next_checks: List[str] = Field(default_factory=list)
    evidence_to_request: List[str] = Field(default_factory=list)
    suggested_sla: Optional[str] = None  # e.g., "60-minute review target"
    routing_hints: Optional[Dict[str, Any]] = Field(default_factory=dict)  # e.g., {"priority": "high", "team": "content_moderation"}


class DecisionSummary(BaseModel):
    """Decision summary with rationale and review requirements."""

    decision: str  # ALLOW, REVIEW, QUARANTINE, REJECT
    decision_mode: str = "AUTO"  # AUTO, score_first, label_first
    decision_rationale: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)  # Legacy field
    reason_codes: List[str] = Field(default_factory=list)
    triggered_rules: List[str] = Field(default_factory=list)
    human_review_required: bool = False
    sla_guidance: Optional[str] = None  # e.g., "60-minute review target for REVIEW decisions"
    review_playbook: Optional[ReviewPlaybook] = None  # F1 - Actionable review guidance


class InterpretabilityCue(BaseModel):
    """Interpretability cue (heuristic or model-based explanation)."""

    feature: str
    direction: str  # positive, negative
    explanation: str
    explanation_method: Literal["heuristic", "model_based"] = "heuristic"


class SignalDefinition(BaseModel):
    """Signal definition for clarity and auditability (E)."""
    
    key: str
    description: str
    scope: str  # "tenant" or "cross_tenant"
    query_window: Optional[str] = None  # e.g., "90d", "all_time"


class MLSignalsContext(BaseModel):
    """ML model signals and predictions."""

    risk_score: float
    assurance_score: float
    anomaly_score: Optional[float] = None
    synthetic_likelihood: Optional[float] = None
    identity_confidence: Optional[float] = None
    # Renamed for precision (E1)
    pvid_prior_uploads_90d: Optional[int] = None  # Prior uploads with same PVID in last 90 days
    pvid_prior_uploads_total: Optional[int] = None  # Total prior uploads with same PVID (all time)
    content_ref_prior_uploads_total: Optional[int] = None  # Prior uploads with same content_ref (all time)
    isrc_prior_uploads_total: Optional[int] = None  # Prior uploads with same ISRC if present (all time)
    # Legacy fields for backward compatibility (deprecated)
    prior_sightings_count: Optional[int] = None  # Deprecated: use pvid_prior_uploads_90d
    prior_quarantine_count: Optional[int] = None  # Deprecated: use identity_and_history.prior_quarantine_count
    has_prior_quarantine: bool = False
    has_prior_reject: bool = False
    primary_label: Optional[str] = None
    class_probabilities: Optional[Dict[str, float]] = None
    interpretability_cues: List[InterpretabilityCue] = Field(
        default_factory=list
    )  # Renamed from feature_contributions for honesty
    model_metadata: Dict[str, Any] = Field(
        default_factory=dict
    )  # {"risk_model_version": "...", "anomaly_model_version": "..."}
    signal_definitions: List[SignalDefinition] = Field(
        default_factory=list
    )  # Signal definitions for clarity (E1)


class RegulatoryProfile(BaseModel):
    """Regulatory compliance profile.

    Supports AI Act Art. 12-13 logging/transparency and DSA systemic risk logging.
    """

    applicable_regimes: List[str] = Field(
        default_factory=lambda: ["EU_AI_ACT", "EU_DSA"]
    )  # EU_AI_ACT, EU_DSA, EU_OSA, etc.
    control_objectives: List[Dict[str, Any]] = Field(
        default_factory=list
    )  # [{"regime": "EU_AI_ACT", "article": "12", "status": "SUPPORTED_FOR_DEPLOYER", "description": "..."}]
    systemic_risk_tags: List[str] = Field(
        default_factory=list
    )  # ["SYNTHETIC_CONTENT", "IDENTITY_FRAUD", "CROSS_TENANT_REUSE"]


class RiskImpactAnalysis(BaseModel):
    """Risk impact analysis with counterfactuals."""

    risk_band: str  # LOW, MEDIUM, HIGH, CRITICAL
    false_positive_risk: str = "UNKNOWN"  # LOW, MEDIUM, HIGH
    false_negative_risk: str = "UNKNOWN"  # LOW, MEDIUM, HIGH
    expected_harm_if_misclassified: Optional[str] = None
    counterfactuals: List[Dict[str, Any]] = Field(
        default_factory=list
    )  # [{"scenario": "risk_score -10", "decision": "ALLOW", "rationale": "..."}]


class IdentityHistoryContext(BaseModel):
    """Identity and historical consistency context."""

    identity_confidence: Optional[float] = None
    shared_device_count: Optional[int] = None
    relationship_count: Optional[int] = None
    prior_quarantine_count: Optional[int] = None
    cross_tenant_signals: Optional[Dict[str, Any]] = None
    historical_consistency: Optional[Dict[str, Any]] = None  # {"last_90_days": {"ALLOW": 5, "REVIEW": 2, ...}}


class GovernanceContext(BaseModel):
    """Governance and accountability context."""

    policy_profile_id: Optional[int] = None
    policy_name: Optional[str] = None
    policy_last_updated_at: Optional[datetime] = None
    policy_owner: Optional[str] = None
    human_oversight: Dict[str, Any] = Field(
        default_factory=lambda: {
            "required": False,
            "recommended_role": "content_moderator",
        }
    )


class TechnicalTraceContext(BaseModel):
    """Technical trace and ledger context."""

    ledger_event: Dict[str, Any] = Field(
        default_factory=dict
    )  # event_hash, previous_event_hash, event_type, timestamp
    certificate_data: Dict[str, Any] = Field(
        default_factory=dict
    )  # inputs_hash, outputs_hash, signature, algorithm, key_fingerprint
    verification_guidance: Optional[str] = None  # Example commands for verification


class AuditMetadata(BaseModel):
    """Audit metadata for evidence pack generation."""

    generated_at: datetime
    generated_by_version: str = "origin-api@unknown"
    audience: EvidenceAudience = EvidenceAudience.INTERNAL
    redactions: List[RedactionRecord] = Field(default_factory=list)

    @field_validator("generated_at")
    @classmethod
    def ensure_timezone_aware(cls, v: datetime) -> datetime:
        """Ensure datetime is timezone-aware (UTC)."""
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


# ============================================================================
# Top-Level EvidencePackV2 Model
# ============================================================================


class EvidencePackV2(BaseModel):
    """Evidence Pack v2 (Decision Dossier) schema.

    This schema represents a regulator-grade decision dossier aligned with:
    - EU AI Act Art. 12-13: Logging and transparency for high-risk AI systems
    - DSA Art. 14-15: Systemic risk assessment and transparency obligations

    The schema is designed to support comprehensive audit trails and regulatory
    compliance while maintaining backward compatibility with existing evidence
    pack structures.

    Top-level fields are required, but nested fields may be optional to support
    gradual migration from v1 evidence packs.
    """

    version: Literal["origin-evidence-v2"] = "origin-evidence-v2"
    tenant: TenantContext
    certificate: CertificateContext
    upload: UploadContext
    decision_summary: DecisionSummary
    ml_and_signals: MLSignalsContext
    regulatory_profile: RegulatoryProfile
    risk_impact_analysis: RiskImpactAnalysis
    identity_and_history: IdentityHistoryContext
    governance_and_accountability: GovernanceContext
    technical_trace_and_ledger: TechnicalTraceContext
    audit_metadata: AuditMetadata

    class Config:
        """Pydantic config."""

        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
        # Allow extra fields for backward compatibility only
        extra = "ignore"
        use_enum_values = True  # Serialize enums as their values

