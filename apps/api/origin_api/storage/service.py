"""Object storage service for evidence pack artifacts.

Uses MinIO (S3-compatible) for secure, scalable artifact storage.
Returns object keys instead of filesystem paths to prevent path traversal attacks.
"""

import logging
from io import BytesIO
from typing import Optional

from minio import Minio
from minio.error import S3Error

from origin_api.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class StorageService:
    """Object storage service for evidence pack artifacts."""

    def __init__(self):
        """Initialize storage service with MinIO client."""
        self.bucket = settings.minio_bucket
        try:
            self.client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_use_ssl,
            )
            # Ensure bucket exists
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"Created bucket: {self.bucket}")
        except Exception as e:
            logger.error(f"Failed to initialize MinIO client: {e}")
            self.client = None

    def put_object(
        self, object_key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        """
        Upload object to storage.
        
        Args:
            object_key: Object key (e.g., "evidence/{certificate_id}/{format}/artifact.json")
            data: Object data as bytes
            content_type: MIME type
        
        Returns:
            Object key (for consistency)
        
        Raises:
            ValueError: If storage client is not available
        """
        if not self.client:
            raise ValueError("Storage client not available")
        
        try:
            data_stream = BytesIO(data)
            self.client.put_object(
                self.bucket,
                object_key,
                data_stream,
                length=len(data),
                content_type=content_type,
            )
            logger.debug(f"Uploaded object: {object_key} ({len(data)} bytes)")
            return object_key
        except S3Error as e:
            logger.error(f"Failed to upload object {object_key}: {e}")
            raise

    def get_object(self, object_key: str) -> bytes:
        """
        Retrieve object from storage.
        
        Args:
            object_key: Object key
        
        Returns:
            Object data as bytes
        
        Raises:
            ValueError: If storage client is not available
            FileNotFoundError: If object does not exist
        """
        if not self.client:
            raise ValueError("Storage client not available")
        
        try:
            response = self.client.get_object(self.bucket, object_key)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            if e.code == "NoSuchKey":
                raise FileNotFoundError(f"Object not found: {object_key}")
            logger.error(f"Failed to retrieve object {object_key}: {e}")
            raise

    def generate_signed_url(
        self, object_key: str, expires_in_seconds: int = 3600
    ) -> Optional[str]:
        """
        Generate presigned URL for object access.
        
        Args:
            object_key: Object key
            expires_in_seconds: URL expiration time
        
        Returns:
            Presigned URL or None if client unavailable
        """
        if not self.client:
            return None
        
        try:
            from datetime import timedelta
            url = self.client.presigned_get_object(
                self.bucket,
                object_key,
                expires=timedelta(seconds=expires_in_seconds),
            )
            return url
        except Exception as e:
            logger.error(f"Failed to generate signed URL for {object_key}: {e}")
            return None

    def object_exists(self, object_key: str) -> bool:
        """Check if object exists in storage."""
        if not self.client:
            return False
        
        try:
            self.client.stat_object(self.bucket, object_key)
            return True
        except S3Error:
            return False

    @staticmethod
    def build_object_key(certificate_id: str, audience: str, format: str) -> str:
        """
        Build object key for evidence pack artifact.
        
        Format: evidence/{certificate_id}/{audience}/{format}
        
        Args:
            certificate_id: Certificate UUID
            audience: Audience (INTERNAL, DSP, REGULATOR)
            format: Format (json, pdf, html)
        
        Returns:
            Object key (safe, no path traversal possible)
        """
        # Validate format to prevent injection
        allowed_formats = {"json", "pdf", "html"}
        if format not in allowed_formats:
            raise ValueError(f"Invalid format: {format}. Allowed: {allowed_formats}")
        
        # Validate audience
        allowed_audiences = {"INTERNAL", "DSP", "REGULATOR"}
        if audience not in allowed_audiences:
            raise ValueError(f"Invalid audience: {audience}. Allowed: {allowed_audiences}")
        
        # Build key - certificate_id is UUID, so safe
        return f"evidence/{certificate_id}/{audience}/{format}"


# Global instance
_storage_service: Optional[StorageService] = None


def get_storage_service() -> StorageService:
    """Get or create storage service instance."""
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service

