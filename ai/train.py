"""
train.py — Run this once to train and save the AI model.

Usage:
    python train.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.data_loader import get_historical_data
from ai.features import create_features
from ai.labels import create_target
from ai.models import train_model
from config import LIMIT


def train():
    print("📥 Fetching historical data...")
    df = get_historical_data(limit=LIMIT)

    print("⚙️  Engineering features...")
    df = create_features(df)

    print("🏷️  Creating target labels...")
    df = create_target(df)

    print("🧠 Training XGBoost model...")
    train_model(df)
    print("✅ Training complete!")


if __name__ == "__main__":
    train()
