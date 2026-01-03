"""Evidence pack routes."""

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
            # Continue to generation code below

    # Create evidence pack record
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

    # Trigger async generation (will be handled by worker)
    # For now, generate synchronously
    generator = EvidencePackGenerator(db)
    artifacts = {}

    # Pass audience to generator (defaults to INTERNAL if not specified)
    audience = request_data.audience or "INTERNAL"

    # Generate artifacts
    try:
        if "json" in formats:
            artifacts["json"] = generator.generate_json(certificate, upload, audience=audience)
            logger.info("Generated JSON artifact")
    except Exception as e:
        logger.error(f"Failed to generate JSON artifact: {e}")

    try:
        if "pdf" in formats:
            artifacts["pdf"] = generator.generate_pdf(certificate, upload)
            logger.info("Generated PDF artifact")
    except Exception as e:
        logger.error(f"Failed to generate PDF artifact: {e}")

    try:
        if "html" in formats:
            artifacts["html"] = generator.generate_html(certificate, upload)
            logger.info("Generated HTML artifact")
    except Exception as e:
        logger.error(f"Failed to generate HTML artifact: {e}")

    # Save artifacts
    storage_refs = {}
    try:
        storage_refs = generator.save_artifacts(
            certificate.certificate_id, formats, artifacts
        )
        logger.info(f"Saved artifacts: {storage_refs}")
    except Exception as e:
        logger.error(f"Failed to save artifacts: {e}")
    
    # Debug: Log what we got
    logger.info(f"Generated artifacts: {list(artifacts.keys())}")
    logger.info(f"Storage refs: {storage_refs}")
    logger.info(f"Formats requested: {formats}")

    # Always use raw SQL update to ensure it works with MinimalEvidencePack objects
    import json
    formats_json = json.dumps(formats) if formats else None
    storage_refs_json = json.dumps(storage_refs) if storage_refs else None
    
    logger.info(f"Formats JSON: {formats_json}")
    logger.info(f"Storage refs JSON: {storage_refs_json}")
    
    # Update by certificate_id instead of id to ensure we get the right record
    # Use CAST instead of ::jsonb for parameterized queries
    try:
        db.execute(
            text("UPDATE evidence_packs SET status = :status, formats = CAST(:formats AS jsonb), storage_refs = CAST(:storage_refs AS jsonb), ready_at = NOW() "
                 "WHERE tenant_id = :tenant_id AND certificate_id = :certificate_id"),
            {
                "status": "ready",
                "formats": formats_json,
                "storage_refs": storage_refs_json,
                "tenant_id": tenant.id,
                "certificate_id": certificate.id,
            }
        )
        db.commit()
        logger.info("Database update successful")
    except Exception as e:
        logger.error(f"Database update failed: {e}")
        db.rollback()
        # Try again with just the essential fields
        try:
            db.execute(
                text("UPDATE evidence_packs SET status = :status, storage_refs = CAST(:storage_refs AS jsonb) WHERE tenant_id = :tenant_id AND certificate_id = :certificate_id"),
                {
                    "status": "ready",
                    "storage_refs": storage_refs_json,
                    "tenant_id": tenant.id,
                    "certificate_id": certificate.id,
                }
            )
            db.commit()
            logger.info("Fallback database update successful")
        except Exception as e2:
            logger.error(f"Fallback database update also failed: {e2}")
            db.rollback()

    # Always use the values we just saved - don't query DB again
    # The database update might have issues, but we know what we saved
    # Log what we have before processing
    logger.info(f"Raw formats variable: {formats} (type: {type(formats)})")
    logger.info(f"Raw storage_refs variable: {storage_refs} (type: {type(storage_refs)})")
    
    # Ensure we have valid types (lists/dicts, not None)
    final_formats = formats if formats is not None else []
    final_storage_refs = storage_refs if storage_refs is not None else {}
    
    # Log what we're returning (this will help debug)
    logger.info(f"Returning formats: {final_formats} (type: {type(final_formats)}, len: {len(final_formats) if isinstance(final_formats, list) else 'N/A'})")
    logger.info(f"Returning storage_refs: {final_storage_refs} (type: {type(final_storage_refs)}, keys: {list(final_storage_refs.keys()) if isinstance(final_storage_refs, dict) else 'N/A'})")
    logger.info(f"Artifacts generated: {list(artifacts.keys())}")
    
    # Get evidence_hash from evidence pack (safely handle missing columns)
    evidence_hash = getattr(evidence_pack, 'evidence_hash', None) if evidence_pack else None
    evidence_version = getattr(evidence_pack, 'evidence_version', None) or "origin-evidence-v2"
    
    # Build download URLs for easy access
    download_urls = {}
    if final_storage_refs:
        for fmt in final_formats:
            download_urls[fmt] = f"/v1/evidence-packs/{request_data.certificate_id}/download/{fmt}"
    
    # Always return the actual values, not None
    # Empty lists/dicts are valid, so return them as-is
    return {
        "status": "ready",
        "certificate_id": request_data.certificate_id,
        "version": evidence_version,
        "evidence_hash": evidence_hash,
        "formats": final_formats,  # Return list even if empty
        "available_formats": final_formats,  # Return list even if empty
        "storage_refs": final_storage_refs,  # Return dict even if empty
        "download_urls": download_urls,
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

    # Get storage path
    storage_path = evidence_pack.storage_refs.get(format) if evidence_pack.storage_refs else None
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

