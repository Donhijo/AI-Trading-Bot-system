import pandas as pd
from binance.client import Client
from config import BINANCE_API_KEY, BINANCE_SECRET_KEY, SYMBOL, TIMEFRAME, LIMIT
import logging

logger = logging.getLogger("bot")

# Lazy client initialization
_client = None

def _get_client():
    """Get or create the Binance client (lazy initialization)."""
    global _client
    if _client is None:
        try:
            _client = Client(
                BINANCE_API_KEY,
                BINANCE_SECRET_KEY,
                requests_params={'timeout': 30}  # Increase timeout to 30 seconds
            )
        except Exception as e:
            logger.error(f"Failed to create Binance client: {e}")
            raise
    return _client

_COLUMNS = [
    "timestamp", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore"
]

def get_historical_data(
    symbol: str = SYMBOL,
    timeframe: str = TIMEFRAME,
    limit: int = LIMIT
) -> pd.DataFrame:
    """Fetch OHLCV candles from Binance REST API."""
    try:
        client = _get_client()
        klines = client.get_klines(symbol=symbol, interval=timeframe, limit=limit)

        df = pd.DataFrame(klines, columns=_COLUMNS)
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        return df
    except Exception as e:
        logger.warning(f"Failed to fetch historical data: {e}. Using sample data.")
        # Generate sample data for testing
        import numpy as np
        timestamps = pd.date_range(end=pd.Timestamp.now(), periods=limit, freq='15min')
        sample_data = {
            "open": np.random.rand(limit) * 50000 + 30000,
            "high": np.random.rand(limit) * 50000 + 30000,
            "low": np.random.rand(limit) * 50000 + 30000,
            "close": np.random.rand(limit) * 50000 + 30000,
            "volume": np.random.rand(limit) * 100 + 10
        }
        df = pd.DataFrame(sample_data, index=timestamps)
        return df
