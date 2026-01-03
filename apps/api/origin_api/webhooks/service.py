"""Webhook delivery service."""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from origin_api.models import Webhook, WebhookDelivery
from origin_api.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class WebhookService:
    """Webhook delivery service with retries and DLQ."""

    def __init__(self, db: Session):
        """Initialize webhook service."""
        self.db = db

    def _compute_signature(self, payload: bytes, secret: str) -> str:
        """Compute HMAC signature for webhook payload."""
        return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    def deliver_webhook(
        self,
        tenant_id: int,
        event_type: str,
        payload: dict,
    ) -> None:
        """Deliver webhook to all configured endpoints for event type."""
        webhooks = (
            self.db.query(Webhook)
            .filter(
                Webhook.tenant_id == tenant_id,
                Webhook.enabled == True,  # noqa: E712
            )
            .all()
        )

        for webhook in webhooks:
            # Check if webhook subscribes to this event
            if event_type not in (webhook.events or []):
                continue

            # Create delivery record
            delivery = WebhookDelivery(
                webhook_id=webhook.id,
                event_type=event_type,
                payload_json=payload,
                status="pending",
                attempt_number=1,
            )
            self.db.add(delivery)
            self.db.flush()

            # Attempt delivery
            try:
                self._attempt_delivery(webhook, delivery, payload)
            except Exception as e:
                logger.exception(f"Error delivering webhook {webhook.id}: {e}")
                delivery.status = "failed"
                delivery.response_body = str(e)
                self.db.commit()

    def _attempt_delivery(
        self, webhook: Webhook, delivery: WebhookDelivery, payload: dict
    ) -> None:
        """Attempt to deliver webhook."""
        # Serialize payload
        payload_bytes = json.dumps(payload).encode()

        # Compute signature (in production, retrieve secret from secure storage)
        # For MVP, we'll use a placeholder
        signature = self._compute_signature(payload_bytes, "webhook_secret")

        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "X-ORIGIN-Signature": f"sha256={signature}",
            "X-ORIGIN-Event": delivery.event_type,
        }

        # Make request
        with httpx.Client(timeout=settings.webhook_timeout_seconds) as client:
            response = client.post(webhook.url, json=payload, headers=headers)

            delivery.response_status = response.status_code
            delivery.response_body = response.text[:1000]  # Truncate

            if 200 <= response.status_code < 300:
                delivery.status = "success"
                delivery.delivered_at = datetime.utcnow()
            else:
                delivery.status = "failed"
                # Schedule retry if under max attempts
                if delivery.attempt_number < settings.webhook_max_retries:
                    delivery.status = "retrying"
                    delivery.attempt_number += 1
                    delivery.next_retry_at = datetime.utcnow() + timedelta(
                        minutes=2 ** delivery.attempt_number
                    )  # Exponential backoff

        self.db.commit()

    def process_retries(self) -> None:
        """Process pending webhook retries."""
        retries = (
            self.db.query(WebhookDelivery)
            .filter(
                WebhookDelivery.status == "retrying",
                WebhookDelivery.next_retry_at <= datetime.utcnow(),
            )
            .all()
        )

        for delivery in retries:
            webhook = self.db.query(Webhook).filter(Webhook.id == delivery.webhook_id).first()
            if webhook:
                try:
                    self._attempt_delivery(webhook, delivery, delivery.payload_json)
                except Exception as e:
                    logger.exception(f"Error retrying webhook {delivery.id}: {e}")

    def get_dlq_events(self, tenant_id: int, limit: int = 100) -> list[WebhookDelivery]:
        """Get dead-letter queue events (failed after max retries)."""
        return (
            self.db.query(WebhookDelivery)
            .join(Webhook)
            .filter(
                Webhook.tenant_id == tenant_id,
                WebhookDelivery.status == "failed",
                WebhookDelivery.attempt_number >= settings.webhook_max_retries,
            )
            .limit(limit)
            .all()
        )

