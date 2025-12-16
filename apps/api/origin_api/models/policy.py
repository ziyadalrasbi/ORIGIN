"""Policy and decision certificate models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from origin_api.db.base import Base


class PolicyProfile(Base):
    """Policy profile model for tenant-specific policy configuration."""

    __tablename__ = "policy_profiles"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)  # NULL for global defaults
    name = Column(String(255), nullable=False, index=True)
    version = Column(String(50), nullable=False)
    thresholds_json = Column(JSON, nullable=True)  # Risk thresholds, assurance thresholds, etc.
    weights_json = Column(JSON, nullable=True)  # Feature weights for policy rules
    ruleset_ref = Column(String(255), nullable=True)  # Reference to policy ruleset (OPA bundle or JSON)
    risk_model_version = Column(String(100), nullable=True)  # ML model version used for risk scoring
    anomaly_model_version = Column(String(100), nullable=True)  # ML model version used for anomaly detection
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="policy_profile", foreign_keys="Tenant.policy_profile_id")
    tenants = relationship("Tenant", foreign_keys="Tenant.policy_profile_id", back_populates="policy_profile")


class DecisionCertificate(Base):
    """Decision certificate model for tamper-evident decisions."""

    __tablename__ = "decision_certificates"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    upload_id = Column(Integer, ForeignKey("uploads.id"), nullable=False, index=True)
    certificate_id = Column(String(255), nullable=False, unique=True, index=True)
    issued_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    policy_version = Column(String(100), nullable=False)
    inputs_hash = Column(String(255), nullable=False)  # Hash of policy inputs
    outputs_hash = Column(String(255), nullable=False)  # Hash of decision outputs
    ledger_hash = Column(String(255), nullable=False, index=True)  # Hash of ledger event
    signature = Column(Text, nullable=False)  # Cryptographic signature
    key_id = Column(String(100), nullable=True)  # Key ID (kid) for key rotation
    alg = Column(String(20), default="PS256", nullable=False)  # Signature algorithm (PS256 for RSA-PSS SHA-256)
    signature_encoding = Column(String(20), default="base64", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant")
    upload = relationship("Upload", back_populates="decision_certificates")
    evidence_packs = relationship("EvidencePack", back_populates="certificate", cascade="all, delete-orphan")

