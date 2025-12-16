"""Train risk scoring model."""

import joblib
import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

from ml.training.feature_engineering import prepare_features


def train_risk_model(dataset_path: str = "ml/datasets/synthetic/synthetic_dataset.parquet"):
    """Train XGBoost risk model."""
    # Load data
    df = pd.read_parquet(dataset_path)

    # Prepare features
    X, y = prepare_features(df)

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

        # Save model
        model_path = "ml/models/risk_model.pkl"
        joblib.dump(calibrated_model, model_path)
        mlflow.log_artifact(model_path)

        print(f"Model trained - Train: {train_score:.3f}, Test: {test_score:.3f}")
        print(f"Model saved to: {model_path}")

    return calibrated_model


def train_anomaly_model(dataset_path: str = "ml/datasets/synthetic/synthetic_dataset.parquet"):
    """Train anomaly detection model."""
    df = pd.read_parquet(dataset_path)

    # Prepare features (use same features as risk model)
    X, _ = prepare_features(df)

    # Train Isolation Forest
    model = IsolationForest(contamination=0.1, random_state=42)
    model.fit(X)

    # Save model
    model_path = "ml/models/anomaly_model.pkl"
    joblib.dump(model, model_path)

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

