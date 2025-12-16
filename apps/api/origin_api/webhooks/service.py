"""Webhook delivery service with retries and DLQ."""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from origin_api.models import Webhook, WebhookDelivery
from origin_api.security.encryption import get_encryption_service
from origin_api.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


class WebhookService:
    """Webhook delivery service with retries and DLQ."""

    def __init__(self, db: Session):
        """Initialize webhook service."""
        self.db = db
        self.encryption_service = get_encryption_service()

    def _decrypt_secret(self, webhook: Webhook) -> str:
        """Decrypt webhook secret."""
        ciphertext_data = {
            "ciphertext": webhook.secret_ciphertext,
            "key_id": webhook.secret_key_id,
            "encryption_context": webhook.encryption_context or {},
        }
        return self.encryption_service.decrypt(ciphertext_data)

    def _compute_signature(self, payload: bytes, secret: str, timestamp: str) -> str:
        """Compute HMAC signature for webhook payload with replay protection."""
        # Sign: timestamp + "." + body
        message = f"{timestamp}.{payload.decode()}"
        return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    def deliver_webhook(
        self,
        tenant_id: int,
        event_type: str,
        payload: dict,
    ) -> None:
        """Enqueue webhook delivery (does not perform HTTP calls)."""
        # This method only enqueues - actual delivery is done by worker
        # Enqueue via Celery task
        try:
            from origin_worker.tasks import deliver_webhook
            
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

                # Enqueue delivery task with correlation ID
                correlation_id = payload.get("correlation_id")
                deliver_webhook.delay(webhook.id, event_type, payload, correlation_id)
        except Exception as e:
            logger.warning(f"Failed to enqueue webhook delivery: {e}", exc_info=True)

    def _attempt_delivery(
        self, webhook: Webhook, delivery: WebhookDelivery, payload: dict
    ) -> None:
        """Attempt to deliver webhook (called by worker)."""
        # Decrypt secret
        try:
            secret = self._decrypt_secret(webhook)
        except Exception as e:
            logger.error(f"Failed to decrypt webhook secret for webhook {webhook.id}: {e}")
            delivery.status = "failed"
            delivery.response_body = f"Secret decryption failed: {e}"
            self.db.commit()
            return

        # Serialize payload deterministically
        payload_bytes = json.dumps(payload, sort_keys=True).encode()

        # Generate timestamp for replay protection
        timestamp = str(int(datetime.utcnow().timestamp()))

        # Compute signature with replay protection
        signature = self._compute_signature(payload_bytes, secret, timestamp)

        # Get correlation_id and event_id from payload
        correlation_id = payload.get("correlation_id", "")
        event_id = str(delivery.id)

        # Prepare headers
        headers = {
            "Content-Type": "application/json",
            "X-Origin-Signature": f"sha256={signature}",
            "X-Origin-Event": delivery.event_type,
            "X-Origin-Correlation-Id": correlation_id,
            "X-Origin-Event-Id": event_id,
            "X-Origin-Timestamp": timestamp,
        }

        # Make request
        try:
            with httpx.Client(timeout=settings.webhook_timeout_seconds) as client:
                response = client.post(webhook.url, json=payload, headers=headers)

                delivery.response_status = response.status_code
                delivery.response_body = response.text[:1000]  # Truncate

                if 200 <= response.status_code < 300:
                    delivery.status = "success"
                    delivery.delivered_at = datetime.utcnow()
                else:
                    delivery.status = "failed"
                    # Retry will be handled by Celery retry mechanism
        except Exception as e:
            logger.error(f"Webhook delivery failed for webhook {webhook.id}: {e}")
            delivery.status = "failed"
            delivery.response_body = str(e)[:1000]

        self.db.commit()

    def create_webhook(
        self, tenant_id: int, url: str, secret: str, events: list[str]
    ) -> Webhook:
        """Create a new webhook with encrypted secret."""
        # Encrypt secret
        encryption_result = self.encryption_service.encrypt(
            secret, encryption_context={"tenant_id": str(tenant_id)}
        )

        webhook = Webhook(
            tenant_id=tenant_id,
            url=url,
            secret_ciphertext=encryption_result["ciphertext"],
            secret_key_id=encryption_result["key_id"],
            secret_version="1",
            encryption_context=encryption_result.get("encryption_context"),
            events=events,
            enabled=True,
            created_at=datetime.utcnow(),
            rotated_at=datetime.utcnow(),
        )
        self.db.add(webhook)
        self.db.commit()
        self.db.refresh(webhook)
        return webhook

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
