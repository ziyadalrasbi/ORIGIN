"""ML inference service for risk signals."""

import logging

import joblib
import numpy as np
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class MLInferenceService:
    """ML inference service for computing risk signals."""

    def __init__(self, model_dir: str = "ml/models"):
        """Initialize inference service."""
        self.model_dir = Path(model_dir)
        self.risk_model = None
        self.risk_label_encoder = None
        self.anomaly_model = None
        self._load_models()

    def _load_models(self):
        """Load trained models."""
        risk_model_path = self.model_dir / "risk_model.pkl"
        anomaly_model_path = self.model_dir / "anomaly_model.pkl"

        if risk_model_path.exists():
            try:
                artifact = joblib.load(risk_model_path)
                if isinstance(artifact, dict) and "model" in artifact and "label_encoder" in artifact:
                    self.risk_model = artifact["model"]
                    self.risk_label_encoder = artifact["label_encoder"]
                    logger.info("Risk model and label encoder loaded successfully")
                else:
                    # Backward compatibility: if old format, treat as model only
                    self.risk_model = artifact
                    self.risk_label_encoder = None
                    logger.warning("Risk model loaded without label encoder. Using fallback label mapping.")
            except Exception as e:
                logger.exception(f"Failed to load risk model from {risk_model_path}: {e}")
                self.risk_model = None
                self.risk_label_encoder = None
        else:
            logger.warning("Risk model not found. Using fallback heuristics.")

        if anomaly_model_path.exists():
            try:
                self.anomaly_model = joblib.load(anomaly_model_path)
                logger.info("Anomaly model loaded successfully")
            except Exception as e:
                logger.exception(f"Failed to load anomaly model from {anomaly_model_path}: {e}")
                self.anomaly_model = None
        else:
            logger.warning("Anomaly model not found. Using fallback heuristics.")

    def compute_risk_signals(
        self,
        account_age_days: int,
        shared_device_count: int,
        prior_quarantine_count: int,
        identity_confidence: float,
        upload_velocity: int,
        prior_sightings_count: int,
    ) -> dict:
        """
        Compute risk signals from features.
        
        Uses trained ML models to compute:
        - risk_score: 0-100, weighted average of decision class probabilities
        - assurance_score: 0-100, confidence that content is legitimate
        - anomaly_score: 0-100, lower = more anomalous (trained on ALLOW data)
        - synthetic_likelihood: 0-100, likelihood content is AI-generated
        
        Returns dict with all signal scores.
        """
        # Prepare feature vector
        features = np.array([[
            account_age_days,
            shared_device_count,
            prior_quarantine_count,
            identity_confidence,
            upload_velocity,
            prior_sightings_count,
        ]])

        # Risk score (0-100)
        if not self.risk_model or not self.risk_label_encoder:
            logger.warning("Risk model or label encoder missing, using fallback heuristics")
            risk_score = self._fallback_risk_score(
                account_age_days, prior_quarantine_count, identity_confidence
            )
        else:
            try:
                # Get probability predictions
                probs = self.risk_model.predict_proba(features)[0]
                
                # Get encoded class indices from model
                classes_encoded = self.risk_model.classes_
                
                # Decode to string labels with defensive checks
                try:
                    classes = self.risk_label_encoder.inverse_transform(classes_encoded)
                except (ValueError, IndexError) as e:
                    logger.warning(f"Label encoder mismatch with model classes: {e}. Using fallback.")
                    risk_score = self._fallback_risk_score(
                        account_age_days, prior_quarantine_count, identity_confidence
                    )
                else:
                    # Verify we have matching probabilities and classes
                    if len(probs) != len(classes):
                        logger.warning(
                            f"Probability array length ({len(probs)}) doesn't match classes length ({len(classes)}). "
                            "Using fallback."
                        )
                        risk_score = self._fallback_risk_score(
                            account_age_days, prior_quarantine_count, identity_confidence
                        )
                    else:
                        # Define severity map
                        severity_map = {
                            "ALLOW": 0,
                            "REVIEW": 30,
                            "QUARANTINE": 70,
                            "REJECT": 90,
                        }
                        
                        # Compute risk_score via weighted sum over labels
                        risk_score = 0.0
                        unexpected_labels = []
                        for p, label in zip(probs, classes):
                            severity = severity_map.get(label, None)
                            if severity is None:
                                unexpected_labels.append(label)
                                severity = 50.0  # default mid-risk if unexpected label
                            risk_score += p * severity
                        
                        if unexpected_labels:
                            logger.warning(
                                f"Unexpected labels in model output: {unexpected_labels}. "
                                "Using default severity (50) for these labels."
                            )
            except Exception as e:
                logger.exception("Error in risk model inference")
                risk_score = self._fallback_risk_score(
                    account_age_days, prior_quarantine_count, identity_confidence
                )

        # Assurance score (0-100) - confidence it's legitimate
        assurance_score = max(
            0,
            min(
                100,
                identity_confidence * 0.6
                + (100 - risk_score) * 0.4
                - (prior_quarantine_count * 15),
            ),
        )

        # Anomaly score (0-100)
        if not self.anomaly_model:
            logger.debug("Anomaly model not available, using fallback")
            anomaly_score = self._fallback_anomaly_score(upload_velocity, shared_device_count)
        else:
            try:
                anomaly_score_raw = self.anomaly_model.score_samples(features)[0]
                # Normalize to 0-100 (lower score = more anomalous)
                anomaly_score = max(0, min(100, 50 + (anomaly_score_raw * 10)))
            except Exception as e:
                logger.exception("Error in anomaly model inference")
                anomaly_score = self._fallback_anomaly_score(upload_velocity, shared_device_count)

        # Synthetic/AI likelihood (placeholder - heuristic for now)
        synthetic_likelihood = self._compute_synthetic_likelihood(
            identity_confidence, upload_velocity, prior_sightings_count
        )

        return {
            "risk_score": float(risk_score),
            "assurance_score": float(assurance_score),
            "anomaly_score": float(anomaly_score),
            "synthetic_likelihood": float(synthetic_likelihood),
        }

    def _fallback_risk_score(
        self, account_age_days: int, prior_quarantine_count: int, identity_confidence: float
    ) -> float:
        """Fallback risk scoring using heuristics."""
        base_risk = 20
        base_risk += (365 - min(account_age_days, 365)) / 365 * 30  # New accounts are riskier
        base_risk += prior_quarantine_count * 25
        base_risk += (100 - identity_confidence) * 0.3
        return max(0, min(100, base_risk))

    def _fallback_anomaly_score(self, upload_velocity: int, shared_device_count: int) -> float:
        """Fallback anomaly scoring."""
        base_score = 50
        if upload_velocity > 50:
            base_score -= 20
        if shared_device_count > 10:
            base_score -= 15
        return max(0, min(100, base_score))

    def _compute_synthetic_likelihood(
        self, identity_confidence: float, upload_velocity: int, prior_sightings_count: int
    ) -> float:
        """Compute synthetic/AI likelihood (placeholder)."""
        base = 20
        if identity_confidence < 30:
            base += 20
        if upload_velocity > 50:
            base += 15
        if prior_sightings_count == 0:
            base += 10  # New content might be synthetic
        return max(0, min(100, base))


# Global instance
_inference_service: Optional[MLInferenceService] = None


def get_inference_service() -> MLInferenceService:
    """Get or create inference service instance."""
    global _inference_service
    if _inference_service is None:
        _inference_service = MLInferenceService()
    return _inference_service

