"""Audit ledger service with hash chaining."""

import hashlib
import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from origin_api.models import LedgerEvent


class LedgerService:
    """Tamper-evident audit ledger with hash chaining."""

    def __init__(self, db: Session):
        """Initialize ledger service."""
        self.db = db

    def _hash_event(self, event_data: dict) -> str:
        """Compute hash of event data."""
        # Create deterministic JSON representation
        event_str = json.dumps(event_data, sort_keys=True)
        return hashlib.sha256(event_str.encode()).hexdigest()

    def _get_last_event_hash(self, tenant_id: int) -> Optional[str]:
        """Get hash of last event for tenant."""
        last_event = (
            self.db.query(LedgerEvent)
            .filter(LedgerEvent.tenant_id == tenant_id)
            .order_by(LedgerEvent.created_at.desc())
            .first()
        )
        return last_event.event_hash if last_event else None

    def append_event(
        self,
        tenant_id: int,
        correlation_id: str,
        event_type: str,
        payload: dict,
    ) -> LedgerEvent:
        """Append event to ledger with hash chaining."""
        # Get previous event hash
        previous_hash = self._get_last_event_hash(tenant_id)

        # Create event data
        event_data = {
            "tenant_id": tenant_id,
            "correlation_id": correlation_id,
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Compute event hash
        event_hash = self._hash_event(event_data)

        # Create ledger event
        ledger_event = LedgerEvent(
            event_hash=event_hash,
            previous_event_hash=previous_hash,
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            event_type=event_type,
            payload_json=payload,
        )

        self.db.add(ledger_event)
        self.db.flush()

        return ledger_event

    def verify_chain(self, tenant_id: int) -> bool:
        """Verify hash chain integrity for tenant."""
        events = (
            self.db.query(LedgerEvent)
            .filter(LedgerEvent.tenant_id == tenant_id)
            .order_by(LedgerEvent.created_at.asc())
            .all()
        )

        if not events:
            return True

        previous_hash = None
        for event in events:
            # Verify previous hash matches
            if event.previous_event_hash != previous_hash:
                return False

            # Verify event hash
            event_data = {
                "tenant_id": event.tenant_id,
                "correlation_id": event.correlation_id,
                "event_type": event.event_type,
                "payload": event.payload_json,
                "previous_hash": event.previous_event_hash,
                "timestamp": event.created_at.isoformat(),
            }
            computed_hash = self._hash_event(event_data)
            if computed_hash != event.event_hash:
                return False

            previous_hash = event.event_hash

        return True

