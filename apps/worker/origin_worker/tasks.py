"""Celery tasks for async evidence pack generation."""

import logging
from typing import Optional

from celery import Task
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from origin_worker.celery_app import celery_app
from origin_worker.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Create database session factory for worker
engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine)


class DatabaseTask(Task):
    """Celery task with database session management."""

    _db = None

    @property
    def db(self):
        """Get or create database session."""
        if self._db is None:
            self._db = SessionLocal()
        return self._db

    def after_return(self, *args, **kwargs):
        """Close database session after task completion."""
        if self._db is not None:
            self._db.close()
            self._db = None


@celery_app.task(
    base=DatabaseTask,
    bind=True,
    name="origin_worker.tasks.generate_evidence_pack",
    max_retries=3,
    default_retry_delay=60,
)
def generate_evidence_pack(
    self,
    certificate_id: str,
    tenant_id: int,
    formats: list[str],
    audience: str = "INTERNAL",
) -> dict:
    """
    Generate evidence pack artifacts asynchronously.
    
    This task:
    1. Loads certificate and upload
    2. Generates canonical INTERNAL JSON snapshot once
    3. Generates requested formats (JSON/PDF/HTML) derived from canonical snapshot + redactions
    4. Stores artifacts to object storage
    5. Updates EvidencePack(status="ready", storage_refs, ready_at)
    
    Args:
        certificate_id: UUID of the decision certificate
        tenant_id: Tenant ID
        formats: List of formats to generate ["json", "pdf", "html"]
        audience: Audience for redactions ("INTERNAL", "DSP", "REGULATOR")
    
    Returns:
        dict with status and storage_refs
    """
    try:
        # Import origin_api modules (available via PYTHONPATH or volume mount)
        # No sys.path manipulation needed - PYTHONPATH is set in Dockerfile/docker-compose
        from origin_api.models import DecisionCertificate, EvidencePack, Upload
        from origin_api.evidence.generator import EvidencePackGenerator
        logger.debug("Successfully imported origin_api modules")
        
        db = self.db
        
        # Load certificate
        certificate = (
            db.query(DecisionCertificate)
            .filter(
                DecisionCertificate.tenant_id == tenant_id,
                DecisionCertificate.certificate_id == certificate_id,
            )
            .first()
        )
        
        if not certificate:
            logger.error(f"Certificate {certificate_id} not found for tenant {tenant_id}")
            raise ValueError(f"Certificate {certificate_id} not found")
        
        # Load upload
        upload = db.query(Upload).filter(Upload.id == certificate.upload_id).first()
        if not upload:
            logger.error(f"Upload not found for certificate {certificate_id}")
            raise ValueError(f"Upload not found for certificate {certificate_id}")
        
        # Check if evidence pack already exists and is ready with same formats and audience
        evidence_pack = (
            db.query(EvidencePack)
            .filter(
                EvidencePack.tenant_id == tenant_id,
                EvidencePack.certificate_id == certificate.id,
                EvidencePack.audience == audience,
            )
            .first()
        )
        
        if evidence_pack and evidence_pack.status == "ready":
            # Check if formats match
            existing_formats = evidence_pack.formats or []
            if set(formats) <= set(existing_formats):
                logger.info(f"Evidence pack already ready with requested formats: {formats} for audience: {audience}")
                return {
                    "status": "ready",
                    "certificate_id": certificate_id,
                    "formats": existing_formats,
                    "storage_refs": evidence_pack.storage_refs or {},
                }
        
        # Update status to processing
        evidence_pack_id = None
        if evidence_pack:
            evidence_pack_id = evidence_pack.id
            # Use raw SQL to update status
            db.execute(
                text("UPDATE evidence_packs SET status = 'processing' WHERE id = :id"),
                {"id": evidence_pack_id}
            )
        else:
            # Create evidence pack record using raw SQL (with audience)
            import json
            formats_json = json.dumps(formats) if formats else None
            # Check if audience column exists
            try:
                result = db.execute(
                    text("INSERT INTO evidence_packs (tenant_id, certificate_id, audience, status, formats, created_at) "
                         "VALUES (:tenant_id, :certificate_id, :audience, 'processing', CAST(:formats AS jsonb), NOW()) "
                         "RETURNING id"),
                    {
                        "tenant_id": tenant_id,
                        "certificate_id": certificate.id,
                        "audience": audience,
                        "formats": formats_json,
                    }
                )
            except Exception:
                # Fallback if audience column doesn't exist yet
                result = db.execute(
                    text("INSERT INTO evidence_packs (tenant_id, certificate_id, status, formats, created_at) "
                         "VALUES (:tenant_id, :certificate_id, 'processing', CAST(:formats AS jsonb), NOW()) "
                         "RETURNING id"),
                    {
                        "tenant_id": tenant_id,
                        "certificate_id": certificate.id,
                        "formats": formats_json,
                    }
                )
            evidence_pack_id = result.scalar()
        db.commit()
        
        # Generate artifacts
        generator = EvidencePackGenerator(db)
        artifacts = {}
        
        # Generate canonical JSON snapshot (INTERNAL audience)
        canonical_json = generator.generate_json(certificate, upload, audience="INTERNAL")
        artifacts["json"] = canonical_json
        
        # Generate other formats if requested
        if "pdf" in formats:
            artifacts["pdf"] = generator.generate_pdf(certificate, upload)
        
        if "html" in formats:
            artifacts["html"] = generator.generate_html(certificate, upload)
        
        # Apply audience redactions to JSON if not INTERNAL
        if audience != "INTERNAL":
            # Re-generate JSON with audience redactions
            artifacts["json"] = generator.generate_json(certificate, upload, audience=audience)
        
        # Save artifacts to storage (with audience for object key path)
        storage_refs = generator.save_artifacts(
            certificate.certificate_id, formats, artifacts, audience=audience
        )
        
        # Update evidence pack using raw SQL
        import json
        from datetime import datetime
        storage_refs_json = json.dumps(storage_refs) if storage_refs else None
        formats_json = json.dumps(formats) if formats else None
        
        # Update evidence pack (include audience in WHERE clause if column exists)
        try:
            db.execute(
                text("UPDATE evidence_packs SET status = 'ready', storage_refs = CAST(:storage_refs AS jsonb), "
                     "formats = CAST(:formats AS jsonb), ready_at = NOW() "
                     "WHERE tenant_id = :tenant_id AND certificate_id = :certificate_id AND audience = :audience"),
                {
                    "storage_refs": storage_refs_json,
                    "formats": formats_json,
                    "tenant_id": tenant_id,
                    "certificate_id": certificate.id,
                    "audience": audience,
                }
            )
        except Exception:
            # Fallback if audience column doesn't exist yet
            db.execute(
                text("UPDATE evidence_packs SET status = 'ready', storage_refs = CAST(:storage_refs AS jsonb), "
                     "formats = CAST(:formats AS jsonb), ready_at = NOW() "
                     "WHERE tenant_id = :tenant_id AND certificate_id = :certificate_id"),
                {
                    "storage_refs": storage_refs_json,
                    "formats": formats_json,
                    "tenant_id": tenant_id,
                    "certificate_id": certificate.id,
                }
            )
        db.commit()
        
        logger.info(f"Successfully generated evidence pack for certificate {certificate_id}")
        
        return {
            "status": "ready",
            "certificate_id": certificate_id,
            "formats": formats,
            "storage_refs": storage_refs,
        }
        
    except Exception as exc:
        logger.exception(f"Failed to generate evidence pack for certificate {certificate_id}: {exc}")
        
        # Update status to failed
        try:
            if evidence_pack_id:
                db.execute(
                    text("UPDATE evidence_packs SET status = 'failed' WHERE id = :id"),
                    {"id": evidence_pack_id}
                )
                db.commit()
        except Exception:
            pass
        
        # Retry if not max retries
        raise self.retry(exc=exc)

