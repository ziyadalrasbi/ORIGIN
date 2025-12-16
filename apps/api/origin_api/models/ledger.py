"""Audit ledger models."""

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from origin_api.db.base import Base


class TenantSequence(Base):
    """Per-tenant sequence counter for deterministic ordering."""

    __tablename__ = "tenant_sequences"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), primary_key=True, index=True)
    last_sequence = Column(BigInteger, default=0, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class LedgerEvent(Base):
    """Append-only audit ledger with hash chaining."""

    __tablename__ = "ledger_events"

    id = Column(Integer, primary_key=True, index=True)
    event_hash = Column(String(255), nullable=False, unique=True, index=True)
    previous_event_hash = Column(String(255), nullable=True, index=True)  # NULL for first event
    correlation_id = Column(String(255), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    tenant_sequence = Column(BigInteger, nullable=False, index=True)  # Monotonic per tenant
    event_type = Column(String(100), nullable=False, index=True)  # ingest, decision, override, etc.
    event_timestamp = Column(DateTime, nullable=False, index=True)  # Fixed timestamp
    payload_json = Column(JSON, nullable=False)
    canonical_event_json = Column(JSON, nullable=False)  # Exact object that was hashed
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    tenant = relationship("Tenant")

    # Unique constraint per tenant sequence
    __table_args__ = (
        UniqueConstraint("tenant_id", "tenant_sequence", name="uq_ledger_tenant_sequence"),
    )
