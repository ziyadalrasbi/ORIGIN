"""Audit ledger models."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from origin_api.db.base import Base


class LedgerEvent(Base):
    """Append-only audit ledger with hash chaining."""

    __tablename__ = "ledger_events"

    id = Column(Integer, primary_key=True, index=True)
    event_hash = Column(String(255), nullable=False, unique=True, index=True)
    previous_event_hash = Column(String(255), nullable=True, index=True)  # NULL for first event
    correlation_id = Column(String(255), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)  # ingest, decision, override, etc.
    payload_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    tenant = relationship("Tenant")

