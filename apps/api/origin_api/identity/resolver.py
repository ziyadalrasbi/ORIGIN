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
        features = self.compute_identity_features(tenant_id, account_entity.id)

        return {
            "account_entity_id": account_entity.id,
            "device_entity_id": device_entity.id if device_entity else None,
            "identity_confidence": features["identity_confidence"],
            "features": features,
        }

    def compute_identity_features(self, tenant_id: int, account_entity_id: int) -> dict:
        """
        Compute identity graph features.
        
        Features computed:
        - shared_device_count: Number of devices linked to this account
        - relationship_count: Total identity relationships
        - prior_quarantine_count: Count of prior QUARANTINE decisions for this account
        - identity_confidence: 0-100 score based on graph features
        
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
        # Get account_id from entity attributes if available
        account_id = None
        if account_entity.attributes_json and "account_id" in account_entity.attributes_json:
            account_id = account_entity.attributes_json["account_id"]
        
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

        # Compute confidence score (0-100)
        # Higher confidence = more established identity
        identity_confidence = min(
            100,
            50 + (shared_device_count * 10) + (relationship_count * 5) - (prior_quarantine_count * 20),
        )

        return {
            "identity_confidence": max(0, identity_confidence),
            "shared_device_count": shared_device_count,
            "relationship_count": relationship_count,
            "prior_quarantine_count": prior_quarantine_count,
        }

