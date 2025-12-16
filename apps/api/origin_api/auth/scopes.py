"""API key scope validation utilities."""

import json
import logging
from typing import List

logger = logging.getLogger(__name__)

# Valid scope names
VALID_SCOPES = {
    "ingest:write",
    "evidence:read",
    "evidence:write",
    "certificates:read",
    "webhooks:read",
    "webhooks:write",
    "admin",
}


def validate_scopes(scopes: str) -> List[str]:
    """
    Validate and parse scopes from JSON string.
    
    Args:
        scopes: JSON string array of scopes
        
    Returns:
        List of validated scope strings
        
    Raises:
        ValueError: If scopes are invalid
    """
    if not scopes:
        return []
    
    try:
        scope_list = json.loads(scopes) if isinstance(scopes, str) else scopes
        if not isinstance(scope_list, list):
            raise ValueError("Scopes must be a JSON array")
        
        # Validate each scope
        validated = []
        for scope in scope_list:
            if not isinstance(scope, str):
                raise ValueError(f"Scope must be a string: {scope}")
            if scope not in VALID_SCOPES:
                logger.warning(f"Unknown scope: {scope} (will be accepted but may not grant access)")
            validated.append(scope)
        
        return validated
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in scopes: {e}") from e


def format_scopes(scopes: List[str]) -> str:
    """
    Format scope list as JSON string for storage.
    
    Args:
        scopes: List of scope strings
        
    Returns:
        JSON string representation
    """
    if not scopes:
        return "[]"
    return json.dumps(sorted(set(scopes)))  # Deduplicate and sort for consistency

