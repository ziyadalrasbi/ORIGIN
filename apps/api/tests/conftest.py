"""Pytest configuration and fixtures for integration tests."""

import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from origin_api.db.base import Base
from origin_api.models import Tenant, APIKey, PolicyProfile


# Use test database URL from environment or default to SQLite in-memory
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "sqlite:///:memory:"
)


@pytest.fixture(scope="function")
def db():
    """
    Create a test database session.
    
    For integration tests, use TEST_DATABASE_URL environment variable
    to point to a real PostgreSQL instance (e.g., from docker-compose.test.yml).
    """
    if TEST_DATABASE_URL.startswith("sqlite"):
        # SQLite in-memory for fast unit tests
        engine = create_engine(
            TEST_DATABASE_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        # PostgreSQL for integration tests
        engine = create_engine(TEST_DATABASE_URL)
    
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def test_tenant(db: Session) -> Tenant:
    """Create a test tenant."""
    tenant = Tenant(
        label="test-tenant",
        api_key_hash="test-hash",
        status="active",
    )
    db.add(tenant)
    db.flush()
    return tenant


@pytest.fixture
def test_api_key(db: Session, test_tenant: Tenant) -> APIKey:
    """Create a test API key with scopes."""
    api_key = APIKey(
        tenant_id=test_tenant.id,
        hash="hashed-test-key",
        label="test-key",
        scopes=json.dumps(["evidence:request:internal", "evidence:download:internal"]),
        is_active=True,
    )
    db.add(api_key)
    db.commit()
    return api_key


@pytest.fixture
def test_policy_profile(db: Session, test_tenant: Tenant) -> PolicyProfile:
    """Create a test policy profile."""
    profile = PolicyProfile(
        tenant_id=test_tenant.id,
        name="test-policy",
        version="v1.0",
        thresholds_json={
            "risk_threshold_review": 40,
            "risk_threshold_quarantine": 70,
            "risk_threshold_reject": 90,
        },
        is_active=True,
    )
    db.add(profile)
    db.commit()
    return profile

