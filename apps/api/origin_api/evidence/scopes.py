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


def get_api_key_scopes(request: Request, db=None) -> list[str]:
    """
    Extract API key scopes from request.
    
    Uses request.state.api_key_obj (set by AuthMiddleware) to avoid DB scanning.
    Returns empty list if scopes not available (backward compatibility).
    
    Args:
        request: FastAPI Request object
        db: Optional DB session (not used, kept for backward compatibility)
    
    Returns:
        List of scope strings
    """
    # Read from request state (set by AuthMiddleware)
    api_key_obj = getattr(request.state, "api_key_obj", None)
    
    if not api_key_obj:
        # No API key object available (legacy key or not authenticated)
        return []
    
    if not api_key_obj.scopes:
        return []
    
    try:
        # Parse scopes (can be JSON string or already a list)
        if isinstance(api_key_obj.scopes, str):
            return json.loads(api_key_obj.scopes)
        elif isinstance(api_key_obj.scopes, list):
            return api_key_obj.scopes
        else:
            logger.warning(f"Invalid scopes type for API key {api_key_obj.id}: {type(api_key_obj.scopes)}")
            return []
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid scopes JSON for API key {api_key_obj.id}: {e}")
        return []
    except Exception as e:
        logger.warning(f"Error parsing scopes for API key {api_key_obj.id}: {e}")
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

