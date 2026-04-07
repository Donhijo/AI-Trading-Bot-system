"""
Workers/rader.py - Market radar background worker.

Continuously scans the market for trading opportunities across
multiple symbols and timeframes.
"""
import time
import logging
import threading
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, timedelta
from enum import Enum

import pandas as pd
from tabulate import tabulate

from ai.features import create_features
from ai.predict import predict_signal_with_confidence
from Core.strategy import create_strategy, StrategyResult
from Services.data_feed import HistoricalDataService
from Services.broker import get_broker
from config import FEATURES, TIMEFRAME

logger = logging.getLogger("bot.radar")


class ScanStatus(Enum):
    """Scan result status."""
    SCANNING = "scanning"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class ScanResult:
    """Result from scanning a single symbol."""
    symbol: str
    timeframe: str
    signal: str
    confidence: float
    price: float
    rsi: Optional[float] = None
    macd: Optional[float] = None
    timestamp: datetime = field(default_factory=datetime.now)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "signal": self.signal,
            "confidence": self.confidence,
            "price": self.price,
            "rsi": self.rsi,
            "macd": self.macd,
            "timestamp": self.timestamp.isoformat(),
            "error": self.error,
        }


@dataclass
class RadarConfig:
    """Configuration for radar scanning."""
    watchlist: List[str] = field(default_factory=lambda: [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT",
        "ADAUSDT", "XRPUSDT", "DOGEUSDT", "AVAXUSDT",
        "LINKUSDT", "DOTUSDT", "MATICUSDT", "NEARUSDT"
    ])
    timeframes: List[str] = field(default_factory=lambda: ["15m", "1h"])
    min_confidence: float = 0.6
    scan_interval: int = 300  # 5 minutes between full scans
    lookback_candles: int = 200


class RadarWorker(threading.Thread):
    """
    Background worker for continuous market scanning.

    Scans configured symbols/timeframes and generates alerts
    for high-confidence trading signals.
    """

    def __init__(
        self,
        config: Optional[RadarConfig] = None,
        data_service: Optional[HistoricalDataService] = None,
        strategy_type: str = "ai",
    ):
        super().__init__(name="RadarWorker", daemon=True)

        self.config = config or RadarConfig()
        self.data_service = data_service or HistoricalDataService()
        self.strategy = create_strategy(strategy_type)

        self._stop_event = threading.Event()
        self._scan_results: List[ScanResult] = []
        self._callbacks: List[Callable] = []
        self._last_scan: Optional[datetime] = None

        self.logger = logging.getLogger("bot.radar")

        # Icons for signals
        self._signal_icons = {
            "BUY": "🟢",
            "SELL": "🔴",
            "HOLD": "⚪",
        }

    def stop(self):
        """Stop the radar worker."""
        self._stop_event.set()
        self.logger.info("Radar worker stopping...")

    def run(self):
        """Main scanning loop."""
        self.logger.info("Radar worker started")

        while not self._stop_event.is_set():
            try:
                self._perform_scan()

                # Wait for next scan interval
                self._stop_event.wait(self.config.scan_interval)

            except Exception as e:
                self.logger.error(f"Radar scan error: {e}")
                time.sleep(30)  # Short delay on error

        self.logger.info("Radar worker stopped")

    def _perform_scan(self):
        """Perform a full scan of all symbols and timeframes."""
        self.logger.info(f"Starting market scan: {len(self.config.watchlist)} symbols")
        self._last_scan = datetime.now()

        results = []

        for symbol in self.config.watchlist:
            for timeframe in self.config.timeframes:
                if self._stop_event.is_set():
                    break

                try:
                    result = self._scan_symbol(symbol, timeframe)
                    if result:
                        results.append(result)

                        # Trigger callbacks for high-confidence signals
                        if result.confidence >= self.config.min_confidence and result.signal != "HOLD":
                            self._notify_signal(result)

                except Exception as e:
                    self.logger.error(f"Error scanning {symbol} {timeframe}: {e}")
                    results.append(ScanResult(
                        symbol=symbol,
                        timeframe=timeframe,
                        signal="ERROR",
                        confidence=0.0,
                        price=0.0,
                        error=str(e),
                    ))

            # Small delay between symbols to avoid rate limits
            time.sleep(0.5)

        # Store results
        self._scan_results = results
        self._last_scan = datetime.now()

        # Log summary
        self._log_summary(results)

    def _scan_symbol(self, symbol: str, timeframe: str) -> Optional[ScanResult]:
        """Scan a single symbol/timeframe combination."""
        # Fetch data
        df = self.data_service.get_historical_data(
            symbol=symbol,
            timeframe=timeframe,
            limit=self.config.lookback_candles,
        )

        if df.empty or len(df) < 50:
            self.logger.warning(f"Insufficient data for {symbol} {timeframe}")
            return None

        # Create features
        df = create_features(df)

        # Get latest values
        latest = df.iloc[-1]
        price = latest["close"]

        # Get signal
        latest_features = df[FEATURES].tail(1)
        signal, confidence = predict_signal_with_confidence(latest_features)

        return ScanResult(
            symbol=symbol,
            timeframe=timeframe,
            signal=signal,
            confidence=confidence,
            price=price,
            rsi=latest.get("rsi"),
            macd=latest.get("macd"),
        )

    def _notify_signal(self, result: ScanResult):
        """Notify callbacks of a high-confidence signal."""
        self.logger.info(
            f"High confidence signal: {result.signal} {result.symbol} "
            f"({result.confidence:.1%})"
        )

        for callback in self._callbacks:
            try:
                callback(result)
            except Exception as e:
                self.logger.error(f"Signal callback error: {e}")

    def _log_summary(self, results: List[ScanResult]):
        """Log scan summary."""
        buy_signals = [r for r in results if r.signal == "BUY"]
        sell_signals = [r for r in results if r.signal == "SELL"]
        high_conf = [r for r in results if r.confidence >= self.config.min_confidence]

        self.logger.info(
            f"Scan complete: {len(buy_signals)} BUY, {len(sell_signals)} SELL, "
            f"{len(high_conf)} high confidence"
        )

        # Print table if there are signals
        if buy_signals or sell_signals:
            self._print_signals_table(results)

    def _print_signals_table(self, results: List[ScanResult]):
        """Print formatted signal table."""
        # Filter and sort: BUY first, then SELL, then HOLD
        order = {"BUY": 0, "SELL": 1, "HOLD": 2}
        sorted_results = sorted(results, key=lambda r: order.get(r.signal, 3))

        rows = []
        for r in sorted_results:
            if r.signal != "HOLD" or r.confidence >= self.config.min_confidence:
                rows.append({
                    " ": self._signal_icons.get(r.signal, "❓"),
                    "Symbol": r.symbol,
                    "TF": r.timeframe,
                    "Signal": r.signal,
                    "Conf": f"{r.confidence:.1%}",
                    "Price": f"${r.price:,.4f}",
                    "RSI": f"{r.rsi:.1f}" if r.rsi else "-",
                })

        if rows:
            print("\n" + "=" * 70)
            print(f"📡 MARKET RADAR | {self._last_scan.strftime('%Y-%m-%d %H:%M:%S')}")
            print(tabulate(rows, headers="keys", tablefmt="simple", showindex=False))
            print("=" * 70 + "\n")

    def get_results(
        self,
        signal_type: Optional[str] = None,
        min_confidence: Optional[float] = None,
    ) -> List[ScanResult]:
        """Get scan results with optional filtering."""
        results = self._scan_results

        if signal_type:
            results = [r for r in results if r.signal == signal_type]

        if min_confidence:
            results = [r for r in results if r.confidence >= min_confidence]

        return results

    def get_results_dataframe(self) -> pd.DataFrame:
        """Get scan results as DataFrame."""
        if not self._scan_results:
            return pd.DataFrame()

        data = [r.to_dict() for r in self._scan_results]
        return pd.DataFrame(data)

    def on_signal(self, callback: Callable):
        """Register callback for trade signals."""
        self._callbacks.append(callback)

    def get_status(self) -> Dict[str, Any]:
        """Get current radar status."""
        return {
            "running": self.is_alive(),
            "last_scan": self._last_scan.isoformat() if self._last_scan else None,
            "symbols_scanned": len(self.config.watchlist),
            "total_results": len(self._scan_results),
            "config": {
                "watchlist_size": len(self.config.watchlist),
                "timeframes": self.config.timeframes,
                "scan_interval": self.config.scan_interval,
                "min_confidence": self.config.min_confidence,
            },
        }


class OpportunityFinder:
    """
    Find trading opportunities across multiple conditions.
    """

    def __init__(self, radar_worker: Optional[RadarWorker] = None):
        self.radar = radar_worker
        self.logger = logging.getLogger("bot.opportunities")

    def find_divergences(self, df: pd.DataFrame) -> List[Dict]:
        """
        Find bullish/bearish divergences.

        Bullish: Price lower low, RSI higher low
        Bearish: Price higher high, RSI lower high
        """
        opportunities = []

        if len(df) < 20:
            return opportunities

        # Get swing highs and lows
        highs = df["high"].rolling(window=5, center=True).max()
        lows = df["low"].rolling(window=5, center=True).min()

        # Check for divergences
        price_highs = df["high"] == highs
        price_lows = df["low"] == lows

        # Bullish divergence
        if len(df[price_lows]) >= 2:
            recent_lows = df[price_lows].iloc[-2:]
            if len(recent_lows) == 2:
                price_lower = recent_lows["low"].iloc[-1] < recent_lows["low"].iloc[0]
                rsi_higher = recent_lows["rsi"].iloc[-1] > recent_lows["rsi"].iloc[0]

                if price_lower and rsi_higher:
                    opportunities.append({
                        "type": "bullish_divergence",
                        "confidence": 0.7,
                        "message": "Bullish RSI divergence detected",
                    })

        # Bearish divergence
        if len(df[price_highs]) >= 2:
            recent_highs = df[price_highs].iloc[-2:]
            if len(recent_highs) == 2:
                price_higher = recent_highs["high"].iloc[-1] > recent_highs["high"].iloc[0]
                rsi_lower = recent_highs["rsi"].iloc[-1] < recent_highs["rsi"].iloc[0]

                if price_higher and rsi_lower:
                    opportunities.append({
                        "type": "bearish_divergence",
                        "confidence": 0.7,
                        "message": "Bearish RSI divergence detected",
                    })

        return opportunities


# Convenience functions
def create_radar_worker(
    watchlist: List[str] = None,
    scan_interval: int = 300,
) -> RadarWorker:
    """Create and configure a radar worker."""
    config = RadarConfig(
        watchlist=watchlist,
        scan_interval=scan_interval,
    )
    return RadarWorker(config=config)


def run_single_scan(
    symbols: List[str],
    timeframe: str = "15m",
) -> pd.DataFrame:
    """Run a single market scan and return results as DataFrame."""
    config = RadarConfig(
        watchlist=symbols,
        timeframes=[timeframe],
    )
    worker = RadarWorker(config=config)

    # Run scan synchronously
    results = []
    for symbol in symbols:
        try:
            result = worker._scan_symbol(symbol, timeframe)
            if result:
                results.append(result)
        except Exception as e:
            logger.error(f"Scan failed for {symbol}: {e}")

    if results:
        return pd.DataFrame([r.to_dict() for r in results])
    return pd.DataFrame()
