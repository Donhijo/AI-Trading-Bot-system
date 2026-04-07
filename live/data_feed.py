import threading
import logging
import pandas as pd
from binance import ThreadedWebsocketManager
from config import BINANCE_API_KEY, BINANCE_SECRET_KEY, SYMBOL, TIMEFRAME

logger = logging.getLogger("bot")

_live_df: pd.DataFrame = pd.DataFrame(
    columns=["open", "high", "low", "close", "volume"]
)
_lock = threading.Lock()
_twm: ThreadedWebsocketManager | None = None


def _handle_kline(msg: dict):
    """WebSocket callback — appends closed candles to the live DataFrame."""
    global _live_df

    if msg.get("e") == "error":
        logger.error(f"WebSocket error: {msg}")
        return

    kline = msg["k"]
    if not kline["x"]:  # Only process fully closed candles
        return

    ts = pd.to_datetime(kline["t"], unit="ms")
    row = {
        "open":   float(kline["o"]),
        "high":   float(kline["h"]),
        "low":    float(kline["l"]),
        "close":  float(kline["c"]),
        "volume": float(kline["v"]),
    }

    with _lock:
        _live_df.loc[ts] = row
        # Keep rolling 500-candle window in memory
        if len(_live_df) > 500:
            _live_df = _live_df.iloc[-500:]

    logger.debug(f"📊 New candle: {ts} close={row['close']}")


def start_feed(symbol: str = SYMBOL, timeframe: str = TIMEFRAME):
    """Start the WebSocket kline stream in a background thread."""
    global _twm
    try:
        _twm = ThreadedWebsocketManager(
            api_key=BINANCE_API_KEY,
            api_secret=BINANCE_SECRET_KEY
        )
        _twm.start()  # Start the WebSocket manager
        _twm.start_kline_socket(
            callback=_handle_kline,
            symbol=symbol,
            interval=timeframe
        )
        logger.info(f"📡 Live feed started → {symbol} {timeframe}")
    except Exception as e:
        logger.error(f"Failed to start WebSocket feed: {e}")
        # Continue without live feed - use historical data only
        logger.info(" Continuing with historical data only...")
        _twm = None


def stop_feed():
    """Gracefully stop the WebSocket feed."""
    global _twm
    if _twm:
        _twm.stop()
        logger.info("📡 Live feed stopped.")
    else:
        logger.info("📡 Live feed was not running.")


def get_live_df() -> pd.DataFrame:
    """Return a thread-safe copy of the live candle DataFrame."""
    global _twm
    if _twm is None:
        # Return empty DataFrame if WebSocket is not available
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    with _lock:
        return _live_df.copy()
