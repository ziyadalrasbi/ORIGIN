"""Tests for evidence pack routes - verify only one router is registered."""

import pytest
from fastapi.testclient import TestClient

from origin_api.main import app


def test_only_one_evidence_router_registered():
    """Test that only one evidence router is registered and paths are correct."""
    # Get all routes
    routes = [route for route in app.routes if hasattr(route, "path")]
    
    # Find evidence pack routes
    evidence_routes = [r for r in routes if "/evidence-packs" in r.path]
    
    # Should have routes from evidence.py only
    assert len(evidence_routes) > 0
    
    # Verify paths are correct
    evidence_paths = [r.path for r in evidence_routes]
    assert "/v1/evidence-packs" in evidence_paths
    
    # Verify no duplicate routes
    assert len(set(evidence_paths)) == len(evidence_paths)


def test_evidence_old_module_raises_error():
    """Test that deprecated evidence_old module raises RuntimeError on import."""
    with pytest.raises(RuntimeError, match="deprecated"):
        import origin_api.routes._deprecated_evidence_old_do_not_use  # noqa: F401

