import pandas as pd


def create_target(
    df: pd.DataFrame,
    forward_periods: int = 5,
    threshold: float = 0.005
) -> pd.DataFrame:
    """
    3-class directional label based on future returns.

    Classes:
        2  →  BUY   (price rises > threshold over next N candles)
        0  →  SELL  (price drops > threshold over next N candles)
        1  →  HOLD  (price stays within ±threshold)

    Args:
        df:              DataFrame with 'close' column
        forward_periods: How many candles ahead to measure return
        threshold:       Min move (0.005 = 0.5%) to qualify as BUY/SELL

    Returns:
        DataFrame with 'target' column appended (NaN rows dropped)
    """
    df = df.copy()

    future_close  = df["close"].shift(-forward_periods)
    future_return = (future_close / df["close"]) - 1

    df["target"] = 1  # default → HOLD
    df.loc[future_return >  threshold, "target"] = 2   # BUY
    df.loc[future_return < -threshold, "target"] = 0   # SELL

    # Drop rows where future price isn't available
    df = df.dropna(subset=["target"])
    df["target"] = df["target"].astype(int)

    class_counts = df["target"].value_counts().sort_index()
    print(f"[LABEL] Label distribution — SELL:{class_counts.get(0,0)}  "
          f"HOLD:{class_counts.get(1,0)}  BUY:{class_counts.get(2,0)}")

    return df
