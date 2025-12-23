"""Tests for policy engine decision logic."""

import pytest
from unittest.mock import Mock

from origin_api.policy.engine import PolicyEngine


class TestPolicyEngine:
    """Test policy engine decision evaluation."""

    def test_allow_decision_low_risk_high_assurance(self):
        """Test ALLOW decision for low risk, high assurance."""
        db = Mock()
        engine = PolicyEngine(db)

        # Mock policy profile
        mock_policy = Mock()
        mock_policy.version = "ORIGIN-CORE-v1.0"
        mock_policy.thresholds_json = {
            "risk_threshold_review": 40,
            "risk_threshold_quarantine": 70,
            "risk_threshold_reject": 90,
            "assurance_threshold_allow": 80,
        }
        engine.get_policy_profile = Mock(return_value=mock_policy)

        result = engine.evaluate_decision(
            tenant_id=1,
            risk_score=20.0,  # Low risk
            assurance_score=85.0,  # High assurance
            anomaly_score=60.0,
            synthetic_likelihood=30.0,
            has_prior_quarantine=False,
            has_prior_reject=False,
            prior_sightings_count=5,
            identity_confidence=80.0,
        )

        assert result["decision"] == "ALLOW"
        assert "HIGH_ASSURANCE" in result["reason_codes"]

    def test_review_decision_moderate_risk(self):
        """Test REVIEW decision for moderate risk above review threshold."""
        db = Mock()
        engine = PolicyEngine(db)

        mock_policy = Mock()
        mock_policy.version = "ORIGIN-CORE-v1.0"
        mock_policy.thresholds_json = {
            "risk_threshold_review": 40,
            "risk_threshold_quarantine": 70,
            "risk_threshold_reject": 90,
        }
        engine.get_policy_profile = Mock(return_value=mock_policy)

        result = engine.evaluate_decision(
            tenant_id=1,
            risk_score=50.0,  # Moderate risk, above review threshold
            assurance_score=60.0,
            anomaly_score=50.0,
            synthetic_likelihood=40.0,
            has_prior_quarantine=False,
            has_prior_reject=False,
            prior_sightings_count=2,
            identity_confidence=50.0,
        )

        assert result["decision"] == "REVIEW"

    def test_quarantine_decision_high_risk(self):
        """Test QUARANTINE decision for high risk above quarantine threshold."""
        db = Mock()
        engine = PolicyEngine(db)

        mock_policy = Mock()
        mock_policy.version = "ORIGIN-CORE-v1.0"
        mock_policy.thresholds_json = {
            "risk_threshold_review": 40,
            "risk_threshold_quarantine": 70,
            "risk_threshold_reject": 90,
        }
        engine.get_policy_profile = Mock(return_value=mock_policy)

        result = engine.evaluate_decision(
            tenant_id=1,
            risk_score=75.0,  # High risk, above quarantine threshold
            assurance_score=40.0,
            anomaly_score=50.0,
            synthetic_likelihood=50.0,
            has_prior_quarantine=False,
            has_prior_reject=False,
            prior_sightings_count=1,
            identity_confidence=40.0,
        )

        assert result["decision"] == "QUARANTINE"
        assert "RISK_SCORE_HIGH" in result["reason_codes"]

    def test_reject_decision_very_high_risk(self):
        """Test REJECT decision for very high risk above reject threshold."""
        db = Mock()
        engine = PolicyEngine(db)

        mock_policy = Mock()
        mock_policy.version = "ORIGIN-CORE-v1.0"
        mock_policy.thresholds_json = {
            "risk_threshold_review": 40,
            "risk_threshold_quarantine": 70,
            "risk_threshold_reject": 90,
        }
        engine.get_policy_profile = Mock(return_value=mock_policy)

        result = engine.evaluate_decision(
            tenant_id=1,
            risk_score=95.0,  # Very high risk, above reject threshold
            assurance_score=20.0,
            anomaly_score=30.0,
            synthetic_likelihood=80.0,
            has_prior_quarantine=False,
            has_prior_reject=False,
            prior_sightings_count=0,
            identity_confidence=20.0,
        )

        assert result["decision"] == "REJECT"
        assert "RISK_SCORE_HIGH" in result["reason_codes"]

    def test_quarantine_decision_anomaly_escalation(self):
        """Test QUARANTINE decision when moderate risk but extremely high anomaly."""
        db = Mock()
        engine = PolicyEngine(db)

        mock_policy = Mock()
        mock_policy.version = "ORIGIN-CORE-v1.0"
        mock_policy.thresholds_json = {
            "risk_threshold_review": 40,
            "risk_threshold_quarantine": 70,
            "risk_threshold_reject": 90,
            "anomaly_threshold": 30,
        }
        engine.get_policy_profile = Mock(return_value=mock_policy)

        result = engine.evaluate_decision(
            tenant_id=1,
            risk_score=50.0,  # Moderate risk, below quarantine threshold
            assurance_score=50.0,
            anomaly_score=10.0,  # Extremely low anomaly (very anomalous)
            synthetic_likelihood=40.0,
            has_prior_quarantine=False,
            has_prior_reject=False,
            prior_sightings_count=1,
            identity_confidence=50.0,
        )

        assert result["decision"] == "QUARANTINE"
        assert "ANOMALY_HIGH_RISK" in result["reason_codes"]

    def test_quarantine_decision_synthetic_first_seen(self):
        """Test QUARANTINE decision for synthetic content with low identity and no prior sightings."""
        db = Mock()
        engine = PolicyEngine(db)

        mock_policy = Mock()
        mock_policy.version = "ORIGIN-CORE-v1.0"
        mock_policy.thresholds_json = {
            "risk_threshold_review": 40,
            "risk_threshold_quarantine": 70,
            "risk_threshold_reject": 90,
            "synthetic_threshold": 70,
        }
        engine.get_policy_profile = Mock(return_value=mock_policy)

        result = engine.evaluate_decision(
            tenant_id=1,
            risk_score=45.0,  # Moderate risk
            assurance_score=50.0,
            anomaly_score=50.0,
            synthetic_likelihood=75.0,  # High synthetic likelihood
            has_prior_quarantine=False,
            has_prior_reject=False,
            prior_sightings_count=0,  # First seen
            identity_confidence=30.0,  # Low identity confidence
        )

        assert result["decision"] == "QUARANTINE"
        assert "SYNTHETIC_LIKELY_FIRST_SEEN" in result["reason_codes"]


