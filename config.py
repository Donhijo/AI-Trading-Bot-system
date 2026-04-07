import os
from dotenv import load_dotenv

load_dotenv()

# ── Binance Credentials ────────────────────────────────────────────────────────
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY", "")

# ── Binance API Settings ───────────────────────────────────────────────────────
RECV_WINDOW = int(os.getenv("RECV_WINDOW", 60000))  # 60 seconds default

# ── Market Settings ────────────────────────────────────────────────────────────
SYMBOL    = os.getenv("SYMBOL", "BTCUSDT")
TIMEFRAME = os.getenv("TIMEFRAME", "15m")   # Binance interval string
LIMIT     = int(os.getenv("LIMIT", 500))    # Candles to fetch

# ── Risk Management ────────────────────────────────────────────────────────────
INITIAL_BALANCE  = float(os.getenv("INITIAL_BALANCE", 1000))
RISK_PER_TRADE   = float(os.getenv("RISK_PER_TRADE", 0.02))   # 2% per trade
SL_PCT           = float(os.getenv("SL_PCT", 0.02))            # 2% stop-loss
TP_RATIO         = float(os.getenv("TP_RATIO", 2.0))           # 2:1 R:R
MAX_DRAWDOWN_PCT = float(os.getenv("MAX_DRAWDOWN_PCT", 0.10))  # 10% max dd
MAX_OPEN_TRADES  = int(os.getenv("MAX_OPEN_TRADES", 1))

# ── AI Model ───────────────────────────────────────────────────────────────────
MODEL_PATH = os.getenv("MODEL_PATH", "ai/model.pkl")
FEATURES   = ["rsi", "macd", "ema", "returns"]

# ── Alerts (Telegram) ──────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Bot Loop ───────────────────────────────────────────────────────────────────
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 60))  # seconds between cycles
