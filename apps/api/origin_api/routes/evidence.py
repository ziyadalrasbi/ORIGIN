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
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
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
EVIDENCE_PACK_STUCK_THRESHOLD_MINUTES = settings.evidence_pack_stuck_threshold_minutes


class EvidencePackRequest(BaseModel):
    """Evidence pack generation request."""

    certificate_id: str
    format: str = Field(default="json", description="json, pdf, html, or comma-separated list")
    audience: Optional[str] = Field(
        default=None, description="INTERNAL, DSP, REGULATOR (determined from scopes if not provided)"
    )


class EvidencePackResponse(BaseModel):
    """Evidence pack status response.
    
    Task field semantics:
    - task_id: Celery task ID (hash-based, deterministic)
    - task_status: ONLY Celery task states (PENDING, STARTED, RETRY, SUCCESS, FAILURE) or None if unknown
    - task_state: Deprecated, always mirrors task_status for backward compatibility
    - pipeline_event: Custom pipeline events (STUCK_REQUEUED, ENQUEUED, etc.) - separate from task_status
    """

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
    task_id: Optional[str] = None  # Celery task ID (hash-based, deterministic)
    task_status: Optional[str] = None  # ONLY: PENDING, STARTED, RETRY, SUCCESS, FAILURE, or None if unknown
    task_state: Optional[str] = None  # Deprecated: always mirrors task_status for backward compatibility
    pipeline_event: Optional[str] = None  # Custom pipeline events: STUCK_REQUEUED, ENQUEUED, POLLING, UPDATED_FROM_TASK_RESULT
    error_code: Optional[str] = None  # Set for transient infra failures (broker down) or permanent failures
    error_message: Optional[str] = None


def _get_idempotency_key(tenant_id: int, certificate_id: int, audience: str, formats: list[str]) -> str:
    """Generate deterministic idempotency key for evidence pack requests."""
    sorted_formats = ",".join(sorted(formats))
    return f"evidence:{tenant_id}:{certificate_id}:{audience}:{sorted_formats}"


def _get_deterministic_task_id(certificate_id: int, tenant_id: int, audience: str, formats: list[str]) -> str:
    """
    Generate deterministic task ID for Celery task using hash-based approach.
    
    Uses SHA256 hash of idempotency key to ensure safe length and character set.
    """
    import hashlib
    
    idempotency_key = _get_idempotency_key(tenant_id, certificate_id, audience, formats)
    hash_digest = hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()[:32]
    return f"evidence_pack_{hash_digest}"


def _pending_response(
    certificate_id: str,
    audience: str,
    formats: list[str],
    task_id: Optional[str] = None,
    task_status: Optional[str] = None,
    pipeline_event: Optional[str] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    retry_after: int = 30,
) -> JSONResponse:
    """
    Create consistent pending response (HTTP 202 Accepted).
    
    All pending responses use 202 Accepted + Retry-After header for consistency.
    """
    content = {
        "status": "pending",
        "certificate_id": certificate_id,
        "audience": audience,
        "formats": formats,
        "poll_url": f"/v1/evidence-packs/{certificate_id}",
        "retry_after_seconds": retry_after,
    }
    
    if task_id:
        content["task_id"] = task_id
    if task_status:
        content["task_status"] = task_status
        content["task_state"] = task_status  # Mirror for backward compatibility
    if pipeline_event:
        content["pipeline_event"] = pipeline_event
    if error_code:
        content["error_code"] = error_code
    if error_message:
        content["error_message"] = error_message
    
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=content,
        headers={"Retry-After": str(retry_after)},
    )


def _failed_response(
    certificate_id: str,
    audience: str,
    formats: list[str],
    error_code: str,
    error_message: str,
    retry_after: int = 30,
) -> JSONResponse:
    """
    Create consistent failed response (HTTP 503 Service Unavailable for infra failures).
    
    Used for transient infrastructure failures (broker down, Celery unavailable).
    """
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "pending",  # Keep as pending for transient failures
            "certificate_id": certificate_id,
            "audience": audience,
            "formats": formats,
            "error_code": error_code,
            "error_message": error_message,
            "retry_after_seconds": retry_after,
        },
        headers={"Retry-After": str(retry_after)},
    )


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
    Falls back to SELECT FOR UPDATE if unique constraint not yet applied.
    """
    formats_json = json.dumps(formats) if formats else None
    now = datetime.now(timezone.utc)
    
    # Try INSERT ... ON CONFLICT (requires unique constraint)
    try:
        stmt = (
            insert(EvidencePack.__table__)
            .values(
                tenant_id=tenant_id,
                certificate_id=certificate_id,
                audience=audience,
                status=status,
                formats=formats_json,
                created_at=now,
                error_code=error_code,
                error_message=error_message,
            )
            .on_conflict_do_update(
                constraint="uq_evidence_packs_tenant_certificate_audience",
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
        if row:
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
                canonical_json=getattr(row, "canonical_json", None),
                evidence_hash=getattr(row, "evidence_hash", None),
                evidence_version=getattr(row, "evidence_version", None),
                canonical_created_at=getattr(row, "canonical_created_at", None),
                error_code=getattr(row, "error_code", None),
                error_message=getattr(row, "error_message", None),
            )
            return evidence_pack
    except Exception as e:
        # Fallback: SELECT FOR UPDATE (if unique constraint not applied yet)
        logger.debug(f"INSERT ON CONFLICT failed, using SELECT FOR UPDATE fallback: {e}")
        db.rollback()
    
    # Fallback: SELECT FOR UPDATE with manual upsert
    evidence_pack = (
        db.query(EvidencePack)
        .filter(
            EvidencePack.tenant_id == tenant_id,
            EvidencePack.certificate_id == certificate_id,
            EvidencePack.audience == audience,
        )
        .with_for_update()
        .first()
    )
    
    if evidence_pack:
        # Update existing
        evidence_pack.status = status
        evidence_pack.formats = formats_json
        evidence_pack.error_code = error_code
        evidence_pack.error_message = error_message
        db.commit()
        return evidence_pack
    else:
        # Create new
        evidence_pack = EvidencePack(
            tenant_id=tenant_id,
            certificate_id=certificate_id,
            audience=audience,
            status=status,
            formats=formats_json,
            created_at=now,
            error_code=error_code,
            error_message=error_message,
        )
        db.add(evidence_pack)
        db.commit()
        db.refresh(evidence_pack)
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
    scopes = get_api_key_scopes(request)
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
    
    # Use SELECT FOR UPDATE for atomic idempotency check
    # This prevents race conditions when multiple requests come in simultaneously
    now = datetime.now(timezone.utc)
    stuck_threshold = timedelta(minutes=EVIDENCE_PACK_STUCK_THRESHOLD_MINUTES)
    
    evidence_pack = (
        db.query(EvidencePack)
        .filter(
            EvidencePack.tenant_id == tenant.id,
            EvidencePack.certificate_id == certificate.id,
            EvidencePack.audience == determined_audience,
        )
        .with_for_update()
        .first()
    )
    
    if evidence_pack:
        # Evidence pack exists - check status
        if evidence_pack.status == "ready":
            # Check if all requested formats are available
            existing_formats = evidence_pack.formats or []
            if set(formats) <= set(existing_formats):
                # All formats available, return ready status
                logger.info(
                    f"Evidence pack already ready with requested formats",
                    extra={
                        "correlation_id": correlation_id,
                        "certificate_id": certificate.certificate_id,
                        "tenant_id": tenant.id,
                        "audience": determined_audience,
                        "formats": formats,
                    },
                )
                return _build_response(evidence_pack, certificate.certificate_id, db)
        
        # Check if task is stuck or should be re-enqueued
        if evidence_pack.status in ("pending", "processing"):
            if evidence_pack.last_enqueued_at:
                time_since_enqueue = now - evidence_pack.last_enqueued_at.replace(tzinfo=timezone.utc)
                if time_since_enqueue < stuck_threshold:
                    # Not stuck yet - return pending without re-enqueueing
                    logger.info(
                        f"Evidence pack generation in progress, not stuck yet",
                        extra={
                            "correlation_id": correlation_id,
                            "certificate_id": certificate.certificate_id,
                            "tenant_id": tenant.id,
                            "status": evidence_pack.status,
                            "time_since_enqueue_minutes": time_since_enqueue.total_seconds() / 60,
                            "task_id": evidence_pack.task_id,
                        },
                    )
                    # Return consistent pending response
                    return _pending_response(
                        certificate_id=request_data.certificate_id,
                        audience=determined_audience,
                        formats=formats,
                        task_id=evidence_pack.task_id,
                        task_status=None,  # Celery unavailable, status unknown
                        pipeline_event="POLLING",
                    )
                # Stuck - will re-enqueue below
                logger.warning(
                    f"Evidence pack task stuck, re-enqueueing",
                    extra={
                        "correlation_id": correlation_id,
                        "certificate_id": certificate.certificate_id,
                        "tenant_id": tenant.id,
                        "time_since_enqueue_minutes": time_since_enqueue.total_seconds() / 60,
                        "task_id": evidence_pack.task_id,
                    },
                )
        
        # Update existing record
        evidence_pack.status = "pending"
        evidence_pack.formats = formats
        evidence_pack.error_code = None
        evidence_pack.error_message = None
        evidence_pack.updated_at = now
    else:
        # Create new evidence pack record
        evidence_pack = EvidencePack(
            tenant_id=tenant.id,
            certificate_id=certificate.id,
            audience=determined_audience,
            status="pending",
            formats=formats,
            created_at=now,
            updated_at=now,
        )
        db.add(evidence_pack)
    
    # Generate task ID and enqueue
    task_id = _get_deterministic_task_id(certificate.id, tenant.id, determined_audience, formats)
    
    # Try to get Celery app (may raise ImportError)
    try:
        celery_app = get_celery_app()
    except ImportError as e:
        # Celery not available - return 503
        logger.error(
            f"Celery unavailable, cannot enqueue evidence pack task: {e}",
            extra={
                "correlation_id": correlation_id,
                "certificate_id": certificate.certificate_id,
                "tenant_id": tenant.id,
                "audience": determined_audience,
                "formats": formats,
            },
            exc_info=True,
        )
        # Keep status as pending for transient failure (allows retry)
        evidence_pack.status = "pending"
        evidence_pack.error_code = "CELERY_UNAVAILABLE"
        evidence_pack.error_message = "Evidence pack generation service unavailable (Celery not installed)"
        evidence_pack.updated_at = now
        db.commit()
        
        return _failed_response(
            certificate_id=request_data.certificate_id,
            audience=determined_audience,
            formats=formats,
            error_code="CELERY_UNAVAILABLE",
            error_message="Evidence pack generation service unavailable (Celery not installed)",
        )
    
    # Check if task is already running (using stored task_id)
    from celery.result import AsyncResult
    
    if evidence_pack.task_id:
        existing_task = AsyncResult(evidence_pack.task_id, app=celery_app)
        task_state = existing_task.state
        
        if task_state in ("STARTED", "RETRY", "PENDING"):
            # Task already running or queued - return pending without re-enqueueing
            logger.info(
                f"Evidence pack task already in progress: {evidence_pack.task_id} (state={task_state})",
                extra={
                    "correlation_id": correlation_id,
                    "certificate_id": certificate.certificate_id,
                    "tenant_id": tenant.id,
                    "task_id": evidence_pack.task_id,
                },
            )
            # Update last_polled_at for telemetry
            evidence_pack.last_polled_at = now
            evidence_pack.updated_at = now
            db.commit()
            
            # Return consistent pending response with Celery task status
            return _pending_response(
                certificate_id=request_data.certificate_id,
                audience=determined_audience,
                formats=formats,
                task_id=evidence_pack.task_id,
                task_status=task_state,  # Celery state: PENDING/STARTED/RETRY
                pipeline_event="POLLING",
            )
    
    # Enqueue new task
    try:
        task_signature = celery_app.signature(
            "origin_worker.tasks.generate_evidence_pack",
            args=[certificate.certificate_id, tenant.id, formats, determined_audience],
            task_id=task_id,
        )
        task = task_signature.apply_async()
        
        # Update evidence pack with task tracking
        evidence_pack.task_id = task_id
        evidence_pack.last_enqueued_at = now
        evidence_pack.updated_at = now
        db.commit()
        
        logger.info(
            f"Enqueued evidence pack generation task: {task.id}",
            extra={
                "correlation_id": correlation_id,
                "certificate_id": certificate.certificate_id,
                "tenant_id": tenant.id,
                "audience": determined_audience,
                "formats": formats,
                "task_id": task_id,
            },
        )
    except (ConnectionError, TimeoutError) as e:
        # Broker connectivity failures - return 503
        logger.error(
            f"Broker connectivity failure, cannot enqueue evidence pack task: {e}",
            extra={
                "correlation_id": correlation_id,
                "certificate_id": certificate.certificate_id,
                "tenant_id": tenant.id,
                "audience": determined_audience,
                "formats": formats,
            },
            exc_info=True,
        )
        # Keep status as pending for transient failure (allows retry)
        evidence_pack.status = "pending"
        evidence_pack.error_code = "BROKER_UNAVAILABLE"
        evidence_pack.error_message = "Broker unavailable (connection/timeout error)"
        evidence_pack.updated_at = now
        db.commit()
        
        return _failed_response(
            certificate_id=request_data.certificate_id,
            audience=determined_audience,
            formats=formats,
            error_code="BROKER_UNAVAILABLE",
            error_message="Broker unavailable (connection/timeout error)",
        )
    except Exception as broker_error:
        # Check if it's a kombu/broker error
        error_type = type(broker_error).__name__
        is_broker_error = (
            "OperationalError" in error_type or
            "KombuError" in error_type or
            "BrokerConnection" in error_type or
            "Connection" in error_type
        )
        
        if is_broker_error:
            # Broker-related error - return 503
            logger.error(
                f"Broker error enqueueing evidence pack task: {broker_error}",
                extra={
                    "correlation_id": correlation_id,
                    "certificate_id": certificate.certificate_id,
                    "tenant_id": tenant.id,
                    "audience": determined_audience,
                    "formats": formats,
                    "error_type": error_type,
                },
                exc_info=True,
            )
            # Keep status as pending for transient failure (allows retry)
            evidence_pack.status = "pending"
            evidence_pack.error_code = "BROKER_UNAVAILABLE"
            evidence_pack.error_message = f"Broker error: {str(broker_error)[:200]}"
            evidence_pack.updated_at = now
            db.commit()
            
            return _failed_response(
                certificate_id=request_data.certificate_id,
                audience=determined_audience,
                formats=formats,
                error_code="BROKER_UNAVAILABLE",
                error_message=f"Broker error: {str(broker_error)[:200]}",
            )
        
        # Re-raise if not a broker error (will be caught by outer exception handler)
        raise
    except Exception as e:
        # Other errors (broker misconfigured, kombu errors, etc.) - return 503
        logger.error(
            f"Failed to enqueue evidence pack task: {e}",
            extra={
                "correlation_id": correlation_id,
                "certificate_id": certificate.certificate_id,
                "tenant_id": tenant.id,
                "audience": determined_audience,
                "formats": formats,
            },
            exc_info=True,
        )
        # Update status to failed
        evidence_pack.status = "failed"
        evidence_pack.error_code = "TASK_ENQUEUE_FAILED"
        evidence_pack.error_message = f"Failed to enqueue generation task: {str(e)[:200]}"
        evidence_pack.updated_at = now
        db.commit()
        
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "failed",
                "certificate_id": request_data.certificate_id,
                "audience": determined_audience,
                "formats": formats,
                "error_code": "TASK_ENQUEUE_FAILED",
                "error_message": f"Failed to enqueue generation task: {str(e)[:200]}",
            },
            headers={"Retry-After": "30"},
        )
    
    # Task successfully enqueued
    return _pending_response(
        certificate_id=request_data.certificate_id,
        audience=determined_audience,
        formats=formats,
        task_id=task_id,
        task_status="PENDING",  # Task is queued, awaiting worker pickup
        pipeline_event="ENQUEUED",
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
    scopes = get_api_key_scopes(request)
    
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
    
    # Update last_polled_at for telemetry
    now = datetime.now(timezone.utc)
    evidence_pack.last_polled_at = now
    evidence_pack.updated_at = now
    db.commit()
    
    # If pending, check Celery task status
    if evidence_pack.status == "pending":
        # Try to get Celery app (may raise ImportError)
        try:
            celery_app = get_celery_app()
        except ImportError:
            # Celery not available - return pending with error info
            logger.warning(
                f"Celery unavailable during poll, evidence pack may be stuck",
                extra={
                    "correlation_id": correlation_id,
                    "certificate_id": certificate_id,
                    "tenant_id": tenant.id,
                    "task_id": evidence_pack.task_id,
                },
            )
            return EvidencePackResponse(
                status="pending",
                certificate_id=certificate_id,
                audience=evidence_pack.audience,
                formats=evidence_pack.formats or [],
                poll_url=f"/v1/evidence-packs/{certificate_id}",
                retry_after_seconds=30,
                error_code="CELERY_UNAVAILABLE",
                error_message="Evidence pack generation service unavailable",
            )
        
        task_id = evidence_pack.task_id or _get_deterministic_task_id(certificate.id, tenant.id, evidence_pack.audience, evidence_pack.formats or [])
        
        from celery.result import AsyncResult
        
        task_result = AsyncResult(task_id, app=celery_app)
        task_state = task_result.state
        
        # Check if task has been pending too long (stuck detection)
        if evidence_pack.last_enqueued_at:
            time_since_enqueue = now - evidence_pack.last_enqueued_at.replace(tzinfo=timezone.utc)
            if time_since_enqueue > stuck_threshold:
                if task_state in ("PENDING", "STARTED"):
                    # Task stuck - re-enqueue with new task_id
                    logger.warning(
                        f"Evidence pack task stuck for {time_since_enqueue}, re-enqueueing",
                        extra={
                            "correlation_id": correlation_id,
                            "certificate_id": certificate_id,
                            "task_id": task_id,
                            "task_state": task_state,
                            "time_since_enqueue_minutes": time_since_enqueue.total_seconds() / 60,
                        },
                    )
                    
                    # Re-enqueue with timestamp suffix
                    retry_task_id = f"{task_id}_retry_{int(now.timestamp())}"
                    try:
                        task_signature = celery_app.signature(
                            "origin_worker.tasks.generate_evidence_pack",
                            args=[certificate.certificate_id, tenant.id, evidence_pack.formats or [], evidence_pack.audience],
                            task_id=retry_task_id,
                        )
                        task_signature.apply_async()
                        
                        # Update task tracking
                        evidence_pack.task_id = retry_task_id
                        evidence_pack.last_enqueued_at = now
                        evidence_pack.updated_at = now
                        db.commit()
                        
                        response_data = {
                            "status": "pending",
                            "certificate_id": certificate_id,
                            "audience": evidence_pack.audience,
                            "formats": evidence_pack.formats,
                            "poll_url": f"/v1/evidence-packs/{certificate_id}",
                            "retry_after_seconds": 30,
                            "task_id": retry_task_id,
                            "task_status": "stuck_requeued",
                            "task_state": "stuck_requeued",  # Backward compatibility
                        }
                        return JSONResponse(
                            status_code=status.HTTP_202_ACCEPTED,
                            content=response_data,
                            headers={"Retry-After": "30"},
                        )
                    except Exception as e:
                        logger.error(
                            f"Failed to re-enqueue stuck task: {e}",
                            extra={
                                "correlation_id": correlation_id,
                                "certificate_id": certificate_id,
                                "task_id": task_id,
                            },
                            exc_info=True,
                        )
        
        # Update DB from task result if available
        if task_state == "SUCCESS":
            task_data = task_result.result
            if isinstance(task_data, dict):
                # Update DB from task result
                evidence_pack.status = "ready"
                evidence_pack.storage_refs = task_data.get("storage_refs", {})
                evidence_pack.formats = task_data.get("formats", [])
                evidence_pack.ready_at = now
                evidence_pack.error_code = None
                evidence_pack.error_message = None
                evidence_pack.updated_at = now
                db.commit()
                
                logger.info(
                    f"Updated evidence pack from task result",
                    extra={
                        "correlation_id": correlation_id,
                        "certificate_id": certificate_id,
                        "tenant_id": tenant.id,
                        "audience": evidence_pack.audience,
                        "task_id": task_id,
                    },
                )
        
        elif task_state == "FAILURE":
            # Task failed - update status
            error_info = task_result.info
            error_message = str(error_info) if error_info else "Unknown error"
            
            evidence_pack.status = "failed"
            evidence_pack.error_code = "GENERATION_FAILED"
            evidence_pack.error_message = error_message[:500]  # Sanitize length
            evidence_pack.updated_at = now
            db.commit()
            
            logger.warning(
                f"Evidence pack generation failed: {error_message}",
                extra={
                    "correlation_id": correlation_id,
                    "certificate_id": certificate_id,
                    "tenant_id": tenant.id,
                    "audience": evidence_pack.audience,
                    "task_id": task_id,
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
    
    # Get task status from Celery if pending and task_id exists
    task_status = None
    if evidence_pack.status == "pending" and evidence_pack.task_id:
        try:
            from celery.result import AsyncResult
            celery_app = get_celery_app()
            task_result = AsyncResult(evidence_pack.task_id, app=celery_app)
            task_status = task_result.state
        except (ImportError, ConnectionError, Exception):
            # Celery unavailable or task not found - use None
            pass
    
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
        task_id=evidence_pack.task_id,
        task_status=task_status,
        task_state=task_status,  # Backward compatibility
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
    scopes = get_api_key_scopes(request)
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

