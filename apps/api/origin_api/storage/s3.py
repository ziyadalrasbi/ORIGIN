"""S3/MinIO storage client for evidence packs."""

import hashlib
from datetime import timedelta
from typing import Optional

from minio import Minio
from minio.error import S3Error

from origin_api.settings import get_settings

settings = get_settings()


class S3Storage:
    """S3-compatible storage client."""

    def __init__(self):
        """Initialize storage client."""
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_use_ssl,
        )
        self.bucket = settings.minio_bucket
        self._ensure_bucket()

    def _ensure_bucket(self):
        """Ensure bucket exists."""
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except S3Error as e:
            print(f"Error ensuring bucket exists: {e}")

    def upload_object(
        self, object_key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> dict:
        """Upload object to storage."""
        from io import BytesIO

        data_stream = BytesIO(data)
        data_size = len(data)

        # Compute hash
        sha256_hash = hashlib.sha256(data).hexdigest()

        # Upload
        self.client.put_object(
            self.bucket,
            object_key,
            data_stream,
            data_size,
            content_type=content_type,
        )

        return {
            "key": object_key,
            "size": data_size,
            "hash": f"sha256:{sha256_hash}",
        }

    def get_signed_url(self, object_key: str, expires_in: int = 3600) -> str:
        """Generate presigned URL for object."""
        try:
            url = self.client.presigned_get_object(
                self.bucket,
                object_key,
                expires=timedelta(seconds=expires_in),
            )
            return url
        except S3Error as e:
            print(f"Error generating signed URL: {e}")
            raise

    def get_object(self, object_key: str) -> bytes:
        """Download object from storage."""
        try:
            response = self.client.get_object(self.bucket, object_key)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            print(f"Error getting object: {e}")
            raise

