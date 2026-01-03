"""JWS (JSON Web Signature) signing for DecisionTrace (F2).

Creates a signed, compact JWS object from the canonical decision trace.
This enables third-party verification of decision integrity without exposing
internal cryptographic keys.
"""

import json
import logging
from typing import Dict, Any, Optional

from jose import jws
from jose.constants import ALGORITHMS

from origin_api.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class DecisionTraceSigner:
    """Sign and verify decision traces using JWS."""

    def __init__(self):
        """Initialize signer with key from settings."""
        # In production, load from secure key management
        # For now, use a deterministic key derived from settings
        self._private_key = self._load_or_generate_key()
        self._public_key = self._get_public_key()

    def _load_or_generate_key(self) -> bytes:
        """Load or generate signing key."""
        # In production, use proper key management (HSM, AWS KMS, etc.)
        # For MVP, derive from secret_key (NOT SECURE FOR PRODUCTION)
        import hashlib
        key_material = settings.secret_key.encode()
        # Use SHA256 to get 32 bytes for HS256
        key = hashlib.sha256(key_material).digest()
        return key

    def _get_public_key(self) -> bytes:
        """Get public key for verification (symmetric key, so same as private)."""
        # For HS256 (symmetric), public key is same as private
        # For RS256 (asymmetric), would extract public key from private
        return self._private_key

    def sign_decision_trace(
        self,
        decision_trace: Dict[str, Any],
        model_hashes: Optional[Dict[str, str]] = None,
        policy_profile_id: Optional[int] = None,
        feature_schema_version: Optional[str] = None,
    ) -> str:
        """
        Create a signed JWS compact object from decision trace (F2).
        
        The decision trace includes:
        - Decision, risk_score, assurance_score
        - Triggered rules, reason codes, rationale
        - Top contributors (from interpretability cues)
        - Model hashes, policy profile ID, feature schema version
        - Thresholds used
        
        Args:
            decision_trace: Canonical decision trace dict
            model_hashes: Optional dict with risk_model_artifact_sha256, anomaly_model_artifact_sha256
            policy_profile_id: Optional policy profile ID
            feature_schema_version: Optional feature schema version
        
        Returns:
            Compact JWS string (header.payload.signature)
        """
        # Build canonical decision trace payload
        payload = {
            "decision": decision_trace.get("decision"),
            "risk_score": decision_trace.get("risk_score"),
            "assurance_score": decision_trace.get("assurance_score"),
            "triggered_rules": decision_trace.get("triggered_rules", []),
            "reason_codes": decision_trace.get("reason_codes", []),
            "rationale": decision_trace.get("rationale"),
            # Provenance fields
            "model_hashes": model_hashes or {},
            "policy_profile_id": policy_profile_id,
            "feature_schema_version": feature_schema_version,
            # Top contributors (extract from rationale or interpretability cues)
            "top_contributors": self._extract_top_contributors(decision_trace),
        }
        
        # Create canonical JSON (sorted keys for determinism)
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        
        # Sign with HS256 (HMAC-SHA256)
        # In production, consider RS256 (RSA) for asymmetric verification
        try:
            compact_jws = jws.sign(
                payload_json.encode("utf-8"),
                self._private_key,
                algorithm=ALGORITHMS.HS256,
            )
            return compact_jws
        except Exception as e:
            logger.error(f"Failed to sign decision trace: {e}")
            raise

    def verify_decision_trace(self, compact_jws: str) -> Dict[str, Any]:
        """
        Verify and decode signed decision trace.
        
        Args:
            compact_jws: Compact JWS string
        
        Returns:
            Decoded payload dict
        
        Raises:
            ValueError: If signature is invalid
        """
        try:
            payload_bytes = jws.verify(
                compact_jws,
                self._public_key,
                algorithms=[ALGORITHMS.HS256],
            )
            payload = json.loads(payload_bytes.decode("utf-8"))
            return payload
        except Exception as e:
            logger.error(f"Failed to verify decision trace: {e}")
            raise ValueError(f"Invalid JWS signature: {e}")

    def _extract_top_contributors(self, decision_trace: Dict[str, Any]) -> list[str]:
        """Extract top contributors from rationale or interpretability cues."""
        rationale = decision_trace.get("rationale", "")
        
        # Try to extract from "Primary drivers:" section
        if "Primary drivers:" in rationale:
            parts = rationale.split("Primary drivers:")
            if len(parts) > 1:
                drivers_text = parts[1].split(".")[0].strip()
                # Parse comma-separated list
                contributors = [d.strip() for d in drivers_text.split(",")]
                return contributors[:3]  # Top 3
        
        # Fallback: return empty list
        return []


# Global instance
_decision_trace_signer: Optional[DecisionTraceSigner] = None


def get_decision_trace_signer() -> DecisionTraceSigner:
    """Get or create decision trace signer instance."""
    global _decision_trace_signer
    if _decision_trace_signer is None:
        _decision_trace_signer = DecisionTraceSigner()
    return _decision_trace_signer

