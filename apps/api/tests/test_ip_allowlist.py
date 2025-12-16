"""Tests for IP allowlist fail-closed behavior."""

import json
import pytest
from unittest.mock import patch

from origin_api.middleware.auth import AuthMiddleware
from origin_api.settings import get_settings


class TestIPAllowlist:
    """Test IP allowlist validation."""

    def test_valid_cidr_allow(self):
        """Test that valid CIDR allows access."""
        middleware = AuthMiddleware(None)
        allowlist = json.dumps(["192.168.1.0/24", "10.0.0.0/8"])
        
        # IP in CIDR range
        assert middleware._check_ip_allowlist("192.168.1.100", allowlist) is True
        assert middleware._check_ip_allowlist("10.0.0.1", allowlist) is True
        
        # IP not in range
        assert middleware._check_ip_allowlist("172.16.0.1", allowlist) is False

    def test_exact_ip_allow(self):
        """Test that exact IP match allows access."""
        middleware = AuthMiddleware(None)
        allowlist = json.dumps(["192.168.1.100", "10.0.0.1"])
        
        assert middleware._check_ip_allowlist("192.168.1.100", allowlist) is True
        assert middleware._check_ip_allowlist("10.0.0.1", allowlist) is True
        assert middleware._check_ip_allowlist("192.168.1.101", allowlist) is False

    @patch("origin_api.middleware.auth.get_settings")
    def test_invalid_json_production_denies(self, mock_get_settings):
        """Test that invalid JSON in production denies access (fail-closed)."""
        mock_settings = get_settings()
        mock_settings.environment = "production"
        mock_settings.ip_allowlist_fail_open = False
        mock_get_settings.return_value = mock_settings
        
        middleware = AuthMiddleware(None)
        
        # Invalid JSON
        invalid_json = "{invalid json}"
        assert middleware._check_ip_allowlist("192.168.1.1", invalid_json) is False
        
        # Not a list
        not_list = json.dumps({"ips": ["192.168.1.1"]})
        assert middleware._check_ip_allowlist("192.168.1.1", not_list) is False

    @patch("origin_api.middleware.auth.get_settings")
    def test_invalid_json_development_allows(self, mock_get_settings):
        """Test that invalid JSON in development allows access (fail-open)."""
        mock_settings = get_settings()
        mock_settings.environment = "development"
        mock_settings.ip_allowlist_fail_open = True
        mock_get_settings.return_value = mock_settings
        
        middleware = AuthMiddleware(None)
        
        # Invalid JSON - should allow in dev
        invalid_json = "{invalid json}"
        assert middleware._check_ip_allowlist("192.168.1.1", invalid_json) is True

