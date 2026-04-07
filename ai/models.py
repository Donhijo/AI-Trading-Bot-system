import os
import joblib
import xgboost as xgb
import pandas as pd
from config import MODEL_PATH, FEATURES


def train_model(df: pd.DataFrame) -> xgb.XGBClassifier:
    """Train XGBoost classifier and save to disk."""
    X = df[FEATURES]
    y = df["target"]

    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        use_label_encoder=False,
        eval_metric="mlogloss",
        random_state=42
    )
    model.fit(X, y)

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    print(f"✅ Model saved → {MODEL_PATH}")
    return model


def load_model() -> xgb.XGBClassifier:
    """Load saved model from disk."""
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(
            f"No model found at '{MODEL_PATH}'. Run train.py first."
        )
    return joblib.load(MODEL_PATH)


def predict(model: xgb.XGBClassifier, features: pd.DataFrame) -> int:
    """Return raw int class prediction (0=SELL, 1=HOLD, 2=BUY)."""
    return int(model.predict(features)[0])


def predict_proba(model: xgb.XGBClassifier, features: pd.DataFrame) -> dict:
    """Return confidence scores for all classes."""
    proba = model.predict_proba(features)[0]
    return {"SELL": proba[0], "HOLD": proba[1], "BUY": proba[2]}
