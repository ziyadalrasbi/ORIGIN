"""Provenance ID (PVID) generation and resolution."""

import hashlib
import json
from typing import Optional

from sqlalchemy.orm import Session

from origin_api.models import Upload


class PVIDGenerator:
    """Generate and resolve Provenance IDs."""

    def __init__(self, db: Session):
        """Initialize PVID generator."""
        self.db = db

    def canonicalize_metadata(self, metadata: dict) -> str:
        """Canonicalize metadata for consistent hashing."""
        if not metadata:
            return "{}"

        # Sort keys and normalize values
        canonical = {}
        for key in sorted(metadata.keys()):
            value = metadata[key]
            if isinstance(value, (dict, list)):
                value = json.dumps(value, sort_keys=True)
            canonical[key] = str(value).lower().strip()

        return json.dumps(canonical, sort_keys=True)

    def generate_pvid(
        self,
        tenant_id: int,
        content_ref: Optional[str],
        fingerprints: Optional[dict],
        metadata: Optional[dict],
    ) -> str:
        """Generate deterministic PVID from content attributes."""
        components = []

        # Add content reference if available
        if content_ref:
            components.append(f"content_ref:{content_ref}")

        # Add fingerprints
        if fingerprints:
            for key in sorted(fingerprints.keys()):
                value = fingerprints[key]
                if value:
                    components.append(f"fingerprint:{key}:{value}")

        # Add canonicalized metadata
        if metadata:
            canonical_metadata = self.canonicalize_metadata(metadata)
            components.append(f"metadata:{canonical_metadata}")

        # Combine and hash
        combined = "|".join(components)
        pvid_hash = hashlib.sha256(combined.encode()).hexdigest()

        return f"PVID-{pvid_hash[:16].upper()}"

    def check_prior_sightings(
        self, tenant_id: int, pvid: str
    ) -> dict:
        """Check for prior sightings of this PVID."""
        sightings = (
            self.db.query(Upload)
            .filter(
                Upload.tenant_id == tenant_id,
                Upload.pvid == pvid,
            )
            .all()
        )

        if not sightings:
            return {
                "prior_sightings_count": 0,
                "has_prior_quarantine": False,
                "has_prior_reject": False,
                "first_seen_at": None,
                "last_seen_at": None,
            }

        # Check for negative provenance
        has_quarantine = any(s.decision == "QUARANTINE" for s in sightings)
        has_reject = any(s.decision == "REJECT" for s in sightings)

        first_seen = min(s.received_at for s in sightings)
        last_seen = max(s.received_at for s in sightings)

        return {
            "prior_sightings_count": len(sightings),
            "has_prior_quarantine": has_quarantine,
            "has_prior_reject": has_reject,
            "first_seen_at": first_seen,
            "last_seen_at": last_seen,
        }

    def resolve_pvid(
        self,
        tenant_id: int,
        content_ref: Optional[str],
        fingerprints: Optional[dict],
        metadata: Optional[dict],
    ) -> dict:
        """Resolve PVID and check for prior sightings."""
        pvid = self.generate_pvid(tenant_id, content_ref, fingerprints, metadata)
        sightings = self.check_prior_sightings(tenant_id, pvid)

        return {
            "pvid": pvid,
            "sightings": sightings,
        }

