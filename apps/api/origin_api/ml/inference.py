"""ML inference service for risk signals.

Returns model-driven risk signals plus explainability metadata:
- risk_score: probability-weighted severity on 0-100
- assurance_score: confidence derived from class probability entropy (0-100)
- anomaly_score: 0-100 (lower = more anomalous)
- synthetic_likelihood: heuristic 0-100 likelihood of synthetic/AI
- primary_label: highest-probability class from the risk model
- class_probabilities: mapping of label -> probability
- model_metadata: provenance information (model hashes, versions, git commit, feature schema)
"""

import hashlib
import logging
import math
import os
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd

from origin_api.settings import get_settings

logger = logging.getLogger(__name__)


class MLInferenceService:
    """ML inference service for computing risk signals."""

    def __init__(self, model_dir: str = "ml/models"):
        """Initialize inference service."""
        self.model_dir = Path(model_dir)
        self.risk_model = None
        self.risk_label_encoder = None
        self.anomaly_model = None
        self.settings = get_settings()
        self._load_models()
        
        # Compute model artifact hashes for provenance
        self.risk_model_hash: Optional[str] = None
        self.anomaly_model_hash: Optional[str] = None
        self._compute_model_hashes()

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
    
    def _compute_model_hashes(self):
        """Compute SHA256 hashes of model artifacts for provenance."""
        risk_model_path = self.model_dir / "risk_model.pkl"
        anomaly_model_path = self.model_dir / "anomaly_model.pkl"
        
        if risk_model_path.exists():
            try:
                with open(risk_model_path, "rb") as f:
                    risk_model_bytes = f.read()
                    self.risk_model_hash = hashlib.sha256(risk_model_bytes).hexdigest()
            except Exception as e:
                logger.warning(f"Failed to compute risk model hash: {e}")
        
        if anomaly_model_path.exists():
            try:
                with open(anomaly_model_path, "rb") as f:
                    anomaly_model_bytes = f.read()
                    self.anomaly_model_hash = hashlib.sha256(anomaly_model_bytes).hexdigest()
            except Exception as e:
                logger.warning(f"Failed to compute anomaly model hash: {e}")

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

        Returns a dict containing:
        - risk_score: 0-100, probability-weighted severity (higher = riskier)
        - assurance_score: 0-100, confidence derived from class-probability entropy (higher = more confident/legitimate)
        - anomaly_score: 0-100, lower = more anomalous (trained on ALLOW data)
        - synthetic_likelihood: 0-100, heuristic likelihood content is AI-generated
        - primary_label: highest-probability class predicted by the risk model
        - class_probabilities: mapping label -> probability (floats)
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

        primary_label = "REVIEW"
        class_probabilities = {}

        # Risk score (0-100)
        if not self.risk_model or not self.risk_label_encoder:
            logger.warning("Risk model or label encoder missing, using fallback heuristics")
            risk_score = self._fallback_risk_score(
                account_age_days, prior_quarantine_count, identity_confidence
            )
            # Pseudo-probabilities for fallback
            class_probabilities = {
                "ALLOW": 0.2,
                "REVIEW": 0.6,
                "QUARANTINE": 0.15,
                "REJECT": 0.05,
            }
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
                        # Build label list and probabilities
                        labels = list(classes)
                        class_probabilities = {
                            label: float(prob) for label, prob in zip(labels, probs)
                        }
                        # Primary label from highest probability
                        primary_idx = int(np.argmax(probs))
                        primary_label = labels[primary_idx]

                        # Define severity map (label-driven)
                        severity_map = {
                            "ALLOW": 5,
                            "REVIEW": 40,
                            "QUARANTINE": 75,
                            "REJECT": 90,
                        }

                        risk_score = float(
                            sum(
                                float(probs[i]) * severity_map.get(labels[i], 40.0)
                                for i in range(len(labels))
                            )
                        )

                        # Assurance score from entropy-based confidence
                        eps = 1e-8
                        num_classes = len(labels)
                        entropy = -sum(float(p) * math.log(float(p) + eps) for p in probs)
                        max_entropy = math.log(num_classes) if num_classes > 0 else 1.0
                        confidence = 1.0 - min(1.0, entropy / max_entropy) if max_entropy > 0 else 0.0
                        assurance_score = float(max(0.0, min(100.0, confidence * 100.0)))
            except Exception as e:
                logger.exception("Error in risk model inference")
                risk_score = self._fallback_risk_score(
                    account_age_days, prior_quarantine_count, identity_confidence
                )
                assurance_score = max(
                    0,
                    min(
                        100,
                        identity_confidence * 0.6
                        + (100 - risk_score) * 0.4
                        - (prior_quarantine_count * 15),
                    ),
                )
                if not class_probabilities:
                    class_probabilities = {
                        "ALLOW": 0.25,
                        "REVIEW": 0.5,
                        "QUARANTINE": 0.2,
                        "REJECT": 0.05,
                    }
        if not class_probabilities:
            # Fallback assurance if not set above
            assurance_score = max(
                0,
                min(
                    100,
                    identity_confidence * 0.6
                    + (100 - risk_score) * 0.4
                    - (prior_quarantine_count * 15),
                ),
            )

        # Assurance score (0-100) - derived from probability entropy when available, otherwise fallback heuristic
        if "assurance_score" not in locals():
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

        # Build model metadata for provenance
        model_metadata = {
            "risk_model_artifact_sha256": self.risk_model_hash,
            "anomaly_model_artifact_sha256": self.anomaly_model_hash,
            "risk_model_version": self.settings.risk_model_version or "unknown",
            "anomaly_model_version": self.settings.anomaly_model_version or "unknown",
            "git_commit_sha": self.settings.git_commit_sha or os.getenv("GIT_COMMIT_SHA") or "unknown",
            "feature_schema_version": self.settings.feature_schema_version,
        }

        return {
            "risk_score": float(risk_score),
            "assurance_score": float(assurance_score),
            "anomaly_score": float(anomaly_score),
            "synthetic_likelihood": float(synthetic_likelihood),
            "primary_label": primary_label,
            "class_probabilities": class_probabilities,
            "model_metadata": model_metadata,
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

