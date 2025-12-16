"""Tests for ledger chain verification."""

import pytest
from sqlalchemy.orm import Session

from origin_api.db.session import SessionLocal
from origin_api.ledger.service import LedgerService
from origin_api.models import Tenant


@pytest.fixture
def db():
    """Get database session."""
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture
def test_tenant(db: Session):
    """Create test tenant."""
    tenant = Tenant(label="test_ledger", status="active")
    db.add(tenant)
    db.commit()
    return tenant


def test_ledger_chain_valid(db: Session, test_tenant):
    """Test that valid chain passes verification."""
    service = LedgerService(db)

    # Append events
    service.append_event(
        test_tenant.id, "corr-1", "test.event", {"data": "event1"}
    )
    service.append_event(
        test_tenant.id, "corr-2", "test.event", {"data": "event2"}
    )
    service.append_event(
        test_tenant.id, "corr-3", "test.event", {"data": "event3"}
    )

    # Verify chain
    is_valid, error = service.verify_chain(test_tenant.id)
    assert is_valid, f"Chain should be valid: {error}"


def test_ledger_chain_tampered_fails(db: Session, test_tenant):
    """Test that tampered chain fails verification."""
    service = LedgerService(db)

    # Append event
    event = service.append_event(
        test_tenant.id, "corr-1", "test.event", {"data": "original"}
    )

    # Tamper with payload
    event.payload_json["tampered"] = True
    db.commit()

    # Verify should fail
    is_valid, error = service.verify_chain(test_tenant.id)
    assert not is_valid, "Tampered chain should fail verification"
    assert error is not None

