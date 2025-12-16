"""Reproducible ML training pipeline.

This pipeline:
1. Loads data
2. Engineers features
3. Trains models
4. Evaluates performance
5. Exports signed artifact metadata
"""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

from ml.training.train_risk_model import train_risk_model, train_anomaly_model

logger = logging.getLogger(__name__)


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def export_model_metadata(
    model_type: str,
    model_path: Path,
    version: str,
    trained_at: datetime,
    metadata: dict,
) -> dict:
    """Export signed model metadata JSON."""
    # Compute file hash
    file_hash = compute_file_hash(model_path)
    
    metadata_dict = {
        "model_type": model_type,
        "version": version,
        "file_path": str(model_path),
        "file_hash": f"sha256:{file_hash}",
        "trained_at": trained_at.isoformat(),
        "metadata": metadata,
    }
    
    # Save metadata JSON
    metadata_path = model_path.parent / f"{model_type}_model_metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata_dict, f, indent=2)
    
    logger.info(f"Exported {model_type} model metadata to {metadata_path}")
    return metadata_dict


def run_training_pipeline(
    dataset_path: str = "ml/datasets/synthetic/synthetic_dataset.parquet",
    version: str = None,
):
    """Run complete training pipeline."""
    if version is None:
        version = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    
    logger.info(f"Starting training pipeline (version: {version})")
    
    # Train risk model
    logger.info("Training risk model...")
    risk_model = train_risk_model(dataset_path)
    risk_model_path = Path("ml/models/risk_model.pkl")
    
    # Export risk model metadata
    export_model_metadata(
        model_type="risk",
        model_path=risk_model_path,
        version=version,
        trained_at=datetime.utcnow(),
        metadata={
            "algorithm": "XGBoost",
            "calibration": "isotonic",
        },
    )
    
    # Train anomaly model
    logger.info("Training anomaly model...")
    anomaly_model = train_anomaly_model(dataset_path)
    anomaly_model_path = Path("ml/models/anomaly_model.pkl")
    
    # Export anomaly model metadata
    export_model_metadata(
        model_type="anomaly",
        model_path=anomaly_model_path,
        version=version,
        trained_at=datetime.utcnow(),
        metadata={
            "algorithm": "IsolationForest",
            "contamination": 0.1,
        },
    )
    
    logger.info("Training pipeline completed successfully")
    return {
        "version": version,
        "risk_model": str(risk_model_path),
        "anomaly_model": str(anomaly_model_path),
    }


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    dataset_path = sys.argv[1] if len(sys.argv) > 1 else "ml/datasets/synthetic/synthetic_dataset.parquet"
    version = sys.argv[2] if len(sys.argv) > 2 else None
    
    run_training_pipeline(dataset_path, version)

