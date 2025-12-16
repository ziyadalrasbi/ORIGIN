"""Account and identity models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from origin_api.db.base import Base


class Account(Base):
    """Account model for uploaders."""

    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    external_id = Column(String(255), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # user, organization, bot, etc.
    display_name = Column(String(255), nullable=True)
    risk_state = Column(String(50), default="unknown", nullable=False)  # unknown, clean, flagged, banned
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant")
    uploads = relationship("Upload", back_populates="account")
    device_fingerprints = relationship("DeviceFingerprint", back_populates="account")


class IdentityEntity(Base):
    """Identity entity model for KYA++ resolution."""

    __tablename__ = "identity_entities"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    entity_type = Column(String(50), nullable=False, index=True)  # account, device, network, org, person
    entity_key_hash = Column(String(255), nullable=False, index=True)
    attributes_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant")
    from_relationships = relationship(
        "IdentityRelationship",
        foreign_keys="IdentityRelationship.from_entity_id",
        back_populates="from_entity",
    )
    to_relationships = relationship(
        "IdentityRelationship",
        foreign_keys="IdentityRelationship.to_entity_id",
        back_populates="to_entity",
    )


class IdentityRelationship(Base):
    """Identity relationship model for graph features."""

    __tablename__ = "identity_relationships"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    from_entity_id = Column(Integer, ForeignKey("identity_entities.id"), nullable=False, index=True)
    to_entity_id = Column(Integer, ForeignKey("identity_entities.id"), nullable=False, index=True)
    relationship_type = Column(String(50), nullable=False)  # shared_device, shared_network, same_org, etc.
    weight = Column(Integer, default=1, nullable=False)
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant")
    from_entity = relationship("IdentityEntity", foreign_keys=[from_entity_id], back_populates="from_relationships")
    to_entity = relationship("IdentityEntity", foreign_keys=[to_entity_id], back_populates="to_relationships")


class DeviceFingerprint(Base):
    """Device fingerprint model."""

    __tablename__ = "device_fingerprints"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True, index=True)
    device_hash = Column(String(255), nullable=False, index=True)
    ip_hash = Column(String(255), nullable=True, index=True)
    user_agent_hash = Column(String(255), nullable=True)
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    tenant = relationship("Tenant")
    account = relationship("Account", back_populates="device_fingerprints")

