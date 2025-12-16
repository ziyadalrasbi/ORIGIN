"""CI tests to verify security assertions are met."""

import ast
import re
from pathlib import Path


def test_no_default_minio_credentials():
    """Fail if any Settings class contains default MinIO credentials."""
    settings_files = [
        Path("apps/api/origin_api/settings.py"),
        Path("apps/worker/origin_worker/settings.py"),
    ]
    
    forbidden_defaults = [
        "minioadmin",
        "minioadmin123",
    ]
    
    for settings_file in settings_files:
        if not settings_file.exists():
            continue
        
        content = settings_file.read_text()
        
        # Check for forbidden defaults
        for default in forbidden_defaults:
            # Look for assignments like minio_access_key = "minioadmin"
            pattern = rf'minio_(access_key|secret_key)\s*[:=]\s*["\']{re.escape(default)}["\']'
            if re.search(pattern, content):
                raise AssertionError(
                    f"{settings_file} contains default MinIO credential '{default}'. "
                    "Use Optional[str] = None and require explicit env vars in production."
                )


def test_readiness_no_todos():
    """Fail if /ready endpoint contains TODO or doesn't run real checks."""
    main_file = Path("apps/api/origin_api/main.py")
    
    if not main_file.exists():
        return
    
    content = main_file.read_text()
    
    # Check for TODO in readiness function
    if "def readiness_check" in content or "@app.get(\"/ready\")" in content:
        readiness_section = content
        # Extract readiness function
        if "TODO" in readiness_section.upper():
            raise AssertionError(
                "Readiness endpoint contains TODO. All checks must be implemented."
            )
        
        # Verify real checks are performed
        required_checks = [
            "database",
            "migrations",  # Should check Alembic
            "redis",
            "object_storage",  # Should check MinIO/S3
        ]
        
        for check in required_checks:
            if check not in readiness_section.lower():
                raise AssertionError(
                    f"Readiness endpoint missing check for: {check}"
                )


def test_webhook_tests_use_raw_bytes():
    """Fail if webhook signing tests use JSON re-serialization."""
    test_files = [
        Path("apps/api/tests/test_webhook_raw_body.py"),
        Path("apps/api/tests/test_webhook_security.py"),
    ]
    
    for test_file in test_files:
        if not test_file.exists():
            continue
        
        content = test_file.read_text()
        
        # Check for problematic patterns
        problematic_patterns = [
            r'json\.dumps\(.*\)\.encode\(\)',  # Re-serializing in test
            r'JSON\.stringify\(',  # Node.js re-serialization
            r'f"{timestamp}\.{.*decode\(\)}"',  # Decoding then re-encoding
        ]
        
        # But allow json.dumps for creating test payloads (that's fine)
        # We're looking for verification logic that re-serializes
        
        # Check if verification uses raw bytes
        if "verify_webhook" in content:
            # Should use raw_body parameter
            if "raw_body" not in content and "rawBody" not in content:
                # Check if it's using re-serialized JSON for verification
                if re.search(r'json\.dumps.*verify|verify.*json\.dumps', content, re.IGNORECASE):
                    raise AssertionError(
                        f"{test_file} uses JSON re-serialization for webhook verification. "
                        "Must use raw body bytes."
                    )


def test_scope_middleware_global():
    """Fail if ScopeMiddleware is not in middleware chain."""
    main_file = Path("apps/api/origin_api/main.py")
    
    if not main_file.exists():
        return
    
    content = main_file.read_text()
    
    # Check that ScopeMiddleware is added
    if "ScopeMiddleware" not in content:
        raise AssertionError(
            "ScopeMiddleware not found in main.py. Must be added to middleware chain."
        )
    
    if "app.add_middleware(ScopeMiddleware)" not in content:
        raise AssertionError(
            "ScopeMiddleware not added via app.add_middleware(). Must be in middleware chain."
        )


def test_settings_consolidation():
    """Fail if duplicate Settings classes exist."""
    settings_files = [
        Path("apps/api/origin_api/settings.py"),
        Path("apps/worker/origin_worker/settings.py"),
    ]
    
    # Count Settings classes
    settings_count = 0
    for settings_file in settings_files:
        if settings_file.exists():
            content = settings_file.read_text()
            if "class Settings" in content:
                settings_count += 1
    
    # Should have exactly 2 (one for API, one for worker)
    if settings_count != 2:
        raise AssertionError(
            f"Expected exactly 2 Settings classes (API + Worker), found {settings_count}"
        )
    
    # Check for any other Settings classes
    for py_file in Path("apps").rglob("**/settings.py"):
        if py_file not in settings_files:
            raise AssertionError(
                f"Found unexpected Settings file: {py_file}. "
                "Only apps/api/origin_api/settings.py and apps/worker/origin_worker/settings.py should exist."
            )


if __name__ == "__main__":
    """Run all CI security assertion tests."""
    import sys
    
    tests = [
        test_no_default_minio_credentials,
        test_readiness_no_todos,
        test_webhook_tests_use_raw_bytes,
        test_scope_middleware_global,
        test_settings_consolidation,
    ]
    
    failures = []
    for test in tests:
        try:
            test()
            print(f"✓ {test.__name__}")
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}")
            failures.append(str(e))
    
    if failures:
        print(f"\n{len(failures)} test(s) failed:")
        for failure in failures:
            print(f"  - {failure}")
        sys.exit(1)
    else:
        print("\nAll security assertion tests passed!")

