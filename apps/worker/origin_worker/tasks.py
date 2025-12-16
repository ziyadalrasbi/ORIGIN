"""Celery tasks for async operations."""

import logging
import sys
from typing import Optional

from celery import Task
from sqlalchemy.orm import Session

# Add parent directory to path for imports
sys.path.insert(0, "/app")

from origin_worker.celery_app import celery_app
from origin_worker.db import get_db

logger = logging.getLogger(__name__)


class DatabaseTask(Task):
    """Task with database session."""

    _db: Optional[Session] = None

    @property
    def db(self) -> Session:
        """Get database session."""
        if self._db is None:
            self._db = next(get_db())
        return self._db

    def after_return(self, *args, **kwargs):
        """Close database session after task."""
        if self._db:
            self._db.close()
            self._db = None


@celery_app.task(base=DatabaseTask, bind=True, max_retries=3)
def generate_evidence_pack(self, certificate_id: str, formats: list[str], correlation_id: Optional[str] = None):
    """Generate evidence pack asynchronously."""
    from origin_api.evidence.generator import EvidencePackGenerator
    from origin_api.models import DecisionCertificate, EvidencePack, Upload
    from origin_api.storage.s3 import S3Storage

    db = self.db
    storage = S3Storage()
    evidence_pack = None
    
    # Structured logging with correlation ID
    log_extra = {
        "task": "generate_evidence_pack",
        "certificate_id": certificate_id,
        "correlation_id": correlation_id,
    }

    try:
        # Get certificate
        certificate = (
            db.query(DecisionCertificate)
            .filter(DecisionCertificate.certificate_id == certificate_id)
            .first()
        )

        if not certificate:
            logger.error(f"Certificate {certificate_id} not found")
            return

        # Get upload
        upload = db.query(Upload).filter(Upload.id == certificate.upload_id).first()
        if not upload:
            logger.error(f"Upload not found for certificate {certificate_id}")
            return

        # Get or create evidence pack
        evidence_pack = (
            db.query(EvidencePack)
            .filter(EvidencePack.certificate_id == certificate.id)
            .first()
        )

        if not evidence_pack:
            evidence_pack = EvidencePack(
                tenant_id=certificate.tenant_id,
                certificate_id=certificate.id,
                status="processing",
                formats=formats,
            )
            db.add(evidence_pack)
            db.flush()

        # Generate artifacts
        generator = EvidencePackGenerator(db)
        artifacts = {}
        storage_keys = {}
        artifact_hashes = {}
        artifact_sizes = {}

        if "json" in formats:
            json_data = generator.generate_json(certificate, upload)
            import json as json_lib
            json_bytes = json_lib.dumps(json_data).encode()
            object_key = f"evidence/{certificate_id}/evidence.json"
            result = storage.upload_object(object_key, json_bytes, "application/json")
            storage_keys["json"] = result["key"]
            artifact_hashes["json"] = result["hash"]
            artifact_sizes["json"] = result["size"]

        if "pdf" in formats:
            pdf_data = generator.generate_pdf(certificate, upload)
            object_key = f"evidence/{certificate_id}/evidence.pdf"
            result = storage.upload_object(object_key, pdf_data, "application/pdf")
            storage_keys["pdf"] = result["key"]
            artifact_hashes["pdf"] = result["hash"]
            artifact_sizes["pdf"] = result["size"]

        if "html" in formats:
            html_data = generator.generate_html(certificate, upload).encode()
            object_key = f"evidence/{certificate_id}/evidence.html"
            result = storage.upload_object(object_key, html_data, "text/html")
            storage_keys["html"] = result["key"]
            artifact_hashes["html"] = result["hash"]
            artifact_sizes["html"] = result["size"]

        # Update evidence pack
        from datetime import datetime

        evidence_pack.status = "ready"
        evidence_pack.storage_keys = storage_keys
        evidence_pack.artifact_hashes = artifact_hashes
        evidence_pack.artifact_sizes = artifact_sizes
        evidence_pack.ready_at = datetime.utcnow()
        evidence_pack.generated_at = datetime.utcnow()
        db.commit()

        logger.info(
            f"Evidence pack generated for certificate {certificate_id}",
            extra=log_extra,
        )

    except Exception as e:
        logger.error(
            f"Error generating evidence pack: {e}",
            exc_info=True,
            extra=log_extra,
        )
        if evidence_pack:
            evidence_pack.status = "failed"
            db.commit()
        raise


@celery_app.task(base=DatabaseTask, bind=True, max_retries=3, autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=600, retry_jitter=True)
def deliver_webhook(self, webhook_id: int, event_type: str, payload: dict, correlation_id: Optional[str] = None):
    """Deliver webhook asynchronously with automatic retries."""
    import sys
    sys.path.insert(0, "/app")
    
    from origin_api.models import Webhook, WebhookDelivery
    from origin_api.webhooks.service import WebhookService
    from origin_api.settings import get_settings

    db = self.db
    settings = get_settings()
    delivery = None
    
    # Structured logging with correlation ID
    log_extra = {
        "task": "deliver_webhook",
        "webhook_id": webhook_id,
        "event_type": event_type,
        "correlation_id": correlation_id,
    }

    try:
        webhook = db.query(Webhook).filter(Webhook.id == webhook_id).first()
        if not webhook:
            logger.error(f"Webhook {webhook_id} not found", extra=log_extra)
            return

        # Check if webhook subscribes to this event
        if event_type not in (webhook.events or []):
            logger.info(f"Webhook {webhook_id} does not subscribe to {event_type}", extra=log_extra)
            return

        # Get or create delivery record
        delivery = (
            db.query(WebhookDelivery)
            .filter(
                WebhookDelivery.webhook_id == webhook_id,
                WebhookDelivery.event_type == event_type,
                WebhookDelivery.payload_json == payload,
            )
            .order_by(WebhookDelivery.created_at.desc())
            .first()
        )

        if not delivery:
            delivery = WebhookDelivery(
                webhook_id=webhook.id,
                event_type=event_type,
                payload_json=payload,
                status="pending",
                attempt_number=self.request.retries + 1,
            )
            db.add(delivery)
            db.flush()
        else:
            # Update attempt number
            delivery.attempt_number = self.request.retries + 1
            db.flush()

        # Attempt delivery
        service = WebhookService(db)
        service._attempt_delivery(webhook, delivery, payload)

        # Check if delivery failed and should retry
        if delivery.status == "failed" and delivery.attempt_number < settings.webhook_max_retries:
            # Raise exception to trigger Celery retry
            raise Exception(f"Webhook delivery failed with status {delivery.response_status}")

    except Exception as e:
        logger.error(f"Error delivering webhook {webhook_id}: {e}", exc_info=True, extra=log_extra)
        if delivery:
            delivery.status = "failed"
            delivery.response_body = str(e)[:1000]
            if delivery.attempt_number >= settings.webhook_max_retries:
                logger.error(f"Webhook {webhook_id} delivery failed after max retries, moving to DLQ")
            db.commit()
        # Re-raise to trigger Celery retry if under max retries
        if not delivery or delivery.attempt_number < settings.webhook_max_retries:
            raise

