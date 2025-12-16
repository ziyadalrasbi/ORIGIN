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
def generate_evidence_pack(self, certificate_id: str, formats: list[str]):
    """Generate evidence pack asynchronously."""
    from origin_api.evidence.generator import EvidencePackGenerator
    from origin_api.models import DecisionCertificate, EvidencePack, Upload
    from origin_api.storage.s3 import S3Storage

    db = self.db
    storage = S3Storage()

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

        logger.info(f"Evidence pack generated for certificate {certificate_id}")

    except Exception as e:
        logger.error(f"Error generating evidence pack: {e}", exc_info=True)
        if evidence_pack:
            evidence_pack.status = "failed"
            db.commit()
        raise


@celery_app.task(base=DatabaseTask, bind=True, max_retries=3)
def deliver_webhook(self, webhook_id: int, event_type: str, payload: dict):
    """Deliver webhook asynchronously."""
    from origin_api.models import Webhook, WebhookDelivery
    from origin_api.webhooks.service import WebhookService

    db = self.db

    try:
        webhook = db.query(Webhook).filter(Webhook.id == webhook_id).first()
        if not webhook:
            logger.error(f"Webhook {webhook_id} not found")
            return

        service = WebhookService(db)
        service._attempt_delivery(webhook, None, payload)  # Will create delivery record

    except Exception as e:
        logger.error(f"Error delivering webhook {webhook_id}: {e}", exc_info=True)
        raise

