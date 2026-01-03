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
    
    # Verify deprecated router is NOT imported
    import origin_api.main
    assert "_deprecated_evidence_old" not in str(origin_api.main.__file__)
    
    # Check that no routes come from deprecated module
    for route in evidence_routes:
        # Route should come from evidence.py, not deprecated module
        route_module = getattr(route, "__module__", "")
        assert "_deprecated" not in route_module.lower()


def test_evidence_old_module_raises_error():
    """Test that deprecated evidence_old module raises RuntimeError on import."""
    with pytest.raises(RuntimeError, match="deprecated"):
        import origin_api.routes._deprecated_evidence_old_do_not_use  # noqa: F401


def test_main_imports_only_active_evidence_router():
    """Test that main.py only imports the active evidence router."""
    import origin_api.main
    import inspect
    
    # Get source code of main.py
    main_source = inspect.getsource(origin_api.main)
    
    # Should import evidence router
    assert "from origin_api.routes import" in main_source or "import evidence" in main_source
    
    # Should NOT import deprecated router
    assert "_deprecated_evidence_old" not in main_source
    assert "evidence_old" not in main_source

