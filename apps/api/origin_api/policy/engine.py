"""Policy engine for deterministic decision making."""

import logging

from sqlalchemy.orm import Session

from origin_api.models import PolicyProfile

logger = logging.getLogger(__name__)


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
                decision_mode="score_first",
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
        primary_label: str | None = None,
        class_probabilities: dict | None = None,
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
        logger.debug(
            "Policy evaluation start",
            extra={
                "tenant_id": tenant_id,
                "risk_score": risk_score,
                "assurance_score": assurance_score,
                "anomaly_score": anomaly_score,
                "synthetic_likelihood": synthetic_likelihood,
                "prior_sightings_count": prior_sightings_count,
                "identity_confidence": identity_confidence,
            },
        )
        def _log_and_return(payload: dict) -> dict:
            logger.debug(
                "Policy evaluation result",
                extra={
                    "decision": payload.get("decision"),
                    "triggered_rules": payload.get("triggered_rules"),
                    "reason_codes": payload.get("reason_codes"),
                },
            )
            return payload
        policy = self.get_policy_profile(tenant_id)
        thresholds = policy.thresholds_json or {}
        decision_mode = getattr(policy, "decision_mode", None) or "score_first"

        triggered_rules: list[str] = []
        reason_codes: list[str] = []
        rationale_parts: list[str] = []

        # Thresholds
        risk_threshold_reject = thresholds.get("risk_threshold_reject", 90)
        risk_threshold_quarantine = thresholds.get("risk_threshold_quarantine", 70)
        risk_threshold_review = thresholds.get("risk_threshold_review", 40)
        anomaly_threshold = thresholds.get("anomaly_threshold", 30)
        synthetic_threshold = thresholds.get("synthetic_threshold", 70)
        assurance_threshold_allow = thresholds.get("assurance_threshold_allow", 80)

        # Baseline decision
        if decision_mode == "label_first" and primary_label:
            decision = primary_label
            triggered_rules.append("MODEL_PRIMARY_LABEL")
            reason_codes.append(f"MODEL_PRIMARY_LABEL_{primary_label}")
            rationale_parts.append(
                f"Model primary label {primary_label} with risk_score={risk_score:.1f}, assurance_score={assurance_score:.1f}"
            )
        else:
            # score_first baseline using risk bands
            rationale_parts.append("score_first baseline using risk thresholds")
            if risk_score >= risk_threshold_reject:
                decision = "REJECT"
                triggered_rules.append("RISK_THRESHOLD_REJECT")
                reason_codes.append("RISK_SCORE_HIGH")
                rationale_parts.append(
                    f"Risk score {risk_score:.1f} exceeds reject threshold {risk_threshold_reject}"
                )
            elif risk_score >= risk_threshold_quarantine:
                decision = "QUARANTINE"
                triggered_rules.append("RISK_THRESHOLD_QUARANTINE")
                reason_codes.append("RISK_SCORE_HIGH")
                rationale_parts.append(
                    f"Risk score {risk_score:.1f} exceeds quarantine threshold {risk_threshold_quarantine}"
                )
            elif risk_score >= risk_threshold_review:
                decision = "REVIEW"
                triggered_rules.append("RISK_THRESHOLD_REVIEW")
                reason_codes.append("RISK_SCORE_MODERATE")
                rationale_parts.append(
                    f"Moderate risk between review {risk_threshold_review} and quarantine {risk_threshold_quarantine}"
                )
            else:
                # Low risk band allow if signals are clean
                if (
                    anomaly_score >= anomaly_threshold
                    and synthetic_likelihood < synthetic_threshold
                    and identity_confidence >= 40
                    and prior_sightings_count >= 1
                ):
                    decision = "ALLOW"
                    triggered_rules.append("LOW_RISK_PROFILE")
                    reason_codes.append("LOW_RISK_NO_SIGNALS")
                    rationale_parts.append(
                        f"Low risk profile: risk={risk_score:.1f} < review {risk_threshold_review}, clean anomaly/synthetic, identity_confidence={identity_confidence:.1f}, prior_sightings={prior_sightings_count}"
                    )
                else:
                    decision = "REVIEW"
                    triggered_rules.append("DEFAULT_REVIEW_BASELINE")
                    reason_codes.append("REQUIRES_MANUAL_REVIEW")
                    rationale_parts.append("Low risk but missing clean-signal criteria, defaulting to REVIEW baseline")

        # Guardrails (apply to both modes)
        guardrail_notes: list[str] = []

        # Prior rejects/quarantines
        if has_prior_reject:
            if decision != "REJECT":
                guardrail_notes.append("Escalated due to prior reject history")
            decision = "REJECT"
            triggered_rules.append("GUARDRAIL_PRIOR_REJECT")
            reason_codes.append("PRIOR_REJECT_HISTORY")

        if has_prior_quarantine and decision in ("ALLOW", "REVIEW"):
            decision = "QUARANTINE"
            triggered_rules.append("GUARDRAIL_PRIOR_QUARANTINE")
            reason_codes.append("PRIOR_QUARANTINE_HISTORY")
            guardrail_notes.append("Escalated due to prior quarantine history")

        # Anomaly guardrail (lower = more anomalous)
        if anomaly_score < anomaly_threshold and decision == "ALLOW":
            decision = "REVIEW"
            triggered_rules.append("GUARDRAIL_ANOMALY_ESCALATION")
            reason_codes.append("ANOMALY_HIGH_RISK")
            guardrail_notes.append("Escalated ALLOW -> REVIEW due to anomaly")

        # Synthetic guardrail (higher = more synthetic)
        if synthetic_likelihood >= synthetic_threshold and decision in ("ALLOW", "REVIEW"):
            decision = "QUARANTINE"
            triggered_rules.append("GUARDRAIL_SYNTHETIC_ESCALATION")
            reason_codes.append("SYNTHETIC_LIKELY_FIRST_SEEN")
            guardrail_notes.append("Escalated due to synthetic likelihood")

        # Extreme risk guardrails
        if risk_score >= risk_threshold_reject and decision != "REJECT":
            decision = "REJECT"
            triggered_rules.append("GUARDRAIL_RISK_REJECT")
            reason_codes.append("RISK_SCORE_HIGH")
            guardrail_notes.append("Escalated to REJECT due to extreme risk")
        elif risk_score >= risk_threshold_quarantine and decision in ("ALLOW", "REVIEW"):
            decision = "QUARANTINE"
            triggered_rules.append("GUARDRAIL_RISK_QUARANTINE")
            reason_codes.append("RISK_SCORE_HIGH")
            guardrail_notes.append("Escalated to QUARANTINE due to high risk")

        # Assurance-based allow (only if still REVIEW and low risk)
        if decision == "REVIEW" and assurance_score >= assurance_threshold_allow and risk_score < risk_threshold_review:
            decision = "ALLOW"
            triggered_rules.append("ASSURANCE_THRESHOLD_ALLOW")
            reason_codes.append("HIGH_ASSURANCE")
            guardrail_notes.append("Assurance high, allowing despite review baseline")

        rationale_tail = ""
        if guardrail_notes:
            rationale_tail = " Guardrails applied: " + "; ".join(guardrail_notes)

        final_rationale = (
            f"{'label_first' if decision_mode == 'label_first' and primary_label else 'score_first'} baseline. "
            + " ".join(rationale_parts)
            + rationale_tail
        )

        decision_payload = {
            "decision": decision,
            "policy_version": policy.version,
            "triggered_rules": triggered_rules,
            "reason_codes": reason_codes,
            "rationale": final_rationale,
            "risk_score": risk_score,
            "assurance_score": assurance_score,
        }
        return _log_and_return(decision_payload)

