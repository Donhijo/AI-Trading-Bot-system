import pandas as pd


def rule_based_strategy(df: pd.DataFrame) -> str:
    """
    Classic rule-based strategy combining RSI, MACD crossover, and EMA trend filter.

    Signal logic:
        BUY  → RSI oversold + MACD crosses up + price above EMA
        SELL → RSI overbought + MACD crosses down + price below EMA
        HOLD → everything else

    Args:
        df: DataFrame with columns: rsi, macd, macd_signal, ema, close

    Returns:
        'BUY' | 'SELL' | 'HOLD'
    """
    if len(df) < 2:
        return "HOLD"

    row  = df.iloc[-1]
    prev = df.iloc[-2]

    rsi       = row.get("rsi", 50)
    macd      = row.get("macd", 0)
    prev_macd = prev.get("macd", 0)
    ema       = row.get("ema", row["close"])
    close     = row["close"]

    macd_crossed_up   = (macd > 0) and (prev_macd <= 0)
    macd_crossed_down = (macd < 0) and (prev_macd >= 0)

    if rsi < 35 and macd_crossed_up and close > ema:
        return "BUY"

    if rsi > 65 and macd_crossed_down and close < ema:
        return "SELL"

    return "HOLD"


def hybrid_strategy(df: pd.DataFrame, ai_signal: str, weight_ai: float = 0.7) -> str:
    """
    Combines AI signal and rule-based signal via weighted voting.
    Both must agree directionally for a trade to execute.

    Args:
        df:         Feature DataFrame
        ai_signal:  'BUY' | 'SELL' | 'HOLD' from the model
        weight_ai:  Weight given to AI signal (rest goes to rule-based)

    Returns:
        Final signal string
    """
    rule_signal = rule_based_strategy(df)

    if ai_signal == rule_signal:
        return ai_signal  # Strong agreement

    # If AI says trade but rules say HOLD (or vice versa), stay out
    return "HOLD"
