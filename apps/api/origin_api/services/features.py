"""Feature computation service for ML inputs."""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from origin_api.models import Account, IdentityEntity, IdentityRelationship, Upload


class FeatureService:
    """Compute features from database for ML inference."""

    def __init__(self, db: Session):
        """Initialize feature service."""
        self.db = db

    def compute_account_age_days(self, account_id: int) -> int:
        """Compute account age in days."""
        account = self.db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return 0

        age_delta = datetime.utcnow() - account.created_at
        return max(0, age_delta.days)

    def compute_upload_velocity_24h(self, tenant_id: int, account_id: int) -> int:
        """Count uploads in last 24 hours for account."""
        since = datetime.utcnow() - timedelta(hours=24)
        count = (
            self.db.query(func.count(Upload.id))
            .filter(
                Upload.tenant_id == tenant_id,
                Upload.account_id == account_id,
                Upload.received_at >= since,
            )
            .scalar()
        )
        return count or 0

    def compute_device_velocity_24h(
        self, tenant_id: int, device_entity_id: Optional[int]
    ) -> int:
        """Count uploads in last 24 hours for device entity."""
        if not device_entity_id:
            return 0

        since = datetime.utcnow() - timedelta(hours=24)
        # Find accounts using this device
        account_ids = (
            self.db.query(IdentityRelationship.from_entity_id)
            .join(
                IdentityEntity,
                IdentityRelationship.from_entity_id == IdentityEntity.id,
            )
            .filter(
                IdentityRelationship.tenant_id == tenant_id,
                IdentityRelationship.to_entity_id == device_entity_id,
                IdentityRelationship.relationship_type == "uses_device",
                IdentityEntity.entity_type == "account",
            )
            .subquery()
        )

        count = (
            self.db.query(func.count(Upload.id))
            .filter(
                Upload.tenant_id == tenant_id,
                Upload.account_id.in_(account_ids),
                Upload.received_at >= since,
            )
            .scalar()
        )
        return count or 0

    def compute_prior_quarantine_count(
        self, tenant_id: int, account_id: Optional[int], pvid: Optional[str]
    ) -> dict:
        """Compute prior quarantine/reject counts for account and PVID."""
        result = {"account_quarantine": 0, "account_reject": 0, "pvid_quarantine": 0, "pvid_reject": 0}

        if account_id:
            # Account-level counts
            account_quarantine = (
                self.db.query(func.count(Upload.id))
                .filter(
                    Upload.tenant_id == tenant_id,
                    Upload.account_id == account_id,
                    Upload.decision == "QUARANTINE",
                )
                .scalar()
                or 0
            )
            account_reject = (
                self.db.query(func.count(Upload.id))
                .filter(
                    Upload.tenant_id == tenant_id,
                    Upload.account_id == account_id,
                    Upload.decision == "REJECT",
                )
                .scalar()
                or 0
            )
            result["account_quarantine"] = account_quarantine
            result["account_reject"] = account_reject

        if pvid:
            # PVID-level counts
            pvid_quarantine = (
                self.db.query(func.count(Upload.id))
                .filter(
                    Upload.tenant_id == tenant_id,
                    Upload.pvid == pvid,
                    Upload.decision == "QUARANTINE",
                )
                .scalar()
                or 0
            )
            pvid_reject = (
                self.db.query(func.count(Upload.id))
                .filter(
                    Upload.tenant_id == tenant_id,
                    Upload.pvid == pvid,
                    Upload.decision == "REJECT",
                )
                .scalar()
                or 0
            )
            result["pvid_quarantine"] = pvid_quarantine
            result["pvid_reject"] = pvid_reject

        return result

    def compute_all_features(
        self,
        tenant_id: int,
        account_id: int,
        device_entity_id: Optional[int],
        pvid: Optional[str],
    ) -> dict:
        """Compute all features for ML inference."""
        account_age_days = self.compute_account_age_days(account_id)
        upload_velocity_24h = self.compute_upload_velocity_24h(tenant_id, account_id)
        device_velocity_24h = self.compute_device_velocity_24h(tenant_id, device_entity_id)
        prior_counts = self.compute_prior_quarantine_count(tenant_id, account_id, pvid)

        return {
            "account_age_days": account_age_days,
            "upload_velocity_24h": upload_velocity_24h,
            "device_velocity_24h": device_velocity_24h,
            "prior_quarantine_count": prior_counts["account_quarantine"] + prior_counts["pvid_quarantine"],
            "prior_reject_count": prior_counts["account_reject"] + prior_counts["pvid_reject"],
            "has_prior_quarantine": (prior_counts["account_quarantine"] + prior_counts["pvid_quarantine"]) > 0,
            "has_prior_reject": (prior_counts["account_reject"] + prior_counts["pvid_reject"]) > 0,
        }

