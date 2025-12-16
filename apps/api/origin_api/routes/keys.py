"""Public key endpoints for certificate verification."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from origin_api.ledger.signer import get_signer

router = APIRouter(prefix="/v1", tags=["keys"])


@router.get("/keys/jwks.json")
async def get_jwks():
    """Return JSON Web Key Set for certificate verification."""
    signer = get_signer()
    jwk = signer.get_public_jwk()

    # Return as JWKS format
    return JSONResponse(content={"keys": [jwk]})


@router.get("/certificates/{certificate_id}")
async def get_certificate(certificate_id: str):
    """Get certificate with verification metadata."""
    from sqlalchemy.orm import Session
    from origin_api.db.session import get_db
    from origin_api.models import DecisionCertificate

    db: Session = next(get_db())
    certificate = (
        db.query(DecisionCertificate)
        .filter(DecisionCertificate.certificate_id == certificate_id)
        .first()
    )

    if not certificate:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certificate {certificate_id} not found",
        )

    return {
        "certificate_id": certificate.certificate_id,
        "issued_at": certificate.issued_at.isoformat(),
        "policy_version": certificate.policy_version,
        "inputs_hash": certificate.inputs_hash,
        "outputs_hash": certificate.outputs_hash,
        "ledger_hash": certificate.ledger_hash,
        "signature": certificate.signature,
        "key_id": certificate.key_id,
        "alg": certificate.alg,
        "verification": {
            "jwks_url": "/v1/keys/jwks.json",
            "instructions": "Verify signature using public key from JWKS endpoint",
        },
    }

