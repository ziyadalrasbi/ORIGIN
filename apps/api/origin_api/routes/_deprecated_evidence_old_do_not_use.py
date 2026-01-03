"""DEPRECATED: Do not use this module.

This file is kept for reference only. The active evidence pack routes
are in routes/evidence.py.

This module will raise RuntimeError if imported to prevent accidental usage.
"""

raise RuntimeError(
    "This module is deprecated. Use origin_api.routes.evidence instead. "
    "This file is kept for reference only and should not be imported."
)

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from origin_api.db.session import get_db
from origin_api.evidence.generator import EvidencePackGenerator
from origin_api.models import DecisionCertificate, EvidencePack, Upload
from origin_api.models.tenant import Tenant

router = APIRouter(prefix="/v1", tags=["evidence"])
logger = logging.getLogger(__name__)
logger = logging.getLogger(__name__)


class EvidencePackRequest(BaseModel):
    """Evidence pack generation request."""

    certificate_id: str
    format: str = "json"  # json, pdf, html, or comma-separated list
    audience: str = "INTERNAL"  # INTERNAL, DSP, REGULATOR


@router.post("/evidence-packs", status_code=status.HTTP_202_ACCEPTED)
async def request_evidence_pack(
    request_data: EvidencePackRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Request evidence pack generation."""
    tenant: Tenant = request.state.tenant

    # Find certificate
    certificate = (
        db.query(DecisionCertificate)
        .filter(
            DecisionCertificate.tenant_id == tenant.id,
            DecisionCertificate.certificate_id == request_data.certificate_id,
        )
        .first()
    )

    if not certificate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certificate {request_data.certificate_id} not found",
        )

    # Get upload
    upload = db.query(Upload).filter(Upload.id == certificate.upload_id).first()
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found for certificate",
        )

    # Parse formats
    formats = [f.strip() for f in request_data.format.split(",")]

    # Check if evidence pack already exists
    # Explicitly select only columns that exist (avoid canonical_json if migration not applied)
    try:
        # Try to query with explicit column selection to avoid loading missing columns
        from sqlalchemy import select
        stmt = select(
            EvidencePack.id,
            EvidencePack.status,
            EvidencePack.formats,
            EvidencePack.storage_refs,
        ).where(
            EvidencePack.tenant_id == tenant.id,
            EvidencePack.certificate_id == certificate.id,
        )
        result = db.execute(stmt).first()
        if result:
            # Create a simple object with the results
            class SimpleEvidencePack:
                def __init__(self, id, status, formats, storage_refs):
                    self.id = id
                    self.status = status
                    self.formats = formats
                    self.storage_refs = storage_refs
                    self.evidence_hash = None
                    self.evidence_version = None
            evidence_pack = SimpleEvidencePack(result.id, result.status, result.formats, result.storage_refs)
        else:
            evidence_pack = None
    except Exception:
        # If query fails, just continue without evidence_pack
        db.rollback()
        evidence_pack = None

    if evidence_pack and hasattr(evidence_pack, 'status') and evidence_pack.status == "ready":
        # Check if formats and storage_refs are actually populated
        # If not, we need to regenerate (they might be None from a previous failed generation)
        has_formats = evidence_pack.formats is not None and len(evidence_pack.formats) > 0
        has_storage_refs = evidence_pack.storage_refs is not None and len(evidence_pack.storage_refs) > 0
        
        if has_formats and has_storage_refs:
            # Return existing - everything is good
            evidence_hash = getattr(evidence_pack, 'evidence_hash', None)
            evidence_version = getattr(evidence_pack, 'evidence_version', None) or "origin-evidence-v2"
            
            # Build download URLs
            download_urls = {}
            if evidence_pack.storage_refs:
                for fmt in (evidence_pack.formats or []):
                    download_urls[fmt] = f"/v1/evidence-packs/{request_data.certificate_id}/download/{fmt}"
            
            return {
                "status": "ready",
                "certificate_id": request_data.certificate_id,
                "version": evidence_version,
                "evidence_hash": evidence_hash,
                "formats": evidence_pack.formats,
                "available_formats": evidence_pack.formats,
                "storage_refs": evidence_pack.storage_refs,
                "download_urls": download_urls,
            }
        else:
            # Evidence pack exists but formats/storage_refs are missing - regenerate
            logger.info(f"Evidence pack exists but formats/storage_refs are missing. Regenerating...")
            # Continue to async generation below

    # Create or update evidence pack record with status="pending"
    # Always use raw SQL INSERT to avoid SQLAlchemy trying to insert columns that don't exist
    if not evidence_pack:
        # Check if migration has been applied (for later use)
        has_canonical_fields = False
        try:
            result = db.execute(
                text("SELECT column_name FROM information_schema.columns "
                     "WHERE table_name = 'evidence_packs' AND column_name = 'canonical_json'")
            ).first()
            has_canonical_fields = result is not None
        except Exception:
            pass
        
        # Always use raw INSERT to avoid SQLAlchemy model column issues
        import json
        formats_json = json.dumps(formats) if formats else None
        
        # Build INSERT statement based on which columns exist
        if has_canonical_fields:
            # Migration applied - include all columns
            result = db.execute(
                text("INSERT INTO evidence_packs (tenant_id, certificate_id, status, formats, created_at) "
                     "VALUES (:tenant_id, :certificate_id, :status, CAST(:formats AS jsonb), NOW()) "
                     "RETURNING id"),
                {
                    "tenant_id": tenant.id,
                    "certificate_id": certificate.id,
                    "status": "pending",
                    "formats": formats_json,
                }
            )
        else:
            # Migration not applied - only insert existing columns
            result = db.execute(
                text("INSERT INTO evidence_packs (tenant_id, certificate_id, status, formats, created_at) "
                     "VALUES (:tenant_id, :certificate_id, :status, CAST(:formats AS jsonb), NOW()) "
                     "RETURNING id"),
                {
                    "tenant_id": tenant.id,
                    "certificate_id": certificate.id,
                    "status": "pending",
                    "formats": formats_json,
                }
            )
        inserted_id = result.scalar()
        db.commit()
        
        # Create a minimal object for the evidence pack
        class MinimalEvidencePack:
            def __init__(self, id, tenant_id, certificate_id, status, formats):
                self.id = id
                self.tenant_id = tenant_id
                self.certificate_id = certificate_id
                self.status = status
                self.formats = formats
                self.storage_refs = None
                self.ready_at = None
        evidence_pack = MinimalEvidencePack(inserted_id, tenant.id, certificate.id, "pending", formats)
        
        # Store formats in the database for later retrieval
        try:
            formats_json = json.dumps(formats) if formats else None
            db.execute(
                text("UPDATE evidence_packs SET formats = CAST(:formats AS jsonb) WHERE id = :id"),
                {"formats": formats_json, "id": inserted_id}
            )
            db.commit()
        except Exception:
            db.rollback()

    # Enqueue async Celery task for evidence pack generation (C)
    try:
        # Use Celery's task signature without importing the task directly
        # This works across containers via Redis broker
        from celery import Celery
        from celery.result import AsyncResult
        
        # Create a minimal Celery app to send tasks (doesn't need worker code)
        from origin_api.settings import get_settings
        settings = get_settings()
        celery_app = Celery("origin_api")
        celery_app.conf.broker_url = settings.redis_url
        celery_app.conf.result_backend = settings.redis_url
        
        # Check if task is already running (idempotency - C2)
        # Use task_id based on certificate_id to prevent duplicates
        task_id = f"evidence_pack_{certificate.id}_{tenant.id}"
        
        # Check if task is already pending/running
        existing_task = AsyncResult(task_id, app=celery_app)
        task_state = existing_task.state
        logger.info(f"Checking existing task {task_id}: state={task_state}")
        
        # Only skip if task is actually running (STARTED) or retrying
        # If PENDING for too long, it might be stuck - allow re-enqueue
        if task_state == "STARTED" or task_state == "RETRY":
            logger.info(f"Evidence pack generation task already in progress: {task_id} (state={task_state})")
            # Return pending status
            return {
                "status": "pending",
                "certificate_id": request_data.certificate_id,
                "formats": formats,
                "poll_url": f"/v1/evidence-packs/{request_data.certificate_id}",
            }
        elif task_state == "PENDING":
            # PENDING means task is in queue but not started yet
            # Check if it's been pending too long (stuck in queue)
            try:
                # If task has no result yet and is just PENDING, it might be stuck
                # Allow re-enqueue to unstick it
                logger.info(f"Task {task_id} is PENDING - will enqueue new task (may replace stuck one)")
            except Exception:
                pass
        elif task_state == "SUCCESS":
            # Task completed - check if DB was updated
            logger.info(f"Task {task_id} already completed - checking DB status")
        elif task_state == "FAILURE":
            # Task failed - allow re-enqueue
            logger.warning(f"Previous task {task_id} failed - allowing re-enqueue")
        
        # Enqueue new task using task signature
        audience = request_data.audience or "INTERNAL"
        task_signature = celery_app.signature(
            "origin_worker.tasks.generate_evidence_pack",
            args=[certificate.certificate_id, tenant.id, formats, audience],
            task_id=task_id,
        )
        task = task_signature.apply_async()
        logger.info(f"Enqueued evidence pack generation task: {task.id} for certificate {certificate.certificate_id}")
        
    except ImportError:
        # Fallback to synchronous generation if Celery is not available
        logger.warning("Celery not available, falling back to synchronous generation")
        from origin_api.evidence.generator import EvidencePackGenerator
        
        generator = EvidencePackGenerator(db)
        artifacts = {}
        audience = request_data.audience or "INTERNAL"
        
        if "json" in formats:
            artifacts["json"] = generator.generate_json(certificate, upload, audience=audience)
        if "pdf" in formats:
            artifacts["pdf"] = generator.generate_pdf(certificate, upload)
        if "html" in formats:
            artifacts["html"] = generator.generate_html(certificate, upload)
        
        storage_refs = generator.save_artifacts(certificate.certificate_id, formats, artifacts, audience=audience)
        
        # Update evidence pack
        import json
        formats_json = json.dumps(formats) if formats else None
        storage_refs_json = json.dumps(storage_refs) if storage_refs else None
        
        try:
            db.execute(
                text("UPDATE evidence_packs SET status = 'ready', formats = CAST(:formats AS jsonb), storage_refs = CAST(:storage_refs AS jsonb), ready_at = NOW() "
                     "WHERE tenant_id = :tenant_id AND certificate_id = :certificate_id"),
                {
                    "formats": formats_json,
                    "storage_refs": storage_refs_json,
                    "tenant_id": tenant.id,
                    "certificate_id": certificate.id,
                }
            )
            db.commit()
        except Exception:
            db.rollback()
        
        # Build download URLs
        download_urls = {}
        if storage_refs:
            for fmt in formats:
                download_urls[fmt] = f"/v1/evidence-packs/{request_data.certificate_id}/download/{fmt}"
        
        return {
            "status": "ready",
            "certificate_id": request_data.certificate_id,
            "version": "origin-evidence-v2",
            "evidence_hash": None,
            "formats": formats,
            "available_formats": formats,
            "storage_refs": storage_refs,
            "download_urls": download_urls,
        }
    except Exception as e:
        logger.error(f"Failed to enqueue evidence pack generation task: {e}")
        # Fallback to synchronous generation
        from origin_api.evidence.generator import EvidencePackGenerator
        
        generator = EvidencePackGenerator(db)
        artifacts = {}
        audience = request_data.audience or "INTERNAL"
        
        if "json" in formats:
            artifacts["json"] = generator.generate_json(certificate, upload, audience=audience)
        if "pdf" in formats:
            artifacts["pdf"] = generator.generate_pdf(certificate, upload)
        if "html" in formats:
            artifacts["html"] = generator.generate_html(certificate, upload)
        
        storage_refs = generator.save_artifacts(certificate.certificate_id, formats, artifacts, audience=audience)
        
        # Update evidence pack
        import json
        formats_json = json.dumps(formats) if formats else None
        storage_refs_json = json.dumps(storage_refs) if storage_refs else None
        
        try:
            db.execute(
                text("UPDATE evidence_packs SET status = 'ready', formats = CAST(:formats AS jsonb), storage_refs = CAST(:storage_refs AS jsonb), ready_at = NOW() "
                     "WHERE tenant_id = :tenant_id AND certificate_id = :certificate_id"),
                {
                    "formats": formats_json,
                    "storage_refs": storage_refs_json,
                    "tenant_id": tenant.id,
                    "certificate_id": certificate.id,
                }
            )
            db.commit()
        except Exception:
            db.rollback()
        
        # Build download URLs
        download_urls = {}
        if storage_refs:
            for fmt in formats:
                download_urls[fmt] = f"/v1/evidence-packs/{request_data.certificate_id}/download/{fmt}"
        
        return {
            "status": "ready",
            "certificate_id": request_data.certificate_id,
            "version": "origin-evidence-v2",
            "evidence_hash": None,
            "formats": formats,
            "available_formats": formats,
            "storage_refs": storage_refs,
            "download_urls": download_urls,
        }
    
    # Return pending status with poll URL
    return {
        "status": "pending",
        "certificate_id": request_data.certificate_id,
        "formats": formats,
        "poll_url": f"/v1/evidence-packs/{request_data.certificate_id}",
    }


@router.get("/evidence-packs/{certificate_id}")
async def get_evidence_pack(
    certificate_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get evidence pack status and download URLs."""
    tenant: Tenant = request.state.tenant

    # Find certificate
    certificate = (
        db.query(DecisionCertificate)
        .filter(
            DecisionCertificate.tenant_id == tenant.id,
            DecisionCertificate.certificate_id == certificate_id,
        )
        .first()
    )

    if not certificate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certificate {certificate_id} not found",
        )
    
    # Get upload (needed for fallback synchronous generation)
    upload = db.query(Upload).filter(Upload.id == certificate.upload_id).first()
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found for certificate",
        )

    # Get evidence pack (explicitly select only existing columns)
    evidence_pack = None
    try:
        stmt = select(
            EvidencePack.id,
            EvidencePack.status,
            EvidencePack.formats,
            EvidencePack.storage_refs,
        ).where(
            EvidencePack.tenant_id == tenant.id,
            EvidencePack.certificate_id == certificate.id,
        )
        result = db.execute(stmt).first()
        if result:
            class SimpleEvidencePack:
                def __init__(self, id, status, formats, storage_refs):
                    self.id = id
                    self.status = status
                    self.formats = formats
                    self.storage_refs = storage_refs
                    self.evidence_hash = None
                    self.evidence_version = None
            evidence_pack = SimpleEvidencePack(result.id, result.status, result.formats, result.storage_refs)
    except Exception:
        db.rollback()
        evidence_pack = None

    if not evidence_pack:
        return {
            "status": "not_found",
            "certificate_id": certificate_id,
        }

    # Check Celery task status if pending (fix stuck pending status)
    if evidence_pack.status == "pending":
        try:
            from celery import Celery
            from celery.result import AsyncResult
            from origin_api.settings import get_settings
            from datetime import datetime, timedelta
            
            # Create a minimal Celery app to check task status (same as POST endpoint)
            settings = get_settings()
            celery_app = Celery("origin_api")
            celery_app.conf.broker_url = settings.redis_url
            celery_app.conf.result_backend = settings.redis_url
            
            task_id = f"evidence_pack_{certificate.id}_{tenant.id}"
            task_result = AsyncResult(task_id, app=celery_app)
            
            # Check if task has been pending for too long (5 minutes) - fallback to sync
            # Get created_at from evidence_pack if available
            try:
                created_at_result = db.execute(
                    text("SELECT created_at FROM evidence_packs WHERE tenant_id = :tenant_id AND certificate_id = :certificate_id"),
                    {"tenant_id": tenant.id, "certificate_id": certificate.id}
                ).first()
                if created_at_result:
                    created_at = created_at_result[0]
                    if isinstance(created_at, datetime):
                        time_elapsed = datetime.utcnow() - created_at.replace(tzinfo=None) if created_at.tzinfo else datetime.utcnow() - created_at
                        if time_elapsed > timedelta(minutes=5):
                            logger.warning(f"Evidence pack generation stuck for {time_elapsed}, falling back to synchronous generation for {certificate_id}")
                            # Fallback to synchronous generation
                            from origin_api.evidence.generator import EvidencePackGenerator
                            
                            generator = EvidencePackGenerator(db)
                            artifacts = {}
                            audience = "INTERNAL"  # Default to INTERNAL
                            
                            if "json" in (evidence_pack.formats or []):
                                artifacts["json"] = generator.generate_json(certificate, upload, audience=audience)
                            if "pdf" in (evidence_pack.formats or []):
                                artifacts["pdf"] = generator.generate_pdf(certificate, upload)
                            if "html" in (evidence_pack.formats or []):
                                artifacts["html"] = generator.generate_html(certificate, upload)
                            
                            storage_refs = generator.save_artifacts(
                                certificate.certificate_id, evidence_pack.formats or [], artifacts, audience=audience
                            )
                            
                            import json
                            storage_refs_json = json.dumps(storage_refs) if storage_refs else None
                            formats_json = json.dumps(evidence_pack.formats) if evidence_pack.formats else None
                            
                            db.execute(
                                text("UPDATE evidence_packs SET status = 'ready', storage_refs = CAST(:storage_refs AS jsonb), "
                                     "formats = CAST(:formats AS jsonb), ready_at = NOW() "
                                     "WHERE tenant_id = :tenant_id AND certificate_id = :certificate_id"),
                                {
                                    "storage_refs": storage_refs_json,
                                    "formats": formats_json,
                                    "tenant_id": tenant.id,
                                    "certificate_id": certificate.id,
                                }
                            )
                            db.commit()
                            
                            # Refresh evidence_pack from DB
                            result = db.execute(stmt).first()
                            if result:
                                evidence_pack = SimpleEvidencePack(result.id, "ready", result.formats, result.storage_refs)
                            logger.info(f"Completed evidence pack generation synchronously (fallback) for {certificate_id}")
            except Exception as fallback_error:
                logger.error(f"Error in fallback synchronous generation: {fallback_error}")
            
            if evidence_pack.status == "pending":  # Only check Celery if still pending after fallback check
                if task_result.state == "SUCCESS":
                    # Task completed successfully - update DB from task result
                    task_data = task_result.result
                    if isinstance(task_data, dict):
                        storage_refs = task_data.get("storage_refs", {})
                        formats = task_data.get("formats", [])
                        
                        import json
                        storage_refs_json = json.dumps(storage_refs) if storage_refs else None
                        formats_json = json.dumps(formats) if formats else None
                        
                        db.execute(
                            text("UPDATE evidence_packs SET status = 'ready', storage_refs = CAST(:storage_refs AS jsonb), "
                                 "formats = CAST(:formats AS jsonb), ready_at = NOW() "
                                 "WHERE tenant_id = :tenant_id AND certificate_id = :certificate_id"),
                            {
                                "storage_refs": storage_refs_json,
                                "formats": formats_json,
                                "tenant_id": tenant.id,
                                "certificate_id": certificate.id,
                            }
                        )
                        db.commit()
                        
                        # Refresh evidence_pack from DB
                        result = db.execute(stmt).first()
                        if result:
                            evidence_pack = SimpleEvidencePack(result.id, "ready", result.formats, result.storage_refs)
                        logger.info(f"Updated evidence pack status to ready from Celery task result for {certificate_id}")
                    else:
                        logger.warning(f"Unexpected task result format for {certificate_id}: {type(task_data)}")
                        
                elif task_result.state == "FAILURE":
                    # Task failed - update status to failed
                    db.execute(
                        text("UPDATE evidence_packs SET status = 'failed' WHERE tenant_id = :tenant_id AND certificate_id = :certificate_id"),
                        {"tenant_id": tenant.id, "certificate_id": certificate.id}
                    )
                    db.commit()
                    evidence_pack.status = "failed"
                    logger.warning(f"Evidence pack generation failed for {certificate_id}: {task_result.info}")
                    
                elif task_result.state in ("PENDING", "STARTED", "RETRY"):
                    # Task still running - return pending status
                    logger.debug(f"Evidence pack generation still in progress for {certificate_id}: {task_result.state}")
                else:
                    logger.warning(f"Unknown Celery task state for {certificate_id}: {task_result.state}")
                
        except ImportError:
            logger.warning("Celery not available, cannot check async task status.")
        except Exception as e:
            logger.error(f"Error checking Celery task status for {certificate_id}: {e}")
            # Continue with DB status

    # Generate signed URLs (for now, return paths - in production, use S3 signed URLs)
    signed_urls = {}
    if evidence_pack.storage_refs:
        for fmt, path in evidence_pack.storage_refs.items():
            # In production, generate S3 signed URL
            signed_urls[fmt] = f"/v1/evidence-packs/{certificate_id}/download/{fmt}"

    return {
        "status": evidence_pack.status,
        "certificate_id": certificate_id,
        "version": evidence_pack.evidence_version or "origin-evidence-v2",
        "evidence_hash": evidence_pack.evidence_hash,
        "formats": evidence_pack.formats or [],
        "available_formats": evidence_pack.formats or [],
        "signed_urls": signed_urls,
        "poll_url": f"/v1/evidence-packs/{certificate_id}" if evidence_pack.status == "pending" else None,
    }


@router.get("/evidence-packs/{certificate_id}/download/{format}")
async def download_evidence_pack(
    certificate_id: str,
    format: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Download evidence pack artifact."""
    tenant: Tenant = request.state.tenant

    # Find certificate and evidence pack
    certificate = (
        db.query(DecisionCertificate)
        .filter(
            DecisionCertificate.tenant_id == tenant.id,
            DecisionCertificate.certificate_id == certificate_id,
        )
        .first()
    )

    if not certificate:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Query evidence pack (explicitly select only existing columns)
    evidence_pack = None
    try:
        stmt = select(
            EvidencePack.id,
            EvidencePack.status,
            EvidencePack.storage_refs,
        ).where(
            EvidencePack.tenant_id == tenant.id,
            EvidencePack.certificate_id == certificate.id,
        )
        result = db.execute(stmt).first()
        if result:
            class SimpleEvidencePack:
                def __init__(self, id, status, storage_refs):
                    self.id = id
                    self.status = status
                    self.storage_refs = storage_refs
            evidence_pack = SimpleEvidencePack(result.id, result.status, result.storage_refs)
    except Exception:
        db.rollback()
        evidence_pack = None

    if not evidence_pack or evidence_pack.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence pack not ready",
        )

    # Validate format (D2 - prevent arbitrary format requests)
    allowed_formats = {"json", "pdf", "html"}
    if format not in allowed_formats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid format: {format}. Allowed: {allowed_formats}",
        )
    
    # Get storage reference (object key or filesystem path)
    storage_ref = evidence_pack.storage_refs.get(format) if evidence_pack.storage_refs else None
    if not storage_ref:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Format {format} not available",
        )
    
    # Determine audience from request (default to INTERNAL, but check if DSP requested)
    # For now, we'll use the audience from the storage_ref path if it's an object key
    # In production, this should come from request headers or tenant context
    requested_audience = "INTERNAL"  # TODO: Extract from request context/headers
    
    # Enforce audience access control (D2)
    # DSP cannot download INTERNAL artifacts
    if requested_audience == "DSP":
        # Check if storage_ref is for INTERNAL audience
        if isinstance(storage_ref, str) and storage_ref.startswith("evidence/") and "/INTERNAL/" in storage_ref:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="DSP audience cannot access INTERNAL evidence packs",
            )
    
    # Retrieve artifact from storage (D2 - path traversal prevention)
    content = None
    try:
        from origin_api.storage.service import get_storage_service
        
        storage_service = get_storage_service()
        
        # Check if it's an object key (starts with "evidence/") or filesystem path
        if isinstance(storage_ref, str) and storage_ref.startswith("evidence/"):
            # Object storage key - retrieve from MinIO/S3
            if storage_service.client:
                content = storage_service.get_object(storage_ref)
            else:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Object storage not available",
                )
        elif isinstance(storage_ref, str) and storage_ref.startswith("file://"):
            # Filesystem fallback - validate path to prevent traversal
            from pathlib import Path
            
            file_path = Path(storage_ref.replace("file://", ""))
            # Ensure path is within storage_base (prevent path traversal)
            storage_base = Path("/app/evidence_packs")
            try:
                file_path.resolve().relative_to(storage_base.resolve())
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid file path",
                )
            
            if not file_path.exists():
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            
            with open(file_path, "rb") as f:
                content = f.read()
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid storage reference format",
            )
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Failed to retrieve artifact: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve artifact",
        )
    
    # Determine content type
    content_types = {
        "json": "application/json",
        "pdf": "application/pdf",
        "html": "text/html",
    }
    
    # Log download for audit (D2)
    logger.info(
        f"Evidence pack download: certificate_id={certificate_id}, format={format}, "
        f"audience={requested_audience}, tenant_id={tenant.id}"
    )
    
    return Response(
        content=content,
        media_type=content_types.get(format, "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="evidence.{format}"',
        },
    )

