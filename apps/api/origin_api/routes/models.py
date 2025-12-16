"""ML model status and lifecycle endpoints."""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from origin_api.db.session import get_db
from origin_api.models import PolicyProfile
from origin_api.models.tenant import Tenant
from origin_api.settings import get_settings

router = APIRouter(prefix="/v1", tags=["models"])
logger = logging.getLogger(__name__)
settings = get_settings()


class ModelStatus(BaseModel):
    """Model status response."""

    model_type: str  # "risk" or "anomaly"
    version: str
    file_hash: Optional[str] = None  # SHA-256 hash of model file
    loaded_at: Optional[datetime] = None
    file_path: Optional[str] = None


class ModelsStatusResponse(BaseModel):
    """Models status response."""

    risk_model: Optional[ModelStatus] = None
    anomaly_model: Optional[ModelStatus] = None
    policy_profiles: list[dict] = []  # Policy profiles referencing model versions


@router.get("/models/status")
async def get_models_status(
    request: Request,
    db: Session = Depends(get_db),
):
    """Get ML model status and versions."""
    tenant: Tenant = request.state.tenant
    
    from origin_api.ml.inference import get_inference_service
    inference_service = get_inference_service()
    
    # Get model status from inference service
    risk_model_status = None
    anomaly_model_status = None
    
    if inference_service.risk_model:
        risk_model_path = inference_service.model_dir / "risk_model.pkl"
        if risk_model_path.exists():
            # Compute file hash
            with open(risk_model_path, "rb") as f:
                model_bytes = f.read()
                file_hash = hashlib.sha256(model_bytes).hexdigest()
            
            # Get version from metadata if available
            version = "unknown"
            metadata_path = inference_service.model_dir / "risk_model_metadata.json"
            if metadata_path.exists():
                try:
                    with open(metadata_path, "r") as f:
                        metadata = json.load(f)
                        version = metadata.get("version", "unknown")
                except Exception:
                    pass
            
            risk_model_status = ModelStatus(
                model_type="risk",
                version=version,
                file_hash=f"sha256:{file_hash}",
                loaded_at=inference_service.risk_model_loaded_at if hasattr(inference_service, "risk_model_loaded_at") else None,
                file_path=str(risk_model_path),
            )
    
    if inference_service.anomaly_model:
        anomaly_model_path = inference_service.model_dir / "anomaly_model.pkl"
        if anomaly_model_path.exists():
            # Compute file hash
            with open(anomaly_model_path, "rb") as f:
                model_bytes = f.read()
                file_hash = hashlib.sha256(model_bytes).hexdigest()
            
            # Get version from metadata if available
            version = "unknown"
            metadata_path = inference_service.model_dir / "anomaly_model_metadata.json"
            if metadata_path.exists():
                try:
                    with open(metadata_path, "r") as f:
                        metadata = json.load(f)
                        version = metadata.get("version", "unknown")
                except Exception:
                    pass
            
            anomaly_model_status = ModelStatus(
                model_type="anomaly",
                version=version,
                file_hash=f"sha256:{file_hash}",
                loaded_at=inference_service.anomaly_model_loaded_at if hasattr(inference_service, "anomaly_model_loaded_at") else None,
                file_path=str(anomaly_model_path),
            )
    
    # Get policy profiles referencing model versions
    policy_profiles = (
        db.query(PolicyProfile)
        .filter(PolicyProfile.tenant_id == tenant.id, PolicyProfile.is_active == True)  # noqa: E712
        .all()
    )
    
    profile_data = []
    for profile in policy_profiles:
        profile_data.append({
            "id": profile.id,
            "name": profile.name,
            "version": profile.version,
            "risk_model_version": getattr(profile, "risk_model_version", None),
            "anomaly_model_version": getattr(profile, "anomaly_model_version", None),
        })
    
    return ModelsStatusResponse(
        risk_model=risk_model_status,
        anomaly_model=anomaly_model_status,
        policy_profiles=profile_data,
    )

