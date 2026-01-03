"""Policy engine for deterministic decision making."""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from origin_api.models import PolicyProfile
from origin_api.policy.decision_mode import DecisionMode

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
                regulatory_compliance_json={
                    "DSA": {
                        "article_14": "Content moderation obligations - risk_score thresholds map to moderation tiers",
                        "article_15": "Transparency reporting - decision_rationale provides audit trail",
                        "article_16": "Risk assessment - risk_score, anomaly_score, synthetic_likelihood inform assessment",
                        "mapped_thresholds": {
                            "risk_threshold_reject": "Article 14 - Immediate removal threshold",
                            "risk_threshold_quarantine": "Article 14 - Restriction threshold",
                            "risk_threshold_review": "Article 16 - Risk assessment trigger",
                        }
                    },
                    "OSA": {
                        "section_9": "Duty to assess risk - risk_score and assurance_score inform risk assessment",
                        "section_10": "Duty to prevent harm - QUARANTINE/REJECT decisions prevent harmful content",
                        "section_19": "Transparency reporting - evidence packs provide decision audit trail",
                        "mapped_thresholds": {
                            "risk_threshold_reject": "Section 10 - Harmful content removal",
                            "synthetic_threshold": "Section 9 - AI-generated content detection",
                            "anomaly_threshold": "Section 9 - Anomalous behavior detection",
                        }
                    },
                    "AI_Act": {
                        "article_50": "Transparency obligations - synthetic_likelihood detects AI-generated content",
                        "article_52": "High-risk AI systems - risk_score thresholds identify high-risk content",
                        "mapped_thresholds": {
                            "synthetic_threshold": "Article 50 - AI content disclosure threshold",
                            "risk_threshold_quarantine": "Article 52 - High-risk content identification",
                        }
                    }
                },
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
        decision_mode_str = getattr(policy, "decision_mode", None) or "score_first"
        
        # Normalize decision mode to enum
        try:
            decision_mode = DecisionMode(decision_mode_str)
        except ValueError:
            decision_mode = DecisionMode.SCORE_FIRST
            logger.warning(f"Unknown decision_mode '{decision_mode_str}', defaulting to SCORE_FIRST")

        triggered_rules: list[str] = []
        reason_codes: list[str] = []
        decision_drivers: list[str] = []  # Top contributors to decision
        counterfactual: Optional[str] = None

        # Thresholds
        risk_threshold_reject = thresholds.get("risk_threshold_reject", 90)
        risk_threshold_quarantine = thresholds.get("risk_threshold_quarantine", 70)
        risk_threshold_review = thresholds.get("risk_threshold_review", 40)
        anomaly_threshold = thresholds.get("anomaly_threshold", 30)
        synthetic_threshold = thresholds.get("synthetic_threshold", 70)
        assurance_threshold_allow = thresholds.get("assurance_threshold_allow", 80)

        # Baseline decision
        baseline_decision: Optional[str] = None
        
        if decision_mode == DecisionMode.LABEL_FIRST and primary_label:
            baseline_decision = primary_label
            decision = primary_label
            triggered_rules.append("MODEL_PRIMARY_LABEL")
            reason_codes.append(f"MODEL_PRIMARY_LABEL_{primary_label}")
            decision_drivers.append(f"Model primary label: {primary_label} (probability: {class_probabilities.get(primary_label, 0):.1%})")
        else:
            # Score-first baseline using risk bands
            if risk_score >= risk_threshold_reject:
                baseline_decision = "REJECT"
                decision = "REJECT"
                triggered_rules.append("RISK_THRESHOLD_REJECT")
                reason_codes.append("RISK_SCORE_HIGH")
                decision_drivers.append(f"Risk score {risk_score:.1f} ≥ reject threshold {risk_threshold_reject}")
                # Counterfactual: what would flip to QUARANTINE?
                score_diff = risk_score - risk_threshold_reject
                counterfactual = f"If risk score were {score_diff:.1f} points lower (from {risk_score:.1f} to {risk_threshold_reject:.1f}), decision would be QUARANTINE under current thresholds"
            elif risk_score >= risk_threshold_quarantine:
                baseline_decision = "QUARANTINE"
                decision = "QUARANTINE"
                triggered_rules.append("RISK_THRESHOLD_QUARANTINE")
                reason_codes.append("RISK_SCORE_HIGH")
                decision_drivers.append(f"Risk score {risk_score:.1f} ≥ quarantine threshold {risk_threshold_quarantine}")
                # Counterfactual: what would flip to REVIEW?
                score_diff = risk_score - risk_threshold_quarantine
                counterfactual = f"If risk score were {score_diff:.1f} points lower (from {risk_score:.1f} to {risk_threshold_quarantine:.1f}), decision would be REVIEW under current thresholds"
            elif risk_score >= risk_threshold_review:
                baseline_decision = "REVIEW"
                decision = "REVIEW"
                triggered_rules.append("RISK_THRESHOLD_REVIEW")
                reason_codes.append("RISK_SCORE_MODERATE")
                decision_drivers.append(f"Risk score {risk_score:.1f} is between review threshold {risk_threshold_review} and quarantine threshold {risk_threshold_quarantine}")
                # Counterfactual: what would flip to ALLOW?
                score_diff = risk_threshold_review - risk_score
                if score_diff > 0:
                    counterfactual = f"If risk score were {score_diff:.1f} points lower (from {risk_score:.1f} to {risk_threshold_review - 0.1:.1f}), decision would be ALLOW under current thresholds"
                else:
                    counterfactual = f"If risk score were {risk_threshold_quarantine - risk_score:.1f} points higher (from {risk_score:.1f} to {risk_threshold_quarantine:.1f}), decision would be QUARANTINE under current thresholds"
            else:
                # Low risk band - check if signals are clean enough for ALLOW
                if (
                    anomaly_score >= anomaly_threshold
                    and synthetic_likelihood < synthetic_threshold
                    and identity_confidence >= 40
                    and prior_sightings_count >= 1
                ):
                    baseline_decision = "ALLOW"
                    decision = "ALLOW"
                    triggered_rules.append("LOW_RISK_PROFILE")
                    reason_codes.append("LOW_RISK_NO_SIGNALS")
                    decision_drivers.append(f"Risk score {risk_score:.1f} < review threshold {risk_threshold_review}")
                    decision_drivers.append(f"Clean signals: anomaly_score={anomaly_score:.1f} (≥{anomaly_threshold}), synthetic_likelihood={synthetic_likelihood:.1f} (<{synthetic_threshold})")
                    decision_drivers.append(f"Established identity: confidence={identity_confidence:.1f}%, prior_sightings={prior_sightings_count}")
                    # Counterfactual: what would flip to REVIEW?
                    counterfactual = f"If risk score were {risk_threshold_review - risk_score:.1f} points higher (from {risk_score:.1f} to {risk_threshold_review:.1f}), decision would be REVIEW under current thresholds"
                else:
                    baseline_decision = "REVIEW"
                    decision = "REVIEW"
                    triggered_rules.append("DEFAULT_REVIEW_BASELINE")
                    reason_codes.append("REQUIRES_MANUAL_REVIEW")
                    missing_criteria = []
                    if anomaly_score < anomaly_threshold:
                        missing_criteria.append(f"anomaly_score {anomaly_score:.1f} < threshold {anomaly_threshold}")
                    if synthetic_likelihood >= synthetic_threshold:
                        missing_criteria.append(f"synthetic_likelihood {synthetic_likelihood:.1f} ≥ threshold {synthetic_threshold}")
                    if identity_confidence < 40:
                        missing_criteria.append(f"identity_confidence {identity_confidence:.1f}% < 40%")
                    if prior_sightings_count < 1:
                        missing_criteria.append(f"prior_sightings {prior_sightings_count} < 1")
                    decision_drivers.append(f"Low risk ({risk_score:.1f} < {risk_threshold_review}) but missing clean-signal criteria: {', '.join(missing_criteria)}")
                    counterfactual = f"If signals were cleaner (anomaly_score≥{anomaly_threshold}, synthetic<{synthetic_threshold}, identity≥40%, prior_sightings≥1), decision would be ALLOW under current thresholds"

        # Guardrails (apply to both modes)
        guardrail_applied = False
        original_decision = decision

        # Prior rejects/quarantines
        if has_prior_reject:
            if decision != "REJECT":
                guardrail_applied = True
                decision_drivers.insert(0, f"GUARDRAIL: Prior reject history (escalated {original_decision} → REJECT)")
            decision = "REJECT"
            triggered_rules.append("GUARDRAIL_PRIOR_REJECT")
            reason_codes.append("PRIOR_REJECT_HISTORY")

        if has_prior_quarantine and decision in ("ALLOW", "REVIEW"):
            guardrail_applied = True
            decision_drivers.insert(0, f"GUARDRAIL: Prior quarantine history (escalated {decision} → QUARANTINE)")
            decision = "QUARANTINE"
            triggered_rules.append("GUARDRAIL_PRIOR_QUARANTINE")
            reason_codes.append("PRIOR_QUARANTINE_HISTORY")

        # Anomaly guardrail (lower = more anomalous)
        if anomaly_score < anomaly_threshold and decision == "ALLOW":
            guardrail_applied = True
            decision_drivers.insert(0, f"GUARDRAIL: Anomaly detected (anomaly_score {anomaly_score:.1f} < threshold {anomaly_threshold}, escalated ALLOW → REVIEW)")
            decision = "REVIEW"
            triggered_rules.append("GUARDRAIL_ANOMALY_ESCALATION")
            reason_codes.append("ANOMALY_HIGH_RISK")

        # Synthetic guardrail (higher = more synthetic)
        if synthetic_likelihood >= synthetic_threshold and decision in ("ALLOW", "REVIEW"):
            guardrail_applied = True
            decision_drivers.insert(0, f"GUARDRAIL: Synthetic content likely (synthetic_likelihood {synthetic_likelihood:.1f} ≥ threshold {synthetic_threshold}, escalated {decision} → QUARANTINE)")
            decision = "QUARANTINE"
            triggered_rules.append("GUARDRAIL_SYNTHETIC_ESCALATION")
            reason_codes.append("SYNTHETIC_LIKELY_FIRST_SEEN")

        # Extreme risk guardrails
        if risk_score >= risk_threshold_reject and decision != "REJECT":
            guardrail_applied = True
            decision_drivers.insert(0, f"GUARDRAIL: Extreme risk (risk_score {risk_score:.1f} ≥ reject threshold {risk_threshold_reject}, escalated {decision} → REJECT)")
            decision = "REJECT"
            triggered_rules.append("GUARDRAIL_RISK_REJECT")
            reason_codes.append("RISK_SCORE_HIGH")
        elif risk_score >= risk_threshold_quarantine and decision in ("ALLOW", "REVIEW"):
            guardrail_applied = True
            decision_drivers.insert(0, f"GUARDRAIL: High risk (risk_score {risk_score:.1f} ≥ quarantine threshold {risk_threshold_quarantine}, escalated {decision} → QUARANTINE)")
            decision = "QUARANTINE"
            triggered_rules.append("GUARDRAIL_RISK_QUARANTINE")
            reason_codes.append("RISK_SCORE_HIGH")

        # Assurance-based allow (only if still REVIEW and low risk)
        if decision == "REVIEW" and assurance_score >= assurance_threshold_allow and risk_score < risk_threshold_review:
            guardrail_applied = True
            decision_drivers.append(f"GUARDRAIL: High assurance (assurance_score {assurance_score:.1f} ≥ threshold {assurance_threshold_allow}, escalated REVIEW → ALLOW)")
            decision = "ALLOW"
            triggered_rules.append("ASSURANCE_THRESHOLD_ALLOW")
            reason_codes.append("HIGH_ASSURANCE")

        # Build final rationale with structure
        # 1. Decision mode and thresholds used
        mode_desc = decision_mode.value.replace("_", " ").title()
        rationale_parts = [
            f"Decision: {decision} (mode: {mode_desc})",
            f"Thresholds: review={risk_threshold_review}, quarantine={risk_threshold_quarantine}, reject={risk_threshold_reject}, "
            f"assurance_allow={assurance_threshold_allow}, anomaly={anomaly_threshold}, synthetic={synthetic_threshold}",
        ]
        
        # 2. Primary drivers (top 3)
        if decision_drivers:
            top_drivers = decision_drivers[:3]
            rationale_parts.append(f"Primary drivers: {'; '.join(top_drivers)}")
        
        # 3. Counterfactual (if available)
        if counterfactual:
            rationale_parts.append(f"Counterfactual: {counterfactual}")
        
        # 4. Guardrail note (if applied)
        if guardrail_applied and original_decision != decision:
            rationale_parts.append(f"Note: Guardrails modified decision from {original_decision} to {decision}")

        final_rationale = ". ".join(rationale_parts) + "."

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

