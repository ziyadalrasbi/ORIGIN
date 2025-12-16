"""Feature engineering for ML models."""

import pandas as pd
from sklearn.preprocessing import LabelEncoder


def prepare_features(df: pd.DataFrame):
    """Prepare features and labels for training."""
    # Feature columns
    feature_cols = [
        "account_age_days",
        "shared_device_count",
        "prior_quarantine_count",
        "identity_confidence",
        "upload_velocity",
        "prior_sightings_count",
    ]

    # Extract features
    X = df[feature_cols].copy()

    # Encode labels
    label_encoder = LabelEncoder()
    y = label_encoder.fit_transform(df["label"])

    return X, y

