"""Upload and decision models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import relationship

from origin_api.db.base import Base


class Upload(Base):
    """Upload model for content submissions."""

    __tablename__ = "uploads"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    ingestion_id = Column(String(255), nullable=False, unique=True, index=True)
    external_id = Column(String(255), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    title = Column(String(500), nullable=True)
    metadata_json = Column(JSON, nullable=True)
    content_ref = Column(Text, nullable=True)  # URL or reference to content
    fingerprints_json = Column(JSON, nullable=True)  # audio_hash, perceptual_hash, etc.
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    pvid = Column(String(255), nullable=True, index=True)  # Provenance ID
    decision = Column(String(50), nullable=False, index=True)  # ALLOW, REVIEW, QUARANTINE, REJECT
    policy_version = Column(String(100), nullable=False)
    risk_score = Column(Numeric(5, 2), nullable=True)  # 0-100
    assurance_score = Column(Numeric(5, 2), nullable=True)  # 0-100
    decision_inputs_json = Column(JSON, nullable=True)  # Computed features for explainability
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Unique constraint per tenant
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )

    # Relationships
    tenant = relationship("Tenant")
    account = relationship("Account", back_populates="uploads")
    risk_signals = relationship("RiskSignal", back_populates="upload", cascade="all, delete-orphan")
    decision_certificates = relationship("DecisionCertificate", back_populates="upload", cascade="all, delete-orphan")


class RiskSignal(Base):
    """Risk signal model for ML outputs."""

    __tablename__ = "risk_signals"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    upload_id = Column(Integer, ForeignKey("uploads.id"), nullable=False, index=True)
    signal_type = Column(String(50), nullable=False, index=True)  # risk_score, assurance_score, anomaly_score, synthetic_likelihood, etc.
    value = Column(Numeric(10, 4), nullable=False)
    details_json = Column(JSON, nullable=True)  # Additional context, feature contributions, etc.
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant")
    upload = relationship("Upload", back_populates="risk_signals")

