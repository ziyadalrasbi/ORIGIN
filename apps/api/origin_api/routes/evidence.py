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

    # Trigger async generation (will be handled by worker)
    # For now, generate synchronously
    generator = EvidencePackGenerator(db)
    artifacts = {}

    if "json" in formats:
        artifacts["json"] = generator.generate_json(certificate, upload)

    if "pdf" in formats:
        artifacts["pdf"] = generator.generate_pdf(certificate, upload)

    if "html" in formats:
        artifacts["html"] = generator.generate_html(certificate, upload)

    # Save artifacts
    storage_refs = generator.save_artifacts(
        certificate.certificate_id, formats, artifacts
    )

    # Update evidence pack
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

    # Generate signed URLs (for now, return paths - in production, use S3 signed URLs)
    signed_urls = {}
    if evidence_pack.storage_refs:
        for fmt, path in evidence_pack.storage_refs.items():
            # In production, generate S3 signed URL
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

    # Get storage path
    storage_path = evidence_pack.storage_refs.get(format)
    if not storage_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Format {format} not available",
        )

    # Read file
    from pathlib import Path

    file_path = Path(storage_path)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Determine content type
    content_types = {
        "json": "application/json",
        "pdf": "application/pdf",
        "html": "text/html",
    }

    with open(file_path, "rb") as f:
        content = f.read()

    return Response(
        content=content,
        media_type=content_types.get(format, "application/octet-stream"),
        headers={
            "Content-Disposition": f'attachment; filename="evidence.{format}"',
        },
    )

