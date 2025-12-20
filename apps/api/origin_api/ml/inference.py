"""ML inference service for risk signals."""

import joblib
import numpy as np
from pathlib import Path
from typing import Optional

import pandas as pd


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
            artifact = joblib.load(risk_model_path)
            if isinstance(artifact, dict) and "model" in artifact and "label_encoder" in artifact:
                self.risk_model = artifact["model"]
                self.risk_label_encoder = artifact["label_encoder"]
            else:
                # Backward compatibility: if old format, treat as model only
                self.risk_model = artifact
                self.risk_label_encoder = None
                print("Warning: Risk model loaded without label encoder. Using fallback label mapping.")
        else:
            print("Warning: Risk model not found. Using fallback heuristics.")

        if anomaly_model_path.exists():
            self.anomaly_model = joblib.load(anomaly_model_path)
        else:
            print("Warning: Anomaly model not found. Using fallback heuristics.")

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
        if self.risk_model:
            try:
                # Get probability predictions
                probs = self.risk_model.predict_proba(features)[0]
                
                # Use label encoder to get string labels if available
                if self.risk_label_encoder is not None:
                    # Get encoded class indices from model
                    classes_encoded = self.risk_model.classes_
                    # Decode to string labels
                    classes = self.risk_label_encoder.inverse_transform(classes_encoded)
                    
                    # Define severity map
                    severity_map = {
                        "ALLOW": 0,
                        "REVIEW": 30,
                        "QUARANTINE": 70,
                        "REJECT": 90,
                    }
                    
                    # Compute risk_score via weighted sum over labels
                    risk_score = 0.0
                    for p, label in zip(probs, classes):
                        severity = severity_map.get(label, 50.0)  # default mid-risk if unexpected label
                        risk_score += p * severity
                else:
                    # Fallback: assume fixed ordering if no encoder (backward compatibility)
                    # This should not happen with new models, but handle gracefully
                    if len(probs) >= 4:
                        risk_score = (
                            probs[0] * 0 +  # ALLOW
                            probs[1] * 30 +  # REVIEW
                            probs[2] * 70 +  # QUARANTINE
                            probs[3] * 90   # REJECT
                        )
                    else:
                        # Handle case where model has fewer classes
                        risk_score = self._fallback_risk_score(
                            account_age_days, prior_quarantine_count, identity_confidence
                        )
            except Exception as e:
                print(f"Error in risk model inference: {e}")
                risk_score = self._fallback_risk_score(
                    account_age_days, prior_quarantine_count, identity_confidence
                )
        else:
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
        if self.anomaly_model:
            try:
                anomaly_score_raw = self.anomaly_model.score_samples(features)[0]
                # Normalize to 0-100 (lower score = more anomalous)
                anomaly_score = max(0, min(100, 50 + (anomaly_score_raw * 10)))
            except Exception as e:
                print(f"Error in anomaly model inference: {e}")
                anomaly_score = self._fallback_anomaly_score(upload_velocity, shared_device_count)
        else:
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

