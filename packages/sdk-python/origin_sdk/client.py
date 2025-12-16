"""ORIGIN API client."""

import requests
from typing import Optional


class OriginClient:
    """Client for ORIGIN API."""

    def __init__(self, api_key: str, base_url: str = "http://localhost:8000"):
        """Initialize client."""
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"x-api-key": api_key})

    def ingest(
        self,
        account_external_id: str,
        upload_external_id: str,
        account_type: str = "user",
        display_name: Optional[str] = None,
        metadata: Optional[dict] = None,
        content_ref: Optional[str] = None,
        fingerprints: Optional[dict] = None,
        device_context: Optional[dict] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """Submit content for ingestion."""
        url = f"{self.base_url}/v1/ingest"
        headers = {}
        if idempotency_key:
            headers["idempotency-key"] = idempotency_key

        payload = {
            "account_external_id": account_external_id,
            "account_type": account_type,
            "upload_external_id": upload_external_id,
            "metadata": metadata or {},
            "content_ref": content_ref,
            "fingerprints": fingerprints,
            "device_context": device_context,
        }
        if display_name:
            payload["display_name"] = display_name

        response = self.session.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()

    def request_evidence_pack(
        self,
        certificate_id: str,
        format: str = "json",
        audience: str = "INTERNAL",
    ) -> dict:
        """Request evidence pack generation."""
        url = f"{self.base_url}/v1/evidence-packs"
        payload = {
            "certificate_id": certificate_id,
            "format": format,
            "audience": audience,
        }
        response = self.session.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def get_evidence_pack(self, certificate_id: str) -> dict:
        """Get evidence pack status and URLs."""
        url = f"{self.base_url}/v1/evidence-packs/{certificate_id}"
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()

    def download_evidence_pack(
        self, certificate_id: str, format: str = "json"
    ) -> bytes:
        """Download evidence pack artifact."""
        url = f"{self.base_url}/v1/evidence-packs/{certificate_id}/download/{format}"
        response = self.session.get(url)
        response.raise_for_status()
        return response.content

