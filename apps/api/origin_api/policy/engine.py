"""Policy engine for deterministic decision making."""

from typing import Optional

from sqlalchemy.orm import Session

from origin_api.models import PolicyProfile


class PolicyEngine:
    """Deterministic policy evaluation engine."""

    def __init__(self, db: Session):
        """Initialize policy engine."""
        self.db = db

    def get_policy_profile(self, tenant_id: int) -> PolicyProfile:
        """Get active policy profile for tenant."""
        tenant = self.db.query(PolicyProfile).filter(
            PolicyProfile.tenant_id == tenant_id,
            PolicyProfile.is_active == True,  # noqa: E712
        ).first()

        if not tenant:
            # Fallback to global default
            tenant = (
                self.db.query(PolicyProfile)
                .filter(
                    PolicyProfile.tenant_id.is_(None),
                    PolicyProfile.is_active == True,  # noqa: E712
                )
                .first()
            )

        # If still no policy, create a default
        if not tenant:
            tenant = PolicyProfile(
                tenant_id=None,
                name="default",
                version="ORIGIN-CORE-v1.0",
                thresholds_json={
                    "risk_threshold_review": 40,
                    "risk_threshold_quarantine": 70,
                    "risk_threshold_reject": 90,
                    "assurance_threshold_allow": 80,
                    "anomaly_threshold": 30,
                    "synthetic_threshold": 70,
                },
                weights_json={},
                is_active=True,
            )
            self.db.add(tenant)
            self.db.flush()

        return tenant

    def evaluate_decision(
        self,
        tenant_id: int,
        risk_score: float,
        assurance_score: float,
        anomaly_score: float,
        synthetic_likelihood: float,
        has_prior_quarantine: bool,
        has_prior_reject: bool,
        prior_sightings_count: int,
        identity_confidence: float,
    ) -> dict:
        """
        Evaluate policy and return decision.
        
        Decision logic:
        - risk_score: 0-100, higher = more risky
        - anomaly_score: 0-100, lower = more anomalous (trained on normal/ALLOW data)
        - synthetic_likelihood: 0-100, higher = more likely synthetic/AI-generated
        - identity_confidence: 0-100, higher = more established identity
        
        Thresholds (configurable via PolicyProfile):
        - risk_threshold_reject: ~90 (default)
        - risk_threshold_quarantine: ~70 (default)
        - risk_threshold_review: ~40 (default)
        - anomaly_threshold: ~30 (default, lower = more anomalous)
        - synthetic_threshold: ~70 (default)
        """
        policy = self.get_policy_profile(tenant_id)
        thresholds = policy.thresholds_json or {}

        triggered_rules = []
        reason_codes = []

        # Hard blocks (highest priority)
        if has_prior_reject:
            triggered_rules.append("HARD_BLOCK_PRIOR_REJECT")
            reason_codes.append("PRIOR_REJECT")
            return {
                "decision": "REJECT",
                "policy_version": policy.version,
                "triggered_rules": triggered_rules,
                "reason_codes": reason_codes,
                "rationale": "Content was previously rejected",
            }

        if has_prior_quarantine:
            triggered_rules.append("HARD_BLOCK_PRIOR_QUARANTINE")
            reason_codes.append("PRIOR_QUARANTINE")
            return {
                "decision": "QUARANTINE",
                "policy_version": policy.version,
                "triggered_rules": triggered_rules,
                "reason_codes": reason_codes,
                "rationale": "Content was previously quarantined",
            }

        # Risk-based decisions
        risk_threshold_reject = thresholds.get("risk_threshold_reject", 90)
        risk_threshold_quarantine = thresholds.get("risk_threshold_quarantine", 70)
        risk_threshold_review = thresholds.get("risk_threshold_review", 40)
        anomaly_threshold = thresholds.get("anomaly_threshold", 30)
        synthetic_threshold = thresholds.get("synthetic_threshold", 70)

        # REJECT: Very high risk
        if risk_score >= risk_threshold_reject:
            triggered_rules.append("RISK_THRESHOLD_REJECT")
            reason_codes.append("RISK_SCORE_HIGH")
            return {
                "decision": "REJECT",
                "policy_version": policy.version,
                "triggered_rules": triggered_rules,
                "reason_codes": reason_codes,
                "rationale": f"Risk score {risk_score:.1f} exceeds reject threshold {risk_threshold_reject}",
            }

        # QUARANTINE: High risk
        if risk_score >= risk_threshold_quarantine:
            triggered_rules.append("RISK_THRESHOLD_QUARANTINE")
            reason_codes.append("RISK_SCORE_HIGH")
            return {
                "decision": "QUARANTINE",
                "policy_version": policy.version,
                "triggered_rules": triggered_rules,
                "reason_codes": reason_codes,
                "rationale": f"Risk score {risk_score:.1f} exceeds quarantine threshold {risk_threshold_quarantine}",
            }

        # Refine with anomaly and synthetic signals
        # Escalate moderate risk if anomaly is very high
        if risk_score < risk_threshold_quarantine and anomaly_score < (anomaly_threshold / 2):
            triggered_rules.append("ANOMALY_HIGH_RISK")
            reason_codes.append("ANOMALY_HIGH_RISK")
            return {
                "decision": "QUARANTINE",
                "policy_version": policy.version,
                "triggered_rules": triggered_rules,
                "reason_codes": reason_codes,
                "rationale": f"Moderate risk ({risk_score:.1f}) but extremely anomalous pattern (anomaly: {anomaly_score:.1f})",
            }

        # Escalate if synthetic + low identity + first seen
        if (
            synthetic_likelihood >= synthetic_threshold
            and identity_confidence < 40
            and prior_sightings_count == 0
        ):
            triggered_rules.append("SYNTHETIC_LIKELY_FIRST_SEEN")
            reason_codes.append("SYNTHETIC_LIKELY_FIRST_SEEN")
            return {
                "decision": "QUARANTINE",
                "policy_version": policy.version,
                "triggered_rules": triggered_rules,
                "reason_codes": reason_codes,
                "rationale": f"Synthetic content likely (score: {synthetic_likelihood:.1f}) with low identity confidence ({identity_confidence:.1f}) and no prior sightings",
            }

        # Assurance-based allow
        assurance_threshold_allow = thresholds.get("assurance_threshold_allow", 80)
        if assurance_score >= assurance_threshold_allow and risk_score < risk_threshold_review:
            triggered_rules.append("ASSURANCE_THRESHOLD_ALLOW")
            reason_codes.append("HIGH_ASSURANCE")
            return {
                "decision": "ALLOW",
                "policy_version": policy.version,
                "triggered_rules": triggered_rules,
                "reason_codes": reason_codes,
                "rationale": f"Assurance score {assurance_score:.1f} meets allow threshold with low risk",
            }

        # Identity confidence checks
        if identity_confidence < 30:
            triggered_rules.append("LOW_IDENTITY_CONFIDENCE")
            reason_codes.append("NEW_IDENTITY")
            return {
                "decision": "REVIEW",
                "policy_version": policy.version,
                "triggered_rules": triggered_rules,
                "reason_codes": reason_codes,
                "rationale": f"Low identity confidence {identity_confidence:.1f} requires review",
            }

        # Anomaly checks (moderate anomaly)
        if anomaly_score < anomaly_threshold:
            triggered_rules.append("HIGH_ANOMALY")
            reason_codes.append("ANOMALOUS_PATTERN")
            return {
                "decision": "REVIEW",
                "policy_version": policy.version,
                "triggered_rules": triggered_rules,
                "reason_codes": reason_codes,
                "rationale": f"Anomaly score {anomaly_score:.1f} indicates unusual pattern",
            }

        # Synthetic/AI disclosure (moderate synthetic likelihood)
        if synthetic_likelihood >= synthetic_threshold:
            triggered_rules.append("SYNTHETIC_LIKELIHOOD")
            reason_codes.append("AI_DISCLOSURE_REQUIRED")
            return {
                "decision": "REVIEW",
                "policy_version": policy.version,
                "triggered_rules": triggered_rules,
                "reason_codes": reason_codes,
                "rationale": f"Synthetic likelihood {synthetic_likelihood:.1f} requires AI disclosure review",
            }

        # Default: REVIEW for anything that doesn't meet clear criteria
        triggered_rules.append("DEFAULT_REVIEW")
        reason_codes.append("REQUIRES_MANUAL_REVIEW")
        return {
            "decision": "REVIEW",
            "policy_version": policy.version,
            "triggered_rules": triggered_rules,
            "reason_codes": reason_codes,
            "rationale": "Content requires manual review",
        }

