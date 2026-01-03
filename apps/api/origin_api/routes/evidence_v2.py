"""Production-grade evidence pack routes.

This module implements enterprise-grade evidence pack generation and retrieval
with proper idempotency, audience enforcement, and observability.

Key features:
- Pure async generation (no synchronous fallbacks)
- Deterministic idempotency via DB constraints
- Audience + scope enforcement
- Presigned URLs for secure access
- Structured logging with correlation IDs
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from origin_api.celery_client import get_celery_app
from origin_api.db.session import get_db
from origin_api.evidence.generator import EvidencePackGenerator
from origin_api.evidence.scopes import (
    determine_audience_from_scopes,
    enforce_audience_access,
    get_api_key_scopes,
)
from origin_api.models import DecisionCertificate, EvidencePack, Upload
from origin_api.models.tenant import Tenant
from origin_api.settings import get_settings
from origin_api.storage.service import get_storage_service

router = APIRouter(prefix="/v1", tags=["evidence"])
logger = logging.getLogger(__name__)
settings = get_settings()

# Evidence pack timeout (minutes)
EVIDENCE_PACK_TIMEOUT_MINUTES = settings.evidence_pack_timeout_minutes


class EvidencePackRequest(BaseModel):
    """Evidence pack generation request."""

    certificate_id: str
    format: str = Field(default="json", description="json, pdf, html, or comma-separated list")
    audience: Optional[str] = Field(
        default=None, description="INTERNAL, DSP, REGULATOR (determined from scopes if not provided)"
    )


class EvidencePackResponse(BaseModel):
    """Evidence pack status response."""

    status: str  # not_found, pending, ready, failed
    certificate_id: str
    audience: Optional[str] = None
    version: Optional[str] = None
    evidence_hash: Optional[str] = None
    formats: Optional[list[str]] = None
    available_formats: Optional[list[str]] = None
    signed_urls: Optional[dict[str, str]] = None
    download_urls: Optional[dict[str, str]] = None
    generated_at: Optional[str] = None  # ISO8601 timestamp
    ready_at: Optional[str] = None  # ISO8601 timestamp
    poll_url: Optional[str] = None
    retry_after_seconds: Optional[int] = None
    task_state: Optional[str] = None  # PENDING, STARTED, SUCCESS, FAILURE
    error_code: Optional[str] = None
    error_message: Optional[str] = None


def _get_deterministic_task_id(certificate_id: int, tenant_id: int) -> str:
    """Generate deterministic task ID for idempotency."""
    return f"evidence_pack_{certificate_id}_{tenant_id}"


def _upsert_evidence_pack(
    db: Session,
    tenant_id: int,
    certificate_id: int,
    audience: str,
    status: str = "pending",
    formats: Optional[list[str]] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> EvidencePack:
    """
    Upsert evidence pack record with proper idempotency.
    
    Uses PostgreSQL INSERT ... ON CONFLICT to ensure atomicity.
    """
    formats_json = json.dumps(formats) if formats else None
    
    # Use INSERT ... ON CONFLICT for atomic upsert
    stmt = (
        insert(EvidencePack.__table__)
        .values(
            tenant_id=tenant_id,
            certificate_id=certificate_id,
            audience=audience,
            status=status,
            formats=formats_json,
            created_at=datetime.now(timezone.utc),
            error_code=error_code,
            error_message=error_message,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "certificate_id", "audience"],
            set_={
                "status": status,
                "formats": formats_json,
                "error_code": error_code,
                "error_message": error_message,
            },
        )
        .returning(EvidencePack.__table__)
    )
    
    result = db.execute(stmt)
    db.commit()
    
    row = result.first()
    if not row:
        raise ValueError("Failed to upsert evidence pack")
    
    # Create EvidencePack instance from row
    evidence_pack = EvidencePack(
        id=row.id,
        tenant_id=row.tenant_id,
        certificate_id=row.certificate_id,
        audience=row.audience,
        status=row.status,
        formats=row.formats,
        storage_refs=row.storage_refs,
        created_at=row.created_at,
        ready_at=row.ready_at,
        canonical_json=row.canonical_json,
        evidence_hash=row.evidence_hash,
        evidence_version=row.evidence_version,
        canonical_created_at=row.canonical_created_at,
        error_code=row.error_code,
        error_message=row.error_message,
    )
    
    return evidence_pack


@router.post("/evidence-packs", response_model=EvidencePackResponse, status_code=status.HTTP_202_ACCEPTED)
async def request_evidence_pack(
    request_data: EvidencePackRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Request evidence pack generation.
    
    This endpoint is idempotent: multiple requests for the same
    (tenant_id, certificate_id, audience, formats) will not create duplicates.
    
    Returns 202 Accepted with pending status and poll_url.
    """
    tenant: Tenant = request.state.tenant
    correlation_id = getattr(request.state, "correlation_id", None)
    
    # Extract API key scopes and determine audience
    scopes = get_api_key_scopes(request, db)
    determined_audience = determine_audience_from_scopes(scopes, request_data.audience)
    
    # Enforce audience access for request
    enforce_audience_access("request", scopes, determined_audience)
    
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
    
    # Parse formats
    formats = [f.strip() for f in request_data.format.split(",")]
    allowed_formats = {"json", "pdf", "html"}
    if not all(f in allowed_formats for f in formats):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid format(s). Allowed: {allowed_formats}",
        )
    
    # Check if evidence pack already exists and is ready
    existing = (
        db.query(EvidencePack)
        .filter(
            EvidencePack.tenant_id == tenant.id,
            EvidencePack.certificate_id == certificate.id,
            EvidencePack.audience == determined_audience,
        )
        .first()
    )
    
    if existing and existing.status == "ready":
        # Check if all requested formats are available
        existing_formats = existing.formats or []
        if set(formats) <= set(existing_formats):
            # All formats available, return ready status
            return _build_response(existing, certificate.certificate_id, db)
    
    # Upsert evidence pack record (idempotent)
    evidence_pack = _upsert_evidence_pack(
        db=db,
        tenant_id=tenant.id,
        certificate_id=certificate.id,
        audience=determined_audience,
        status="pending",
        formats=formats,
    )
    
    # Enqueue Celery task
    celery_app = get_celery_app()
    task_id = _get_deterministic_task_id(certificate.id, tenant.id)
    
    # Check if task is already running
    from celery.result import AsyncResult
    
    existing_task = AsyncResult(task_id, app=celery_app)
    task_state = existing_task.state
    
    if task_state in ("STARTED", "RETRY"):
        # Task already running, return pending
        logger.info(
            f"Evidence pack task already running: {task_id} (state={task_state})",
            extra={
                "correlation_id": correlation_id,
                "certificate_id": certificate.certificate_id,
                "tenant_id": tenant.id,
            },
        )
        return EvidencePackResponse(
            status="pending",
            certificate_id=request_data.certificate_id,
            audience=determined_audience,
            formats=formats,
            poll_url=f"/v1/evidence-packs/{request_data.certificate_id}",
            retry_after_seconds=30,
            task_state=task_state,
        )
    
    # Enqueue new task
    try:
        task_signature = celery_app.signature(
            "origin_worker.tasks.generate_evidence_pack",
            args=[certificate.certificate_id, tenant.id, formats, determined_audience],
            task_id=task_id,
        )
        task = task_signature.apply_async()
        
        logger.info(
            f"Enqueued evidence pack generation task: {task.id}",
            extra={
                "correlation_id": correlation_id,
                "certificate_id": certificate.certificate_id,
                "tenant_id": tenant.id,
                "audience": determined_audience,
                "formats": formats,
            },
        )
    except Exception as e:
        logger.error(
            f"Failed to enqueue evidence pack task: {e}",
            extra={
                "correlation_id": correlation_id,
                "certificate_id": certificate.certificate_id,
                "tenant_id": tenant.id,
            },
            exc_info=True,
        )
        # Update status to failed
        evidence_pack.status = "failed"
        evidence_pack.error_code = "TASK_ENQUEUE_FAILED"
        evidence_pack.error_message = "Failed to enqueue generation task"
        db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue evidence pack generation",
        )
    
    return EvidencePackResponse(
        status="pending",
        certificate_id=request_data.certificate_id,
        audience=determined_audience,
        formats=formats,
        poll_url=f"/v1/evidence-packs/{request_data.certificate_id}",
        retry_after_seconds=30,
        task_state="PENDING",
    )


@router.get("/evidence-packs/{certificate_id}", response_model=EvidencePackResponse)
async def get_evidence_pack(
    certificate_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Get evidence pack status (read-only, no DB writes except benign telemetry).
    
    This endpoint:
    - Returns current status from DB
    - Checks Celery task state if pending
    - Updates DB from task result if task completed
    - Never performs synchronous generation
    - Returns presigned URLs when ready
    """
    tenant: Tenant = request.state.tenant
    correlation_id = getattr(request.state, "correlation_id", None)
    
    # Extract scopes to determine allowed audience
    scopes = get_api_key_scopes(request, db)
    
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
    
    # Find evidence pack (determine audience from scopes)
    determined_audience = determine_audience_from_scopes(scopes)
    
    evidence_pack = (
        db.query(EvidencePack)
        .filter(
            EvidencePack.tenant_id == tenant.id,
            EvidencePack.certificate_id == certificate.id,
            EvidencePack.audience == determined_audience,
        )
        .first()
    )
    
    if not evidence_pack:
        return EvidencePackResponse(
            status="not_found",
            certificate_id=certificate_id,
        )
    
    # Enforce audience access
    enforce_audience_access("download", scopes, determined_audience, evidence_pack.audience)
    
    # If pending, check Celery task status
    if evidence_pack.status == "pending":
        celery_app = get_celery_app()
        task_id = _get_deterministic_task_id(certificate.id, tenant.id)
        
        from celery.result import AsyncResult
        
        task_result = AsyncResult(task_id, app=celery_app)
        task_state = task_result.state
        
        # Check if task has been pending too long
        time_elapsed = datetime.now(timezone.utc) - evidence_pack.created_at.replace(tzinfo=timezone.utc)
        if time_elapsed > timedelta(minutes=EVIDENCE_PACK_TIMEOUT_MINUTES):
            if task_state in ("PENDING", "STARTED"):
                # Task stuck - re-enqueue with new task_id
                logger.warning(
                    f"Evidence pack task stuck for {time_elapsed}, re-enqueueing",
                    extra={
                        "correlation_id": correlation_id,
                        "certificate_id": certificate_id,
                        "task_id": task_id,
                        "task_state": task_state,
                    },
                )
                
                # Re-enqueue with timestamp suffix
                retry_task_id = f"{task_id}_retry_{int(datetime.now(timezone.utc).timestamp())}"
                try:
                    task_signature = celery_app.signature(
                        "origin_worker.tasks.generate_evidence_pack",
                        args=[certificate.certificate_id, tenant.id, evidence_pack.formats or [], evidence_pack.audience],
                        task_id=retry_task_id,
                    )
                    task_signature.apply_async()
                    
                    return EvidencePackResponse(
                        status="pending",
                        certificate_id=certificate_id,
                        audience=evidence_pack.audience,
                        formats=evidence_pack.formats,
                        poll_url=f"/v1/evidence-packs/{certificate_id}",
                        retry_after_seconds=30,
                        task_state="stuck_requeued",
                    )
                except Exception as e:
                    logger.error(f"Failed to re-enqueue stuck task: {e}", exc_info=True)
        
        # Update DB from task result if available
        if task_state == "SUCCESS":
            task_data = task_result.result
            if isinstance(task_data, dict):
                # Update DB from task result
                evidence_pack.status = "ready"
                evidence_pack.storage_refs = task_data.get("storage_refs", {})
                evidence_pack.formats = task_data.get("formats", [])
                evidence_pack.ready_at = datetime.now(timezone.utc)
                evidence_pack.error_code = None
                evidence_pack.error_message = None
                db.commit()
                
                logger.info(
                    f"Updated evidence pack from task result",
                    extra={
                        "correlation_id": correlation_id,
                        "certificate_id": certificate_id,
                    },
                )
        
        elif task_state == "FAILURE":
            # Task failed - update status
            error_info = task_result.info
            error_message = str(error_info) if error_info else "Unknown error"
            
            evidence_pack.status = "failed"
            evidence_pack.error_code = "GENERATION_FAILED"
            evidence_pack.error_message = error_message[:500]  # Sanitize length
            db.commit()
            
            logger.warning(
                f"Evidence pack generation failed: {error_message}",
                extra={
                    "correlation_id": correlation_id,
                    "certificate_id": certificate_id,
                },
            )
        
        # Refresh from DB
        db.refresh(evidence_pack)
    
    # Build response
    response = _build_response(evidence_pack, certificate_id, db)
    
    # Add Retry-After header for pending
    if evidence_pack.status == "pending":
        return Response(
            content=response.model_dump_json(),
            media_type="application/json",
            headers={"Retry-After": "30"},
        )
    
    return response


def _build_response(evidence_pack: EvidencePack, certificate_id: str, db: Session) -> EvidencePackResponse:
    """Build EvidencePackResponse from EvidencePack model."""
    # Generate presigned URLs
    signed_urls = {}
    download_urls = {}
    storage_service = get_storage_service()
    
    if evidence_pack.storage_refs:
        for fmt, object_key in evidence_pack.storage_refs.items():
            if isinstance(object_key, str) and object_key.startswith("evidence/"):
                # Generate presigned URL
                presigned = storage_service.generate_signed_url(object_key, expires_in_seconds=3600)
                if presigned:
                    signed_urls[fmt] = presigned
                
                # Legacy download URL
                download_urls[fmt] = f"/v1/evidence-packs/{certificate_id}/download/{fmt}"
    
    return EvidencePackResponse(
        status=evidence_pack.status,
        certificate_id=certificate_id,
        audience=evidence_pack.audience,
        version=evidence_pack.evidence_version or "origin-evidence-v2",
        evidence_hash=evidence_pack.evidence_hash,
        formats=evidence_pack.formats or [],
        available_formats=evidence_pack.formats or [],
        signed_urls=signed_urls if signed_urls else None,
        download_urls=download_urls if download_urls else None,
        generated_at=evidence_pack.created_at.isoformat() if evidence_pack.created_at else None,
        ready_at=evidence_pack.ready_at.isoformat() if evidence_pack.ready_at else None,
        poll_url=f"/v1/evidence-packs/{certificate_id}" if evidence_pack.status == "pending" else None,
        error_code=evidence_pack.error_code,
        error_message=evidence_pack.error_message,
    )


@router.get("/evidence-packs/{certificate_id}/download/{format}")
async def download_evidence_pack(
    certificate_id: str,
    format: str,
    request: Request,
    db: Session = Depends(get_db),
    stream: bool = False,  # Query param: ?stream=1 to force streaming instead of redirect
):
    """
    Download evidence pack artifact.
    
    Prefers redirect to presigned URL (302) when available.
    Use ?stream=1 to force streaming bytes instead of redirect.
    """
    tenant: Tenant = request.state.tenant
    
    # Extract scopes and determine audience
    scopes = get_api_key_scopes(request, db)
    determined_audience = determine_audience_from_scopes(scopes)
    
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    
    # Find evidence pack
    evidence_pack = (
        db.query(EvidencePack)
        .filter(
            EvidencePack.tenant_id == tenant.id,
            EvidencePack.certificate_id == certificate.id,
            EvidencePack.audience == determined_audience,
        )
        .first()
    )
    
    if not evidence_pack or evidence_pack.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence pack not ready",
        )
    
    # Enforce audience access
    enforce_audience_access("download", scopes, determined_audience, evidence_pack.audience)
    
    # Validate format
    allowed_formats = {"json", "pdf", "html"}
    if format not in allowed_formats:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid format: {format}. Allowed: {allowed_formats}",
        )
    
    # Get storage reference
    storage_ref = evidence_pack.storage_refs.get(format) if evidence_pack.storage_refs else None
    if not storage_ref:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Format {format} not available",
        )
    
    storage_service = get_storage_service()
    
    # If presigned URL available and not streaming, redirect
    if isinstance(storage_ref, str) and storage_ref.startswith("evidence/") and not stream:
        presigned = storage_service.generate_signed_url(storage_ref, expires_in_seconds=3600)
        if presigned:
            return Response(status_code=status.HTTP_302_FOUND, headers={"Location": presigned})
    
    # Otherwise, stream bytes
    try:
        if isinstance(storage_ref, str) and storage_ref.startswith("evidence/"):
            content = storage_service.get_object(storage_ref)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid storage reference",
            )
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        logger.error(f"Failed to retrieve artifact: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve artifact",
        )
    
    # Log download for audit
    logger.info(
        f"Evidence pack download: certificate_id={certificate_id}, format={format}, audience={determined_audience}",
        extra={
            "certificate_id": certificate_id,
            "format": format,
            "audience": determined_audience,
            "tenant_id": tenant.id,
        },
    )
    
    content_types = {
        "json": "application/json",
        "pdf": "application/pdf",
        "html": "text/html",
    }
    
    return Response(
        content=content,
        media_type=content_types.get(format, "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="evidence.{format}"',
        },
    )

