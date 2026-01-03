"""Seed data for development and testing."""

import hashlib
import logging
from datetime import datetime, timedelta

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from origin_api.models import (
    APIKey,
    Account,
    PolicyProfile,
    Tenant,
)

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_api_key(api_key: str) -> str:
    """Hash an API key using Argon2/bcrypt."""
    # Bcrypt has a 72-byte limit, truncate if necessary
    api_key_bytes = api_key.encode('utf-8')
    if len(api_key_bytes) > 72:
        api_key_bytes = api_key_bytes[:72]
        api_key = api_key_bytes.decode('utf-8', errors='ignore')
    return pwd_context.hash(api_key)


def seed_tenants(db: Session):
    """Seed demo tenants."""
    # Demo tenant
    demo_tenant = db.query(Tenant).filter(Tenant.label == "demo").first()
    if not demo_tenant:
        demo_tenant = Tenant(
            label="demo",
            api_key_hash=hash_api_key("demo-api-key-12345"),
            status="active",
        )
        db.add(demo_tenant)
        db.flush()

        # Create API key
        api_key = APIKey(
            tenant_id=demo_tenant.id,
            hash=hash_api_key("demo-api-key-12345"),
            label="Default API Key",
            scopes='["ingest", "evidence", "read"]',
            is_active=True,
        )
        db.add(api_key)

        # Create default policy profile
        policy_profile = PolicyProfile(
            tenant_id=demo_tenant.id,
            name="default",
            version="ORIGIN-CORE-v1.0",
            thresholds_json={
                "risk_threshold_review": 40,
                "risk_threshold_quarantine": 70,
                "risk_threshold_reject": 90,
                "assurance_threshold_allow": 80,
                "anomaly_threshold": 30,
                "synthetic_threshold": 70,
            },
            weights_json={},
            decision_mode="score_first",
            regulatory_compliance_json={
                "DSA": {
                    "article_14": "Content moderation obligations - risk_score thresholds map to moderation tiers",
                    "article_15": "Transparency reporting - decision_rationale provides audit trail",
                    "article_16": "Risk assessment - risk_score, anomaly_score, synthetic_likelihood inform assessment",
                    "mapped_thresholds": {
                        "risk_threshold_reject": "Article 14 - Immediate removal threshold",
                        "risk_threshold_quarantine": "Article 14 - Restriction threshold",
                        "risk_threshold_review": "Article 16 - Risk assessment trigger",
                    }
                },
                "OSA": {
                    "section_9": "Duty to assess risk - risk_score and assurance_score inform risk assessment",
                    "section_10": "Duty to prevent harm - QUARANTINE/REJECT decisions prevent harmful content",
                    "section_19": "Transparency reporting - evidence packs provide decision audit trail",
                    "mapped_thresholds": {
                        "risk_threshold_reject": "Section 10 - Harmful content removal",
                        "synthetic_threshold": "Section 9 - AI-generated content detection",
                        "anomaly_threshold": "Section 9 - Anomalous behavior detection",
                    }
                },
                "AI_Act": {
                    "article_50": "Transparency obligations - synthetic_likelihood detects AI-generated content",
                    "article_52": "High-risk AI systems - risk_score thresholds identify high-risk content",
                    "mapped_thresholds": {
                        "synthetic_threshold": "Article 50 - AI content disclosure threshold",
                        "risk_threshold_quarantine": "Article 52 - High-risk content identification",
                    }
                }
            },
            is_active=True,
        )
        db.add(policy_profile)
        demo_tenant.policy_profile_id = policy_profile.id

        db.commit()
        logger.info(f"✓ Created demo tenant: {demo_tenant.label} (ID: {demo_tenant.id})")
        logger.info(f"  API Key: demo-api-key-12345")
    else:
        logger.info(f"✓ Demo tenant already exists: {demo_tenant.label}")

    # Test tenant
    test_tenant = db.query(Tenant).filter(Tenant.label == "test").first()
    if not test_tenant:
        test_tenant = Tenant(
            label="test",
            api_key_hash=hash_api_key("test-api-key-67890"),
            status="active",
        )
        db.add(test_tenant)
        db.flush()

        api_key = APIKey(
            tenant_id=test_tenant.id,
            hash=hash_api_key("test-api-key-67890"),
            label="Test API Key",
            scopes='["ingest", "evidence", "read"]',
            is_active=True,
        )
        db.add(api_key)

        policy_profile = PolicyProfile(
            tenant_id=test_tenant.id,
            name="default",
            version="ORIGIN-CORE-v1.0",
            thresholds_json={
                "risk_threshold_review": 40,
                "risk_threshold_quarantine": 70,
                "risk_threshold_reject": 90,
                "assurance_threshold_allow": 80,
                "anomaly_threshold": 30,
                "synthetic_threshold": 70,
            },
            weights_json={},
            decision_mode="score_first",
            regulatory_compliance_json={
                "DSA": {
                    "article_14": "Content moderation obligations - risk_score thresholds map to moderation tiers",
                    "article_15": "Transparency reporting - decision_rationale provides audit trail",
                    "article_16": "Risk assessment - risk_score, anomaly_score, synthetic_likelihood inform assessment",
                    "mapped_thresholds": {
                        "risk_threshold_reject": "Article 14 - Immediate removal threshold",
                        "risk_threshold_quarantine": "Article 14 - Restriction threshold",
                        "risk_threshold_review": "Article 16 - Risk assessment trigger",
                    }
                },
                "OSA": {
                    "section_9": "Duty to assess risk - risk_score and assurance_score inform risk assessment",
                    "section_10": "Duty to prevent harm - QUARANTINE/REJECT decisions prevent harmful content",
                    "section_19": "Transparency reporting - evidence packs provide decision audit trail",
                    "mapped_thresholds": {
                        "risk_threshold_reject": "Section 10 - Harmful content removal",
                        "synthetic_threshold": "Section 9 - AI-generated content detection",
                        "anomaly_threshold": "Section 9 - Anomalous behavior detection",
                    }
                },
                "AI_Act": {
                    "article_50": "Transparency obligations - synthetic_likelihood detects AI-generated content",
                    "article_52": "High-risk AI systems - risk_score thresholds identify high-risk content",
                    "mapped_thresholds": {
                        "synthetic_threshold": "Article 50 - AI content disclosure threshold",
                        "risk_threshold_quarantine": "Article 52 - High-risk content identification",
                    }
                }
            },
            is_active=True,
        )
        db.add(policy_profile)
        test_tenant.policy_profile_id = policy_profile.id

        db.commit()
        logger.info(f"✓ Created test tenant: {test_tenant.label} (ID: {test_tenant.id})")
        logger.info(f"  API Key: test-api-key-67890")
    else:
        logger.info(f"✓ Test tenant already exists: {test_tenant.label}")


def seed_accounts(db: Session):
    """Seed demo accounts."""
    demo_tenant = db.query(Tenant).filter(Tenant.label == "demo").first()
    if not demo_tenant:
        return

    # Create a few demo accounts
    accounts_data = [
        {"external_id": "user-001", "type": "user", "display_name": "Demo User 1", "risk_state": "clean"},
        {"external_id": "user-002", "type": "user", "display_name": "Demo User 2", "risk_state": "clean"},
        {"external_id": "org-001", "type": "organization", "display_name": "Demo Org", "risk_state": "clean"},
    ]

    for acc_data in accounts_data:
        account = db.query(Account).filter(
            Account.tenant_id == demo_tenant.id,
            Account.external_id == acc_data["external_id"],
        ).first()
        if not account:
            account = Account(
                tenant_id=demo_tenant.id,
                **acc_data,
            )
            db.add(account)
            logger.info(f"✓ Created account: {acc_data['external_id']}")
        else:
            logger.info(f"✓ Account already exists: {acc_data['external_id']}")

    db.commit()


def seed_all(db: Session):
    """Seed all data."""
    logger.info("Seeding database...")
    seed_tenants(db)
    seed_accounts(db)
    logger.info("✓ Seeding complete!")

