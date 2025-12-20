"""Tests for ML inference service."""

import numpy as np
import pytest
from sklearn.preprocessing import LabelEncoder
from unittest.mock import Mock, patch

from origin_api.ml.inference import MLInferenceService


class TestMLInferenceService:
    """Test ML inference service risk score mapping."""

    def test_risk_score_mapping_with_label_encoder(self):
        """Test that risk_score is computed correctly using label encoder."""
        # Create label encoder first to get actual class order
        label_encoder = LabelEncoder()
        label_encoder.fit(["ALLOW", "REVIEW", "QUARANTINE", "REJECT"])
        # LabelEncoder sorts alphabetically: ALLOW=0, QUARANTINE=1, REJECT=2, REVIEW=3
        classes = label_encoder.classes_  # ['ALLOW', 'QUARANTINE', 'REJECT', 'REVIEW']
        
        # Create mock model with predict_proba matching the encoder order
        mock_model = Mock()
        mock_model.classes_ = np.array([0, 1, 2, 3])  # Encoded classes in alphabetical order
        # High probability on ALLOW (index 0)
        mock_model.predict_proba = Mock(return_value=np.array([[0.8, 0.1, 0.05, 0.05]]))

        # Create service instance
        service = MLInferenceService(model_dir="ml/models")
        service.risk_model = mock_model
        service.risk_label_encoder = label_encoder

        # Compute risk signals
        result = service.compute_risk_signals(
            account_age_days=100,
            shared_device_count=2,
            prior_quarantine_count=0,
            identity_confidence=80.0,
            upload_velocity=5,
            prior_sightings_count=1,
        )

        # With high ALLOW probability, risk_score should be low
        assert result["risk_score"] < 20, "High ALLOW probability should yield low risk score"

    def test_risk_score_mapping_reject_high(self):
        """Test that high REJECT probability yields high risk_score."""
        # Create label encoder first to get actual class order
        label_encoder = LabelEncoder()
        label_encoder.fit(["ALLOW", "REVIEW", "QUARANTINE", "REJECT"])
        # LabelEncoder sorts: ALLOW=0, QUARANTINE=1, REJECT=2, REVIEW=3
        
        # Create mock model
        mock_model = Mock()
        mock_model.classes_ = np.array([0, 1, 2, 3])
        # High REJECT probability (REJECT is at index 2 in alphabetical order)
        mock_model.predict_proba = Mock(return_value=np.array([[0.05, 0.05, 0.85, 0.05]]))

        # Create label encoder
        label_encoder = LabelEncoder()
        label_encoder.fit(["ALLOW", "REVIEW", "QUARANTINE", "REJECT"])

        service = MLInferenceService(model_dir="ml/models")
        service.risk_model = mock_model
        service.risk_label_encoder = label_encoder

        result = service.compute_risk_signals(
            account_age_days=10,
            shared_device_count=10,
            prior_quarantine_count=2,
            identity_confidence=20.0,
            upload_velocity=100,
            prior_sightings_count=0,
        )

        # With high REJECT probability, risk_score should be close to 90
        assert result["risk_score"] > 80, "High REJECT probability should yield high risk score (close to 90)"

    def test_risk_score_fallback_on_missing_model(self):
        """Test that fallback logic works when model is missing."""
        service = MLInferenceService(model_dir="ml/models")
        service.risk_model = None
        service.risk_label_encoder = None

        result = service.compute_risk_signals(
            account_age_days=10,
            shared_device_count=0,
            prior_quarantine_count=0,
            identity_confidence=50.0,
            upload_velocity=1,
            prior_sightings_count=0,
        )

        # Should return a valid risk_score from fallback
        assert 0 <= result["risk_score"] <= 100
        assert "assurance_score" in result
        assert "anomaly_score" in result
        assert "synthetic_likelihood" in result

