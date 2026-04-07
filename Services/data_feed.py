"""
Services/data_feed.py - Market data feed service.

Provides unified access to historical and real-time market data
from multiple sources with caching and error handling.
"""
import logging
import threading
import time
from typing import Optional, Callable, List, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass

import pandas as pd
from binance import ThreadedWebsocketManager

from config import BINANCE_API_KEY, BINANCE_SECRET_KEY, SYMBOL, TIMEFRAME
from Services.broker import get_broker, BinanceBroker

logger = logging.getLogger("bot.data_feed")


@dataclass
class Candle:
    """Represents a single candlestick."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "is_closed": self.is_closed,
        }

    def to_series(self) -> pd.Series:
        return pd.Series({
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }, name=self.timestamp)


class HistoricalDataService:
    """
    Service for fetching and caching historical market data.
    """

    def __init__(self, broker: Optional[BinanceBroker] = None):
        self.broker = broker or get_broker()
        self._cache: Dict[str, pd.DataFrame] = {}
        self._cache_timeout = 300  # 5 minutes
        self._cache_timestamp: Dict[str, datetime] = {}

    def _get_cache_key(self, symbol: str, timeframe: str) -> str:
        """Generate cache key for symbol/timeframe combination."""
        return f"{symbol}_{timeframe}"

    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached data is still valid."""
        if cache_key not in self._cache_timestamp:
            return False
        age = datetime.now() - self._cache_timestamp[cache_key]
        return age.total_seconds() < self._cache_timeout

    def get_historical_data(
        self,
        symbol: str = SYMBOL,
        timeframe: str = TIMEFRAME,
        limit: int = 500,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data from Binance.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            timeframe: Candle interval (1m, 5m, 15m, 1h, 4h, 1d)
            limit: Number of candles to fetch
            use_cache: Whether to use cached data if available

        Returns:
            DataFrame with OHLCV data
        """
        cache_key = self._get_cache_key(symbol, timeframe)

        # Check cache
        if use_cache and self._is_cache_valid(cache_key):
            logger.debug(f"Using cached data for {cache_key}")
            return self._cache[cache_key].copy()

        # Fetch from broker
        logger.info(f"Fetching historical data: {symbol} {timeframe} x{limit}")

        try:
            klines = self.broker.get_klines(symbol, timeframe, limit)

            df = self._klines_to_dataframe(klines)

            # Update cache
            self._cache[cache_key] = df.copy()
            self._cache_timestamp[cache_key] = datetime.now()

            return df

        except Exception as e:
            logger.error(f"Failed to fetch historical data: {e}")
            # Return cached data even if expired
            if cache_key in self._cache:
                logger.warning("Returning expired cached data")
                return self._cache[cache_key].copy()
            raise

    def get_data_range(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
    ) -> pd.DataFrame:
        """
        Fetch historical data for a specific date range.

        Note: Binance API has rate limits on historical data.
        """
        # Convert dates to milliseconds
        start_ms = int(start_date.timestamp() * 1000)
        end_ms = int(end_date.timestamp() * 1000)

        logger.info(f"Fetching data range: {symbol} {start_date} to {end_date}")

        all_klines = []
        current_start = start_ms

        while current_start < end_ms:
            klines = self.broker.get_klines(
                symbol=symbol,
                interval=timeframe,
                limit=1000,
                start_time=current_start,
                end_time=end_ms,
            )

            if not klines:
                break

            all_klines.extend(klines)

            # Move start time to after last candle
            current_start = klines[-1][0] + 1

            # Rate limit protection
            time.sleep(0.1)

        return self._klines_to_dataframe(all_klines)

    def _klines_to_dataframe(self, klines: List[List[Any]]) -> pd.DataFrame:
        """Convert Binance klines to DataFrame."""
        columns = [
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_buy_base", "taker_buy_quote", "ignore"
        ]

        df = pd.DataFrame(klines, columns=columns)
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]

        # Convert timestamp
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)

        # Convert to float
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)

        return df

    def clear_cache(self):
        """Clear all cached data."""
        self._cache.clear()
        self._cache_timestamp.clear()
        logger.info("Historical data cache cleared")


class DataFeedService:
    """
    Real-time data feed service using WebSocket.

    Provides live candle updates and price tick streaming.
    """

    def __init__(
        self,
        api_key: str = BINANCE_API_KEY,
        api_secret: str = BINANCE_SECRET_KEY,
    ):
        self.api_key = api_key
        self.api_secret = api_secret

        self._ws_manager: Optional[ThreadedWebsocketManager] = None
        self._live_candles: Dict[str, Candle] = {}
        self._candle_buffer: Dict[str, List[Candle]] = {}
        self._callbacks: List[Callable] = []
        self._lock = threading.Lock()

        self._running = False

    def start(
        self,
        symbols: List[str],
        timeframe: str = TIMEFRAME,
        callback: Optional[Callable] = None,
    ):
        """
        Start the WebSocket data feed.

        Args:
            symbols: List of symbols to subscribe to (e.g., ["BTCUSDT"])
            timeframe: Candle interval
            callback: Optional callback function for new candles
        """
        if self._running:
            logger.warning("Data feed already running")
            return

        self._ws_manager = ThreadedWebsocketManager(
            api_key=self.api_key,
            api_secret=self.api_secret,
        )

        self._ws_manager.start()

        for symbol in symbols:
            self._ws_manager.start_kline_socket(
                callback=self._handle_kline,
                symbol=symbol,
                interval=timeframe,
            )
            logger.info(f"Started data feed for {symbol} {timeframe}")

        if callback:
            self._callbacks.append(callback)

        self._running = True

    def stop(self):
        """Stop the WebSocket data feed."""
        if self._ws_manager:
            self._ws_manager.stop()
            self._ws_manager = None

        self._running = False
        self._callbacks.clear()
        logger.info("Data feed stopped")

    def _handle_kline(self, msg: Dict[str, Any]):
        """Handle incoming kline message from WebSocket."""
        if msg.get("e") == "error":
            logger.error(f"WebSocket error: {msg}")
            return

        kline = msg["k"]
        symbol = msg["s"]

        # Create candle object
        candle = Candle(
            timestamp=pd.to_datetime(kline["t"], unit="ms"),
            open=float(kline["o"]),
            high=float(kline["h"]),
            low=float(kline["l"]),
            close=float(kline["c"]),
            volume=float(kline["v"]),
            is_closed=kline["x"],
        )

        with self._lock:
            # Update current candle
            self._live_candles[symbol] = candle

            # Store closed candles
            if candle.is_closed:
                if symbol not in self._candle_buffer:
                    self._candle_buffer[symbol] = []
                self._candle_buffer[symbol].append(candle)

                # Keep only last 1000 candles
                if len(self._candle_buffer[symbol]) > 1000:
                    self._candle_buffer[symbol] = self._candle_buffer[symbol][-1000:]

        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(symbol, candle)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def get_current_candle(self, symbol: str) -> Optional[Candle]:
        """Get the current/latest candle for a symbol."""
        with self._lock:
            return self._live_candles.get(symbol)

    def get_candles_as_dataframe(
        self,
        symbol: str,
        n: int = 100,
        include_current: bool = False,
    ) -> pd.DataFrame:
        """
        Get recent candles as DataFrame.

        Args:
            symbol: Trading pair
            n: Number of candles to return
            include_current: Include the current (unfinished) candle

        Returns:
            DataFrame with OHLCV data
        """
        with self._lock:
            buffer = self._candle_buffer.get(symbol, [])
            candles = buffer[-n:] if len(buffer) >= n else buffer

        if not candles:
            return pd.DataFrame()

        # Add current candle if requested
        if include_current and symbol in self._live_candles:
            candles = candles + [self._live_candles[symbol]]

        # Convert to DataFrame
        data = {
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
        }
        index = [c.timestamp for c in candles]

        return pd.DataFrame(data, index=index)

    def is_running(self) -> bool:
        """Check if data feed is running."""
        return self._running


# Convenience functions
def get_historical_service() -> HistoricalDataService:
    """Get historical data service instance."""
    return HistoricalDataService()


def get_live_feed() -> DataFeedService:
    """Get live data feed instance."""
    return DataFeedService()
