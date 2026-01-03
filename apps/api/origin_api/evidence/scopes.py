"""Evidence pack scope and audience enforcement.

Defines evidence read scopes and enforces audience access rules.
"""

import json
import logging
from typing import Optional

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

# Evidence scopes
EVIDENCE_SCOPES = {
    "request": {
        "internal": "evidence:request:internal",
        "dsp": "evidence:request:dsp",
        "regulator": "evidence:request:regulator",
    },
    "download": {
        "internal": "evidence:download:internal",
        "dsp": "evidence:download:dsp",
        "regulator": "evidence:download:regulator",
    },
}


def get_api_key_scopes(request: Request, db) -> list[str]:
    """
    Extract API key scopes from request.
    
    Returns empty list if scopes not available (backward compatibility).
    """
    api_key = request.headers.get("x-api-key")
    if not api_key:
        return []
    
    try:
        from origin_api.auth.api_key import verify_api_key
        from origin_api.models import APIKey
        
        # Find API key object
        api_key_objs = (
            db.query(APIKey)
            .filter(
                APIKey.is_active == True,  # noqa: E712
                APIKey.revoked_at.is_(None),
            )
            .all()
        )
        
        for key_obj in api_key_objs:
            if verify_api_key(api_key, key_obj.hash):
                if key_obj.scopes:
                    try:
                        return json.loads(key_obj.scopes) if isinstance(key_obj.scopes, str) else key_obj.scopes
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(f"Invalid scopes format for API key {key_obj.id}")
                        return []
                return []
        
        return []
    except Exception as e:
        logger.debug(f"Error extracting API key scopes: {e}")
        return []


def determine_audience_from_scopes(scopes: list[str], requested_audience: Optional[str] = None) -> str:
    """
    Determine evidence pack audience from API key scopes.
    
    Rules:
    - If scope has evidence:request:dsp -> DSP
    - If scope has evidence:request:regulator -> REGULATOR
    - Otherwise -> INTERNAL
    
    Requested audience is validated but scope wins.
    
    Args:
        scopes: List of API key scopes
        requested_audience: Optional requested audience from request body
        
    Returns:
        Determined audience (INTERNAL, DSP, or REGULATOR)
    """
    # Check scopes in priority order
    if EVIDENCE_SCOPES["request"]["dsp"] in scopes:
        return "DSP"
    elif EVIDENCE_SCOPES["request"]["regulator"] in scopes:
        return "REGULATOR"
    else:
        # Default to INTERNAL (backward compatible)
        return "INTERNAL"


def enforce_audience_access(
    action: str,  # "request" or "download"
    scopes: list[str],
    requested_audience: str,
    target_audience: Optional[str] = None,
) -> None:
    """
    Enforce audience access rules.
    
    Rules:
    - DSP cannot request/download INTERNAL
    - INTERNAL can only request/download INTERNAL
    - REGULATOR can request/download REGULATOR (and optionally INTERNAL if explicitly allowed)
    
    Args:
        action: "request" or "download"
        scopes: API key scopes
        requested_audience: Audience being requested
        target_audience: Audience of existing evidence pack (for downloads)
        
    Raises:
        HTTPException: If access is forbidden
    """
    # Determine allowed audience from scopes
    scope_audience = determine_audience_from_scopes(scopes, requested_audience)
    
    # For downloads, check target audience
    effective_audience = target_audience if target_audience else requested_audience
    
    # Enforce rules
    if scope_audience == "DSP":
        if effective_audience == "INTERNAL":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="DSP audience cannot access INTERNAL evidence packs",
            )
        if effective_audience not in ("DSP",):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"DSP audience can only access DSP evidence packs, not {effective_audience}",
            )
    
    elif scope_audience == "INTERNAL":
        if effective_audience not in ("INTERNAL",):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"INTERNAL audience can only access INTERNAL evidence packs, not {effective_audience}",
            )
    
    elif scope_audience == "REGULATOR":
        # REGULATOR can access REGULATOR and optionally INTERNAL (if tenant allows)
        if effective_audience not in ("REGULATOR", "INTERNAL"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"REGULATOR audience cannot access {effective_audience} evidence packs",
            )
    
    # Check required scope
    required_scope = EVIDENCE_SCOPES[action].get(scope_audience.lower())
    if required_scope and required_scope not in scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required scope: {required_scope}",
        )

