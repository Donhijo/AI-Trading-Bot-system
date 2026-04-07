import pandas as pd
import ta


def create_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add technical indicators and return-based features.
    Unified entry point used by train.py, strategy_wrapper, and bot loop.
    """
    df = df.copy()

    # ── Momentum ───────────────────────────────────────────────────────────────
    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()

    # ── Trend ──────────────────────────────────────────────────────────────────
    macd_obj = ta.trend.MACD(df["close"])
    df["macd"]        = macd_obj.macd()
    df["macd_signal"] = macd_obj.macd_signal()
    df["macd_diff"]   = macd_obj.macd_diff()

    df["ema"]  = ta.trend.EMAIndicator(df["close"], window=20).ema_indicator()
    df["ema50"] = ta.trend.EMAIndicator(df["close"], window=50).ema_indicator()

    # ── Volatility ─────────────────────────────────────────────────────────────
    bb = ta.volatility.BollingerBands(df["close"])
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["close"]

    # ── Price Returns ──────────────────────────────────────────────────────────
    df["returns"]  = df["close"].pct_change()
    df["returns_5"] = df["close"].pct_change(5)

    # ── Volume ─────────────────────────────────────────────────────────────────
    df["volume_ma"] = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_ma"]

    return df.dropna()


# Backward-compatible alias (features.py original name)
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    return create_features(df)
