"""Synthetic dataset generator for ML training."""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

# Set seed for reproducibility
random.seed(42)


def generate_synthetic_dataset(n_samples: int = 1000, output_path: str = "synthetic_dataset.parquet"):
    """Generate synthetic dataset with realistic distributions."""
    data = []

    # Account types and their risk profiles
    account_profiles = {
        "normal_user": {"risk_base": 10, "assurance_base": 85, "clean_ratio": 0.95},
        "spam_creator": {"risk_base": 80, "assurance_base": 20, "clean_ratio": 0.05},
        "identity_hopper": {"risk_base": 60, "assurance_base": 30, "clean_ratio": 0.3},
        "new_user": {"risk_base": 40, "assurance_base": 50, "clean_ratio": 0.7},
    }

    for i in range(n_samples):
        # Select account profile
        profile_name = random.choices(
            list(account_profiles.keys()),
            weights=[0.7, 0.1, 0.1, 0.1],  # More normal users
        )[0]
        profile = account_profiles[profile_name]

        # Generate features
        account_age_days = random.randint(0, 365 * 2)
        shared_device_count = random.randint(0, 5) if profile_name != "identity_hopper" else random.randint(5, 20)
        prior_quarantine_count = random.randint(0, 3) if profile_name == "spam_creator" else 0
        upload_velocity = random.randint(1, 100)  # uploads per day
        prior_sightings_count = random.randint(0, 10) if profile_name == "spam_creator" else 0

        # Identity confidence
        identity_confidence = max(
            0,
            min(
                100,
                50
                + (shared_device_count * 5)
                + (account_age_days // 30 * 2)
                - (prior_quarantine_count * 20)
                - (random.randint(0, 30) if profile_name == "identity_hopper" else 0),
            ),
        )

        # Risk score (with noise)
        risk_score = profile["risk_base"] + random.randint(-20, 20)
        risk_score = max(0, min(100, risk_score))
        risk_score += prior_quarantine_count * 15
        risk_score += prior_sightings_count * 5
        risk_score += (100 - identity_confidence) * 0.3

        # Assurance score
        assurance_score = profile["assurance_base"] + random.randint(-15, 15)
        assurance_score = max(0, min(100, assurance_score))
        assurance_score += identity_confidence * 0.4
        assurance_score -= prior_quarantine_count * 20

        # Anomaly score (higher for unusual patterns)
        anomaly_score = random.uniform(0, 100)
        if profile_name == "identity_hopper":
            anomaly_score += 30
        if upload_velocity > 50:
            anomaly_score += 20
        anomaly_score = min(100, anomaly_score)

        # Synthetic/AI likelihood (placeholder)
        synthetic_likelihood = random.uniform(0, 100)
        if profile_name == "spam_creator":
            synthetic_likelihood += 30

        # Generate label based on profile and scores
        is_clean = random.random() < profile["clean_ratio"]
        if risk_score > 70 or prior_quarantine_count > 0:
            label = "QUARANTINE"
        elif risk_score > 40 or identity_confidence < 30:
            label = "REVIEW"
        elif is_clean and assurance_score > 70:
            label = "ALLOW"
        else:
            label = "REVIEW"

        # Create feature row
        row = {
            "account_age_days": account_age_days,
            "shared_device_count": shared_device_count,
            "prior_quarantine_count": prior_quarantine_count,
            "identity_confidence": identity_confidence,
            "upload_velocity": upload_velocity,
            "prior_sightings_count": prior_sightings_count,
            "risk_score": risk_score,
            "assurance_score": assurance_score,
            "anomaly_score": anomaly_score,
            "synthetic_likelihood": synthetic_likelihood,
            "label": label,
            "account_type": profile_name,
        }

        data.append(row)

    # Create DataFrame
    df = pd.DataFrame(data)

    # Save to parquet
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)

    print(f"Generated {len(df)} synthetic samples")
    print(f"Label distribution:")
    print(df["label"].value_counts())
    print(f"\nSaved to: {output_path}")

    return df


if __name__ == "__main__":
    # Generate dataset
    dataset_path = "ml/datasets/synthetic/synthetic_dataset.parquet"
    generate_synthetic_dataset(n_samples=5000, output_path=dataset_path)

