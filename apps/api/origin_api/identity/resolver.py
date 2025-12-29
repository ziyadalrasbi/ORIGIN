"""Identity resolution service (KYA++)."""

import hashlib
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from origin_api.models import Account, DeviceFingerprint, IdentityEntity, IdentityRelationship, Upload


class IdentityResolver:
    """Resolve uploader to persistent identity entities."""

    def __init__(self, db: Session):
        """Initialize resolver with database session."""
        self.db = db

    def hash_value(self, value: str) -> str:
        """Hash a value for storage."""
        return hashlib.sha256(value.encode()).hexdigest()

    def resolve_account_entity(
        self, tenant_id: int, account_id: int, account_external_id: str
    ) -> IdentityEntity:
        """Resolve account to identity entity."""
        entity_key = f"account:{account_external_id}"
        entity_key_hash = self.hash_value(entity_key)

        entity = (
            self.db.query(IdentityEntity)
            .filter(
                IdentityEntity.tenant_id == tenant_id,
                IdentityEntity.entity_type == "account",
                IdentityEntity.entity_key_hash == entity_key_hash,
            )
            .first()
        )

        if not entity:
            entity = IdentityEntity(
                tenant_id=tenant_id,
                entity_type="account",
                entity_key_hash=entity_key_hash,
                attributes_json={"account_id": account_id, "external_id": account_external_id},
            )
            self.db.add(entity)
            self.db.flush()

        return entity

    def resolve_device_entity(
        self, tenant_id: int, device_hash: str, ip_hash: Optional[str] = None
    ) -> Optional[IdentityEntity]:
        """Resolve device to identity entity."""
        if not device_hash:
            return None

        entity_key = f"device:{device_hash}"
        entity_key_hash = self.hash_value(entity_key)

        entity = (
            self.db.query(IdentityEntity)
            .filter(
                IdentityEntity.tenant_id == tenant_id,
                IdentityEntity.entity_type == "device",
                IdentityEntity.entity_key_hash == entity_key_hash,
            )
            .first()
        )

        if not entity:
            entity = IdentityEntity(
                tenant_id=tenant_id,
                entity_type="device",
                entity_key_hash=entity_key_hash,
                attributes_json={"device_hash": device_hash, "ip_hash": ip_hash},
            )
            self.db.add(entity)
            self.db.flush()

        return entity

    def create_relationship(
        self,
        tenant_id: int,
        from_entity_id: int,
        to_entity_id: int,
        relationship_type: str,
    ) -> IdentityRelationship:
        """Create or update identity relationship."""
        relationship = (
            self.db.query(IdentityRelationship)
            .filter(
                IdentityRelationship.tenant_id == tenant_id,
                IdentityRelationship.from_entity_id == from_entity_id,
                IdentityRelationship.to_entity_id == to_entity_id,
                IdentityRelationship.relationship_type == relationship_type,
            )
            .first()
        )

        if relationship:
            relationship.weight += 1
            relationship.last_seen_at = datetime.utcnow()
        else:
            relationship = IdentityRelationship(
                tenant_id=tenant_id,
                from_entity_id=from_entity_id,
                to_entity_id=to_entity_id,
                relationship_type=relationship_type,
                weight=1,
            )
            self.db.add(relationship)

        return relationship

    def resolve_identity(
        self,
        tenant_id: int,
        account_id: int,
        account_external_id: str,
        device_hash: Optional[str] = None,
        ip_hash: Optional[str] = None,
    ) -> dict:
        """Resolve identity and compute features."""
        # Resolve account entity
        account_entity = self.resolve_account_entity(tenant_id, account_id, account_external_id)

        # Resolve device entity if provided
        device_entity = None
        if device_hash:
            device_entity = self.resolve_device_entity(tenant_id, device_hash, ip_hash)
            if device_entity:
                # Create relationship: account -> device
                self.create_relationship(
                    tenant_id, account_entity.id, device_entity.id, "uses_device"
                )

        # Compute identity features
        features = self.compute_identity_features(tenant_id, account_entity.id, account_id=account_id)

        return {
            "account_entity_id": account_entity.id,
            "device_entity_id": device_entity.id if device_entity else None,
            "identity_confidence": features["identity_confidence"],
            "features": features,
        }

    def detect_cross_tenant_identity(
        self, entity_key_hash: str, current_tenant_id: int
    ) -> dict:
        """
        Detect cross-tenant identity reuse (privacy-safe, hash-based).
        
        This method enables Cross-Tenant Identity Graph (CIG) functionality by
        detecting when the same identity entity (by hash) exists across multiple
        tenants, without exposing raw tenant data.
        
        Returns:
        - cross_tenant_count: Number of other tenants where this identity exists
        - cross_tenant_risk_signals: Aggregated risk signals (no raw data)
        """
        # Query for same entity_key_hash in other tenants (privacy-safe)
        cross_tenant_entities = (
            self.db.query(IdentityEntity)
            .filter(
                IdentityEntity.entity_key_hash == entity_key_hash,
                IdentityEntity.tenant_id != current_tenant_id,
            )
            .all()
        )

        if not cross_tenant_entities:
            return {
                "cross_tenant_count": 0,
                "cross_tenant_risk_signals": {},
                "cross_tenant_identity_reuse": False,
            }

        # Aggregate risk signals across tenants (privacy-safe aggregation)
        # We only count decisions, never expose raw content or tenant-specific data
        cross_tenant_tenant_ids = [e.tenant_id for e in cross_tenant_entities]
        
        # Get account IDs from cross-tenant entities (privacy-safe - only IDs, no content)
        cross_tenant_account_ids = []
        for entity in cross_tenant_entities:
            if entity.attributes_json and "account_id" in entity.attributes_json:
                cross_tenant_account_ids.append(entity.attributes_json["account_id"])
        
        # Count prior quarantines/rejects across tenants (aggregated, no raw data)
        cross_tenant_quarantines = 0
        cross_tenant_rejects = 0
        
        if cross_tenant_account_ids:
            # Query for quarantines across tenants (privacy-safe - only counts)
            cross_tenant_quarantines = (
                self.db.query(func.count(Upload.id))
                .filter(
                    Upload.tenant_id.in_(cross_tenant_tenant_ids),
                    Upload.account_id.in_(cross_tenant_account_ids),
                    Upload.decision == "QUARANTINE",
                )
                .scalar()
                or 0
            )

            cross_tenant_rejects = (
                self.db.query(func.count(Upload.id))
                .filter(
                    Upload.tenant_id.in_(cross_tenant_tenant_ids),
                    Upload.account_id.in_(cross_tenant_account_ids),
                    Upload.decision == "REJECT",
                )
                .scalar()
                or 0
            )

        return {
            "cross_tenant_count": len(cross_tenant_entities),
            "cross_tenant_risk_signals": {
                "prior_quarantine_count": cross_tenant_quarantines,
                "prior_reject_count": cross_tenant_rejects,
                "identity_reuse_detected": True,
            },
            "cross_tenant_identity_reuse": True,
        }

    def compute_identity_features(
        self, tenant_id: int, account_entity_id: int, account_id: Optional[int] = None
    ) -> dict:
        """
        Compute identity graph features (including cross-tenant if enabled).
        
        Features computed:
        - shared_device_count: Number of devices linked to this account
        - relationship_count: Total identity relationships
        - prior_quarantine_count: Count of prior QUARANTINE decisions for this account
        - identity_confidence: 0-100 score based on graph features
        - cross_tenant_signals: Cross-tenant identity reuse detection (if enabled)
        
        Returns dict with all computed features.
        """
        # Count shared devices
        shared_device_count = (
            self.db.query(func.count(IdentityRelationship.id))
            .join(
                IdentityEntity,
                IdentityRelationship.to_entity_id == IdentityEntity.id,
            )
            .filter(
                IdentityRelationship.tenant_id == tenant_id,
                IdentityRelationship.from_entity_id == account_entity_id,
                IdentityRelationship.relationship_type == "uses_device",
                IdentityEntity.entity_type == "device",
            )
            .scalar()
            or 0
        )

        # Count relationships (network connections)
        relationship_count = (
            self.db.query(func.count(IdentityRelationship.id))
            .filter(
                IdentityRelationship.tenant_id == tenant_id,
                IdentityRelationship.from_entity_id == account_entity_id,
            )
            .scalar()
            or 0
        )

        # Query prior quarantines from uploads table
        # Use provided account_id, or try to get from entity attributes
        account_entity_obj = (
            self.db.query(IdentityEntity)
            .filter(IdentityEntity.id == account_entity_id)
            .first()
        )
        
        if account_id is None and account_entity_obj:
            if account_entity_obj.attributes_json and "account_id" in account_entity_obj.attributes_json:
                account_id = account_entity_obj.attributes_json["account_id"]
        
        prior_quarantine_count = 0
        if account_id:
            prior_quarantine_count = (
                self.db.query(Upload)
                .filter(
                    Upload.tenant_id == tenant_id,
                    Upload.account_id == account_id,
                    Upload.decision == "QUARANTINE",
                )
                .count()
            )

        # Cross-tenant identity detection (CIG - Cross-Tenant Identity Graph)
        cross_tenant_signals = {}
        if account_entity_obj and account_entity_obj.entity_key_hash:
            cross_tenant_signals = self.detect_cross_tenant_identity(
                account_entity_obj.entity_key_hash, tenant_id
            )
        
        # Adjust prior_quarantine_count to include cross-tenant signals
        total_prior_quarantines = prior_quarantine_count
        if cross_tenant_signals.get("cross_tenant_risk_signals", {}).get("prior_quarantine_count"):
            total_prior_quarantines += cross_tenant_signals["cross_tenant_risk_signals"]["prior_quarantine_count"]
        
        # Compute confidence score (0-100)
        # Higher confidence = more established identity
        # Cross-tenant reuse reduces confidence (potential identity hopper)
        base_confidence = 50 + (shared_device_count * 10) + (relationship_count * 5) - (total_prior_quarantines * 20)
        
        # Penalize cross-tenant identity reuse (potential fraud indicator)
        if cross_tenant_signals.get("cross_tenant_identity_reuse"):
            cross_tenant_penalty = min(30, cross_tenant_signals.get("cross_tenant_count", 0) * 5)
            base_confidence -= cross_tenant_penalty
        
        identity_confidence = max(0, min(100, base_confidence))

        return {
            "identity_confidence": identity_confidence,
            "shared_device_count": shared_device_count,
            "relationship_count": relationship_count,
            "prior_quarantine_count": prior_quarantine_count,
            "cross_tenant_signals": cross_tenant_signals,
        }

