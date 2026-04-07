import pandas as pd
from ai.models import load_model, predict, predict_proba

# Lazy-load model once on first call
_model = None

def _get_model():
    global _model
    if _model is None:
        _model = load_model()
    return _model


_SIGNAL_MAP = {0: "SELL", 1: "HOLD", 2: "BUY"}


def predict_signal(features: pd.DataFrame) -> str:
    """
    Given a 1-row feature DataFrame, return 'BUY', 'SELL', or 'HOLD'.
    """
    model = _get_model()
    raw = predict(model, features)
    return _SIGNAL_MAP.get(raw, "HOLD")


def predict_signal_with_confidence(features: pd.DataFrame) -> tuple[str, float]:
    """
    Returns (signal, confidence) — confidence is the winning class probability.
    """
    model = _get_model()
    raw    = predict(model, features)
    signal = _SIGNAL_MAP.get(raw, "HOLD")
    proba  = predict_proba(model, features)
    return signal, proba[signal]


def reload_model():
    """Force reload the model from disk (e.g. after retraining)."""
    global _model
    _model = load_model()
    print("🔄 Model reloaded.")
