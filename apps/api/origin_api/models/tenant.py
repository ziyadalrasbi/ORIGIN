"""Tenant and API key models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from origin_api.db.base import Base


class Tenant(Base):
    """Tenant model for multi-tenancy."""

    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    label = Column(String(255), nullable=False, unique=True, index=True)
    api_key_hash = Column(String(255), nullable=False, unique=True, index=True)
    rotated_at = Column(DateTime, nullable=True)
    policy_profile_id = Column(Integer, ForeignKey("policy_profiles.id"), nullable=True)
    status = Column(String(50), default="active", nullable=False)  # active, suspended, deleted
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    api_keys = relationship("APIKey", back_populates="tenant", cascade="all, delete-orphan")
    policy_profile = relationship("PolicyProfile", back_populates="tenants", foreign_keys=[policy_profile_id])


class APIKey(Base):
    """API key model for tenant authentication."""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    hash = Column(String(255), nullable=False, unique=True, index=True)
    label = Column(String(255), nullable=True)
    scopes = Column(Text, nullable=True)  # JSON array of scopes
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    tenant = relationship("Tenant", back_populates="api_keys")

