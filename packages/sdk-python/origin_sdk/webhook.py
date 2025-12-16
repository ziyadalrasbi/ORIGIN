"""Webhook verification utilities for ORIGIN webhooks."""

import hashlib
import hmac
import time
from typing import Dict


def verify_webhook(
    headers: Dict[str, str],
    raw_body: bytes,
    secret: str,
    tolerance_seconds: int = 300,
) -> bool:
    """
    Verify ORIGIN webhook signature and timestamp.
    
    Args:
        headers: Request headers dictionary
        raw_body: Raw request body bytes
        secret: Webhook secret (decrypted)
        tolerance_seconds: Maximum age of timestamp in seconds (default: 300 = 5 minutes)
        
    Returns:
        True if webhook is valid, False otherwise
    """
    # Extract required headers
    signature_header = headers.get("X-Origin-Signature", "")
    timestamp_str = headers.get("X-Origin-Timestamp", "")
    
    if not signature_header or not timestamp_str:
        return False
    
    # Parse signature (format: "sha256=<hex>")
    if not signature_header.startswith("sha256="):
        return False
    
    expected_signature = signature_header[7:]  # Remove "sha256=" prefix
    
    # Validate timestamp
    try:
        timestamp = int(timestamp_str)
        current_time = int(time.time())
        age = abs(current_time - timestamp)
        
        if age > tolerance_seconds:
            return False  # Timestamp too old (replay attack)
    except (ValueError, TypeError):
        return False  # Invalid timestamp format
    
    # Reconstruct signed message: timestamp + "." + raw_body_bytes
    # Use raw bytes exactly as received (not re-encoded)
    if not isinstance(raw_body, bytes):
        raw_body = raw_body.encode("utf-8")
    
    message = timestamp_str.encode("utf-8") + b"." + raw_body
    
    # Compute expected signature
    computed_signature = hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    
    # Constant-time comparison
    return hmac.compare_digest(expected_signature, computed_signature)

