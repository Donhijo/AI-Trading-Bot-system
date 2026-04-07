import logging
from live.broker import place_order, get_account_balance, get_ticker_price
from live.risk import calculate_position_size, calculate_sl_tp, is_drawdown_safe, get_drawdown
from live.monitor import send_alert, log_error
from config import SYMBOL, SL_PCT, TP_RATIO, INITIAL_BALANCE

logger = logging.getLogger("bot")


def execute_signal(
    signal: str,
    symbol: str = SYMBOL,
    initial_balance: float = INITIAL_BALANCE
) -> dict | None:
    """
    Full execution pipeline:
        1. Skip HOLD signals
        2. Check max drawdown safety
        3. Size position with fixed-fractional risk
        4. Place market order
        5. Return order dict or None

    Returns: Binance order dict on success, None if skipped/failed
    """
    if signal == "HOLD":
        return None

    # ── Safety checks ──────────────────────────────────────────────────────────
    balance = get_account_balance("USDT")
    dd = get_drawdown(balance, initial_balance)

    if not is_drawdown_safe(balance, initial_balance):
        msg = f"⛔ Max drawdown reached ({dd:.1%}) — skipping trade"
        logger.warning(msg)
        send_alert(msg)
        return None

    # ── Sizing ─────────────────────────────────────────────────────────────────
    price   = get_ticker_price(symbol)
    sl, tp  = calculate_sl_tp(price, signal, SL_PCT, TP_RATIO)
    qty     = calculate_position_size(balance, price, sl)

    if qty <= 0:
        logger.warning(f"⚠️ Position size too small ({qty}) — skipping")
        return None

    # ── Execution ──────────────────────────────────────────────────────────────
    side = "BUY" if signal == "BUY" else "SELL"
    try:
        order = place_order(symbol, side, qty)
        msg = (
            f"✅ <b>{side}</b> {qty} {symbol} @ ~{price:.2f}\n"
            f"   SL: {sl:.2f} | TP: {tp:.2f} | DD: {dd:.1%}"
        )
        logger.info(msg.replace("<b>", "").replace("</b>", ""))
        send_alert(msg)
        return order

    except Exception as e:
        log_error("execute_signal", e)
        return None
