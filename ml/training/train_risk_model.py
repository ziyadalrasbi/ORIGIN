"""Train risk scoring model."""

import joblib
import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier

from ml.training.feature_engineering import prepare_features


def train_risk_model(dataset_path: str = "ml/datasets/synthetic/synthetic_dataset.parquet"):
    """Train XGBoost risk model."""
    # Load data
    df = pd.read_parquet(dataset_path)

    # Prepare features and encode labels
    feature_cols = [
        "account_age_days",
        "shared_device_count",
        "prior_quarantine_count",
        "identity_confidence",
        "upload_velocity",
        "prior_sightings_count",
    ]
    X = df[feature_cols].copy()

    # Encode labels with LabelEncoder
    label_encoder = LabelEncoder()
    y = label_encoder.fit_transform(df["label"])

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Start MLflow run
    mlflow.set_experiment("risk_model")
    with mlflow.start_run():
        # Train XGBoost model
        model = XGBClassifier(
            n_estimators=100,
            max_depth=6,
            learning_rate=0.1,
            random_state=42,
            eval_metric="logloss",
        )

        # Calibrate for probability estimates
        calibrated_model = CalibratedClassifierCV(model, method="isotonic", cv=3)
        calibrated_model.fit(X_train, y_train)

        # Evaluate
        train_score = calibrated_model.score(X_train, y_train)
        test_score = calibrated_model.score(X_test, y_test)

        # Log metrics
        mlflow.log_metric("train_accuracy", train_score)
        mlflow.log_metric("test_accuracy", test_score)

        # Log model
        mlflow.sklearn.log_model(calibrated_model, "model")

        # Save model and label encoder together
        model_path = "ml/models/risk_model.pkl"
        artifact = {
            "model": calibrated_model,
            "label_encoder": label_encoder,
        }
        joblib.dump(artifact, model_path)
        mlflow.log_artifact(model_path)

        print(f"Model trained - Train: {train_score:.3f}, Test: {test_score:.3f}")
        print(f"Model saved to: {model_path}")
        print(f"Label classes: {label_encoder.classes_}")

    return calibrated_model


def train_anomaly_model(dataset_path: str = "ml/datasets/synthetic/synthetic_dataset.parquet"):
    """Train anomaly detection model on normal (ALLOW) data only."""
    df = pd.read_parquet(dataset_path)

    # Filter to only "ALLOW" label for normal behavior baseline
    normal_df = df[df["label"] == "ALLOW"].copy()
    
    if len(normal_df) == 0:
        raise ValueError("No ALLOW samples found in dataset. Cannot train anomaly model.")

    # Prepare features (use same features as risk model)
    feature_cols = [
        "account_age_days",
        "shared_device_count",
        "prior_quarantine_count",
        "identity_confidence",
        "upload_velocity",
        "prior_sightings_count",
    ]
    X_normal = normal_df[feature_cols].copy()

    # Train Isolation Forest on normal data only
    model = IsolationForest(
        n_estimators=200,
        contamination=0.05,
        random_state=42,
    )
    model.fit(X_normal)

    # Save model
    model_path = "ml/models/anomaly_model.pkl"
    joblib.dump(model, model_path)

    print(f"Anomaly model trained on {len(normal_df)} ALLOW samples")
    print(f"Anomaly model saved to: {model_path}")
    return model


if __name__ == "__main__":
    import sys
    from pathlib import Path

    # Add project root to path
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    # Train models
    train_risk_model()
    train_anomaly_model()

