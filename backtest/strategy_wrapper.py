import pandas as pd
from ai.features import create_features
from ai.predict import predict_signal
from config import FEATURES


def ai_strategy(df: pd.DataFrame) -> str:
    """
    AI model strategy — used as the strategy_func argument for Backtester.run().
    Wraps the model prediction into the backtester's expected interface.
    """
    df = create_features(df.copy())

    if len(df) < 10:
        return "HOLD"

    latest = df[FEATURES].tail(1)
    return predict_signal(latest)
