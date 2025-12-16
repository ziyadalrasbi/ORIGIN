"""Audit ledger service with hash chaining."""

import hashlib
import json
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from origin_api.models import LedgerEvent, TenantSequence


class LedgerService:
    """Tamper-evident audit ledger with hash chaining."""

    def __init__(self, db: Session):
        """Initialize ledger service."""
        self.db = db

    def _allocate_sequence(self, tenant_id: int) -> int:
        """Allocate next sequence number for tenant (thread-safe)."""
        # Use SELECT FOR UPDATE to lock the row
        seq_row = (
            self.db.query(TenantSequence)
            .filter(TenantSequence.tenant_id == tenant_id)
            .with_for_update()
            .first()
        )

        if not seq_row:
            seq_row = TenantSequence(tenant_id=tenant_id, last_sequence=0)
            self.db.add(seq_row)
            self.db.flush()

        seq_row.last_sequence += 1
        sequence = seq_row.last_sequence
        self.db.flush()
        return sequence

    def _hash_canonical_event(self, canonical_event: dict) -> str:
        """Compute hash of canonical event JSON."""
        # Create deterministic JSON (sorted keys, no whitespace)
        event_str = json.dumps(canonical_event, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(event_str.encode()).hexdigest()

    def append_event(
        self,
        tenant_id: int,
        correlation_id: str,
        event_type: str,
        payload: dict,
    ) -> LedgerEvent:
        """Append event to ledger with hash chaining."""
        # Allocate sequence number (thread-safe)
        tenant_sequence = self._allocate_sequence(tenant_id)

        # Get previous event hash
        previous_hash = self._get_last_event_hash(tenant_id)

        # Set fixed timestamp
        event_timestamp = datetime.utcnow()

        # Build canonical event JSON (exact structure that will be hashed)
        canonical_event = {
            "tenant_id": tenant_id,
            "tenant_sequence": tenant_sequence,
            "correlation_id": correlation_id,
            "event_type": event_type,
            "payload": payload,
            "previous_event_hash": previous_hash,
            "event_timestamp": event_timestamp.isoformat(),
        }

        # Compute hash from canonical event only
        event_hash = self._hash_canonical_event(canonical_event)

        # Create ledger event
        ledger_event = LedgerEvent(
            event_hash=event_hash,
            previous_event_hash=previous_hash,
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            tenant_sequence=tenant_sequence,
            event_type=event_type,
            event_timestamp=event_timestamp,
            payload_json=payload,
            canonical_event_json=canonical_event,
        )

        self.db.add(ledger_event)
        self.db.flush()

        return ledger_event

    def _get_last_event_hash(self, tenant_id: int) -> Optional[str]:
        """Get hash of last event for tenant."""
        last_event = (
            self.db.query(LedgerEvent)
            .filter(LedgerEvent.tenant_id == tenant_id)
            .order_by(LedgerEvent.tenant_sequence.desc())
            .first()
        )
        return last_event.event_hash if last_event else None

    def verify_chain(self, tenant_id: int) -> tuple[bool, Optional[str]]:
        """Verify hash chain integrity for tenant.
        
        Returns:
            (is_valid, error_message)
        """
        events = (
            self.db.query(LedgerEvent)
            .filter(LedgerEvent.tenant_id == tenant_id)
            .order_by(LedgerEvent.tenant_sequence.asc())
            .all()
        )

        if not events:
            return True, None

        previous_hash = None
        expected_sequence = 1

        for event in events:
            # Verify sequence is monotonic
            if event.tenant_sequence != expected_sequence:
                return False, f"Sequence mismatch: expected {expected_sequence}, got {event.tenant_sequence}"

            # Verify previous hash links
            if event.previous_event_hash != previous_hash:
                return False, f"Previous hash mismatch at sequence {event.tenant_sequence}"

            # Verify event hash matches canonical event
            computed_hash = self._hash_canonical_event(event.canonical_event_json)
            if computed_hash != event.event_hash:
                return False, f"Hash mismatch at sequence {event.tenant_sequence}"

            previous_hash = event.event_hash
            expected_sequence += 1

        return True, None
