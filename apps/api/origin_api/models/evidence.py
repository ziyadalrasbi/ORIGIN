"""Evidence pack models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from origin_api.db.base import Base


class EvidencePack(Base):
    """Evidence pack model for decision artifacts.
    
    Evidence packs are immutable snapshots tied to the decision moment.
    The canonical_json field stores the EvidencePackV2 JSON snapshot at decision time,
    ensuring that evidence packs never drift from the original decision state.
    """

    __tablename__ = "evidence_packs"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    certificate_id = Column(Integer, ForeignKey("decision_certificates.id"), nullable=False, index=True)
    status = Column(String(50), default="pending", nullable=False, index=True)  # pending, processing, ready, failed
    formats = Column(JSON, nullable=True)  # ["json", "pdf", "html"]
    storage_refs = Column(JSON, nullable=True)  # {"json": "s3://...", "pdf": "s3://...", "html": "s3://..."}
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    ready_at = Column(DateTime, nullable=True)
    
    # Immutability fields
    canonical_json = Column(JSON, nullable=True)  # Immutable EvidencePackV2 JSON snapshot (audience=INTERNAL)
    evidence_hash = Column(String(64), nullable=True, index=True)  # SHA256 hash of canonical_json
    evidence_version = Column(String(50), nullable=True, server_default="origin-evidence-v2")  # Schema version
    canonical_created_at = Column(DateTime, nullable=True)  # When canonical snapshot was created

    # Relationships
    tenant = relationship("Tenant")
    certificate = relationship("DecisionCertificate", back_populates="evidence_packs")

