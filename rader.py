"""
rader.py — Market Radar Scanner.

Scans a watchlist of symbols, runs the AI model on each,
and prints a ranked signal table.

Usage:
    python rader.py
    python rader.py --timeframe 1h --limit 300
"""
import argparse
import pandas as pd
from binance.client import Client
from tabulate import tabulate

from ai.features import create_features
from ai.predict import predict_signal_with_confidence
from config import BINANCE_API_KEY, BINANCE_SECRET_KEY, FEATURES

# Lazy client initialization
_client = None


def _get_client():
    """Get or create the Binance client (lazy initialization)."""
    global _client
    if _client is None:
        _client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)
    return _client


WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT",
    "ADAUSDT", "XRPUSDT", "DOGEUSDT", "AVAXUSDT",
    "LINKUSDT", "DOTUSDT", "MATICUSDT", "NEARUSDT"
]

_COLUMNS = [
    "timestamp", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore"
]


def _fetch(symbol: str, timeframe: str, limit: int) -> pd.DataFrame | None:
    try:
        klines = _get_client().get_klines(symbol=symbol, interval=timeframe, limit=limit)
        df = pd.DataFrame(klines, columns=_COLUMNS)
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        print(f"  [!] {symbol} fetch failed: {e}")
        return None


def scan_market(
    symbols: list = WATCHLIST,
    timeframe: str = "15m",
    limit: int = 200
) -> pd.DataFrame:
    """Scan all symbols and return a DataFrame of signals."""
    rows = []

    for symbol in symbols:
        df = _fetch(symbol, timeframe, limit)
        if df is None:
            continue

        df = create_features(df)
        if len(df) < 10:
            continue

        latest = df[FEATURES].tail(1)
        signal, confidence = predict_signal_with_confidence(latest)

        rows.append({
            "Symbol":     symbol,
            "Signal":     signal,
            "Conf%":      f"{confidence:.1%}",
            "RSI":        round(df["rsi"].iloc[-1], 1),
            "MACD":       round(df["macd"].iloc[-1], 4),
            "Close":      round(df["close"].iloc[-1], 4),
        })

    result = pd.DataFrame(rows)
    # Sort: BUY first, then SELL, then HOLD
    order = {"BUY": 0, "SELL": 1, "HOLD": 2}
    result["_ord"] = result["Signal"].map(order)
    result = result.sort_values("_ord").drop(columns="_ord").reset_index(drop=True)
    return result


def print_radar(timeframe: str = "15m", limit: int = 200):
    print(f"\n[SCAN] MARKET RADAR  |  {timeframe} candles  |  {len(WATCHLIST)} pairs")
    print("=" * 60)

    df = scan_market(timeframe=timeframe, limit=limit)

    icons = {"BUY": "[BUY]", "SELL": "[SELL]", "HOLD": "[HOLD]"}
    df["  "] = df["Signal"].map(icons)
    df = df[["  ", "Symbol", "Signal", "Conf%", "RSI", "MACD", "Close"]]

    print(tabulate(df, headers="keys", tablefmt="simple", showindex=False))
    print("=" * 60)
    print(f"  [BUY]: {(df['Signal']=='BUY').sum()}  "
          f"[SELL]: {(df['Signal']=='SELL').sum()}  "
          f"[HOLD]: {(df['Signal']=='HOLD').sum()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Market Radar Scanner")
    parser.add_argument("--timeframe", default="15m", help="Binance interval (default: 15m)")
    parser.add_argument("--limit",     default=200, type=int, help="Candles per symbol")
    args = parser.parse_args()

    print_radar(timeframe=args.timeframe, limit=args.limit)