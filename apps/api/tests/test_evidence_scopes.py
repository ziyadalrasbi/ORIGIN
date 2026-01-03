"""Unit tests for evidence pack scope parsing and audience enforcement."""

import json
from unittest.mock import MagicMock

import pytest

from origin_api.evidence.scopes import (
    determine_audience_from_scopes,
    enforce_audience_access,
    get_api_key_scopes,
)
from origin_api.models import APIKey
from fastapi import Request, HTTPException


class TestScopeParsing:
    """Test scope parsing from API key objects."""
    
    def test_scopes_as_json_string(self):
        """Test parsing scopes stored as JSON string."""
        request = MagicMock(spec=Request)
        api_key_obj = MagicMock(spec=APIKey)
        api_key_obj.scopes = json.dumps(["evidence:request:internal", "evidence:download:internal"])
        request.state.api_key_obj = api_key_obj
        
        scopes = get_api_key_scopes(request)
        assert scopes == ["evidence:request:internal", "evidence:download:internal"]
    
    def test_scopes_as_list(self):
        """Test parsing scopes stored as list."""
        request = MagicMock(spec=Request)
        api_key_obj = MagicMock(spec=APIKey)
        api_key_obj.scopes = ["evidence:request:dsp", "evidence:download:dsp"]
        request.state.api_key_obj = api_key_obj
        
        scopes = get_api_key_scopes(request)
        assert scopes == ["evidence:request:dsp", "evidence:download:dsp"]
    
    def test_invalid_json_returns_empty_list(self):
        """Test that invalid JSON returns empty list with warning."""
        request = MagicMock(spec=Request)
        api_key_obj = MagicMock(spec=APIKey)
        api_key_obj.scopes = "{invalid json"
        api_key_obj.id = 123
        request.state.api_key_obj = api_key_obj
        
        scopes = get_api_key_scopes(request)
        assert scopes == []
    
    def test_missing_api_key_obj_returns_empty_list(self):
        """Test that missing api_key_obj returns empty list."""
        request = MagicMock(spec=Request)
        delattr(request.state, "api_key_obj")
        
        scopes = get_api_key_scopes(request)
        assert scopes == []
    
    def test_none_scopes_returns_empty_list(self):
        """Test that None scopes returns empty list."""
        request = MagicMock(spec=Request)
        api_key_obj = MagicMock(spec=APIKey)
        api_key_obj.scopes = None
        request.state.api_key_obj = api_key_obj
        
        scopes = get_api_key_scopes(request)
        assert scopes == []


class TestAudienceDetermination:
    """Test audience determination from scopes."""
    
    def test_dsp_scope_returns_dsp(self):
        """Test that DSP scope returns DSP audience."""
        scopes = ["evidence:request:dsp"]
        audience = determine_audience_from_scopes(scopes)
        assert audience == "DSP"
    
    def test_regulator_scope_returns_regulator(self):
        """Test that REGULATOR scope returns REGULATOR audience."""
        scopes = ["evidence:request:regulator"]
        audience = determine_audience_from_scopes(scopes)
        assert audience == "REGULATOR"
    
    def test_internal_scope_returns_internal(self):
        """Test that INTERNAL scope returns INTERNAL audience."""
        scopes = ["evidence:request:internal"]
        audience = determine_audience_from_scopes(scopes)
        assert audience == "INTERNAL"
    
    def test_no_scope_defaults_to_internal(self):
        """Test that no evidence scope defaults to INTERNAL."""
        scopes = []
        audience = determine_audience_from_scopes(scopes)
        assert audience == "INTERNAL"
    
    def test_multiple_scopes_prioritizes_dsp(self):
        """Test that multiple scopes prioritize DSP > REGULATOR > INTERNAL."""
        scopes = ["evidence:request:internal", "evidence:request:regulator", "evidence:request:dsp"]
        audience = determine_audience_from_scopes(scopes)
        assert audience == "DSP"


class TestAudienceEnforcement:
    """Test audience access enforcement."""
    
    def test_dsp_cannot_access_internal(self):
        """Test that DSP scope cannot access INTERNAL evidence."""
        scopes = ["evidence:request:dsp"]
        with pytest.raises(HTTPException) as exc_info:
            enforce_audience_access("request", scopes, "DSP", "INTERNAL")
        assert exc_info.value.status_code == 403
    
    def test_internal_can_access_internal(self):
        """Test that INTERNAL scope can access INTERNAL evidence."""
        scopes = ["evidence:request:internal"]
        # Should not raise
        enforce_audience_access("request", scopes, "INTERNAL", "INTERNAL")
    
    def test_dsp_can_access_dsp(self):
        """Test that DSP scope can access DSP evidence."""
        scopes = ["evidence:request:dsp"]
        # Should not raise
        enforce_audience_access("request", scopes, "DSP", "DSP")
    
    def test_missing_required_scope_raises(self):
        """Test that missing required scope raises 403."""
        scopes = []
        with pytest.raises(HTTPException) as exc_info:
            enforce_audience_access("request", scopes, "INTERNAL")
        assert exc_info.value.status_code == 403

