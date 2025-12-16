"""Webhook models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from origin_api.db.base import Base


class Webhook(Base):
    """Webhook configuration model."""

    __tablename__ = "webhooks"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    url = Column(Text, nullable=False)
    secret_ciphertext = Column(Text, nullable=False)  # Encrypted webhook secret
    secret_key_id = Column(String(255), nullable=False)  # KMS key ID or "local"
    secret_version = Column(String(100), nullable=True)  # Secret version for rotation
    encryption_context = Column(JSON, nullable=True)  # KMS encryption context
    events = Column(JSON, nullable=False)  # ["decision.created", "decision.updated", etc.]
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    rotated_at = Column(DateTime, nullable=True)

    # Relationships
    tenant = relationship("Tenant")
    deliveries = relationship("WebhookDelivery", back_populates="webhook", cascade="all, delete-orphan")


class WebhookDelivery(Base):
    """Webhook delivery attempt model."""

    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True, index=True)
    webhook_id = Column(Integer, ForeignKey("webhooks.id"), nullable=False, index=True)
    event_type = Column(String(100), nullable=False)
    payload_json = Column(JSON, nullable=False)
    status = Column(String(50), nullable=False, index=True)  # pending, success, failed, retrying
    response_status = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    attempt_number = Column(Integer, default=1, nullable=False)
    next_retry_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    webhook = relationship("Webhook", back_populates="deliveries")

