"""Evidence pack routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from origin_api.db.session import get_db
from origin_api.evidence.generator import EvidencePackGenerator
from origin_api.models import DecisionCertificate, EvidencePack, Upload
from origin_api.models.tenant import Tenant

router = APIRouter(prefix="/v1", tags=["evidence"])


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
    evidence_pack = (
        db.query(EvidencePack)
        .filter(
            EvidencePack.tenant_id == tenant.id,
            EvidencePack.certificate_id == certificate.id,
        )
        .first()
    )

    if evidence_pack and evidence_pack.status == "ready":
        # Return existing
        return {
            "status": "ready",
            "certificate_id": request_data.certificate_id,
            "formats": evidence_pack.formats,
            "storage_refs": evidence_pack.storage_refs,
        }

    # Create evidence pack record
    if not evidence_pack:
        evidence_pack = EvidencePack(
            tenant_id=tenant.id,
            certificate_id=certificate.id,
            status="pending",
            formats=formats,
        )
        db.add(evidence_pack)
        db.commit()

    # Enqueue async generation job
    try:
        from origin_worker.tasks import generate_evidence_pack
        generate_evidence_pack.delay(certificate.certificate_id, formats)
    except Exception as e:
        # Fallback to sync if worker unavailable
        logger.warning(f"Worker unavailable, generating synchronously: {e}")
        from origin_api.evidence.generator import EvidencePackGenerator
        generator = EvidencePackGenerator(db)
        artifacts = {}
        if "json" in formats:
            artifacts["json"] = generator.generate_json(certificate, upload)
        if "pdf" in formats:
            artifacts["pdf"] = generator.generate_pdf(certificate, upload)
        if "html" in formats:
            artifacts["html"] = generator.generate_html(certificate, upload)
        storage_refs = generator.save_artifacts(certificate.certificate_id, formats, artifacts)
        evidence_pack.status = "ready"
        evidence_pack.storage_refs = storage_refs
        evidence_pack.ready_at = datetime.utcnow()
        db.commit()

    return {
        "status": "ready",
        "certificate_id": request_data.certificate_id,
        "formats": formats,
        "storage_refs": storage_refs,
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

    # Get evidence pack
    evidence_pack = (
        db.query(EvidencePack)
        .filter(
            EvidencePack.tenant_id == tenant.id,
            EvidencePack.certificate_id == certificate.id,
        )
        .first()
    )

    if not evidence_pack:
        return {
            "status": "not_found",
            "certificate_id": certificate_id,
        }

    # Generate signed URLs from storage
    signed_urls = {}
    storage = S3Storage()
    
    if evidence_pack.storage_keys:
        for fmt, storage_key in evidence_pack.storage_keys.items():
            try:
                signed_url = storage.get_signed_url(
                    storage_key, expires_in=settings.evidence_signed_url_ttl
                )
                signed_urls[fmt] = signed_url
            except Exception as e:
                logger.error(f"Error generating signed URL for {fmt}: {e}")
    elif evidence_pack.storage_refs:  # Legacy fallback
        for fmt, path in evidence_pack.storage_refs.items():
            signed_urls[fmt] = f"/v1/evidence-packs/{certificate_id}/download/{fmt}"

    return {
        "status": evidence_pack.status,
        "certificate_id": certificate_id,
        "formats": evidence_pack.formats or [],
        "signed_urls": signed_urls,
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

    evidence_pack = (
        db.query(EvidencePack)
        .filter(
            EvidencePack.tenant_id == tenant.id,
            EvidencePack.certificate_id == certificate.id,
        )
        .first()
    )

    if not evidence_pack or evidence_pack.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence pack not ready",
        )

    # Get storage key
    storage_key = evidence_pack.storage_keys.get(format) if evidence_pack.storage_keys else None
    if not storage_key:
        # Legacy fallback
        storage_path = evidence_pack.storage_refs.get(format) if evidence_pack.storage_refs else None
        if storage_path:
            from pathlib import Path
            file_path = Path(storage_path)
            if file_path.exists():
                with open(file_path, "rb") as f:
                    content = f.read()
            else:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Format {format} not available",
            )
    else:
        # Get from object storage
        storage = S3Storage()
        content = storage.get_object(storage_key)

    # Determine content type
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

