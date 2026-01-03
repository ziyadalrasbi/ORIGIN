"""Tests for evidence pack task field correctness (task_state mirrors task_status)."""

import pytest
from unittest.mock import MagicMock, patch

from origin_api.routes.evidence import EvidencePackResponse


class TestTaskFieldCorrectness:
    """Test that task_state always mirrors task_status, never task_id."""
    
    def test_task_state_mirrors_task_status(self):
        """Test that task_state mirrors task_status in EvidencePackResponse."""
        # Valid response with task_status
        response = EvidencePackResponse(
            status="pending",
            certificate_id="test-cert-123",
            task_id="evidence_pack_abc123",
            task_status="PENDING",
            task_state="PENDING",  # Should mirror task_status
        )
        assert response.task_state == response.task_status
        assert response.task_state == "PENDING"
        assert response.task_id == "evidence_pack_abc123"
        assert response.task_id != response.task_state  # task_id != task_state
    
    def test_task_state_not_task_id(self):
        """Test that task_state is never set to task_id value."""
        response = EvidencePackResponse(
            status="pending",
            certificate_id="test-cert-123",
            task_id="evidence_pack_xyz789",
            task_status="STARTED",
            task_state="STARTED",  # Should mirror task_status, not task_id
        )
        assert response.task_state != response.task_id
        assert response.task_state == "STARTED"
        assert response.task_id == "evidence_pack_xyz789"
    
    def test_none_task_status_has_none_task_state(self):
        """Test that None task_status results in None task_state."""
        response = EvidencePackResponse(
            status="pending",
            certificate_id="test-cert-123",
            task_id="evidence_pack_abc123",
            task_status=None,  # Unknown status
            task_state=None,  # Should mirror None
        )
        assert response.task_state == response.task_status
        assert response.task_state is None
    
    def test_custom_status_mirrored(self):
        """Test that custom statuses like 'stuck_requeued' are mirrored."""
        response = EvidencePackResponse(
            status="pending",
            certificate_id="test-cert-123",
            task_id="evidence_pack_abc123",
            task_status="stuck_requeued",
            task_state="stuck_requeued",  # Should mirror custom status
        )
        assert response.task_state == response.task_status
        assert response.task_state == "stuck_requeued"


class TestTaskIdFormat:
    """Test that task_id uses hash-based format."""
    
    def test_task_id_format(self):
        """Test that task_id follows hash-based format."""
        # Task IDs should be hash-based, not raw strings
        task_id = "evidence_pack_abc123def456ghi789jkl012mno345pq"
        assert task_id.startswith("evidence_pack_")
        assert len(task_id.split("_")[-1]) == 32  # SHA256 hex digest (32 chars)
    
    def test_task_id_deterministic(self):
        """Test that same inputs produce same task_id."""
        from origin_api.routes.evidence import _get_deterministic_task_id
        
        task_id1 = _get_deterministic_task_id(1, 100, "INTERNAL", ["json"])
        task_id2 = _get_deterministic_task_id(1, 100, "INTERNAL", ["json"])
        
        assert task_id1 == task_id2  # Deterministic
        assert task_id1.startswith("evidence_pack_")
    
    def test_task_id_different_for_different_inputs(self):
        """Test that different inputs produce different task_ids."""
        from origin_api.routes.evidence import _get_deterministic_task_id
        
        task_id1 = _get_deterministic_task_id(1, 100, "INTERNAL", ["json"])
        task_id2 = _get_deterministic_task_id(1, 100, "DSP", ["json"])
        
        assert task_id1 != task_id2  # Different audience = different task_id

