from config import RISK_PER_TRADE, SL_PCT, TP_RATIO, MAX_DRAWDOWN_PCT, INITIAL_BALANCE


def calculate_position_size(
    balance: float,
    entry_price: float,
    sl_price: float
) -> float:
    """
    Fixed-fractional position sizing.
    Risks exactly RISK_PER_TRADE % of balance per trade.

    Returns: quantity in base asset (e.g. BTC)
    """
    risk_amount = balance * RISK_PER_TRADE
    price_risk  = abs(entry_price - sl_price)

    if price_risk == 0:
        return 0.0

    size = risk_amount / price_risk
    return round(size, 6)


def calculate_sl_tp(
    entry_price: float,
    signal: str,
    sl_pct: float = SL_PCT,
    tp_ratio: float = TP_RATIO
) -> tuple[float, float]:
    """
    Calculate stop-loss and take-profit prices.

    Returns: (sl_price, tp_price)
    """
    if signal == "BUY":
        sl = entry_price * (1 - sl_pct)
        tp = entry_price * (1 + sl_pct * tp_ratio)
    elif signal == "SELL":
        sl = entry_price * (1 + sl_pct)
        tp = entry_price * (1 - sl_pct * tp_ratio)
    else:
        sl = tp = entry_price

    return round(sl, 6), round(tp, 6)


def is_drawdown_safe(
    balance: float,
    initial_balance: float = INITIAL_BALANCE,
    max_drawdown_pct: float = MAX_DRAWDOWN_PCT
) -> bool:
    """Returns False if account has exceeded the max drawdown threshold."""
    if initial_balance <= 0:
        return True
    drawdown = (initial_balance - balance) / initial_balance
    return drawdown < max_drawdown_pct


def get_drawdown(balance: float, initial_balance: float = INITIAL_BALANCE) -> float:
    """Returns current drawdown as a float (0.05 = 5%)."""
    return max(0.0, (initial_balance - balance) / initial_balance)
