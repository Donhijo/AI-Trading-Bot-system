import os
import logging
import sys
import requests
from datetime import datetime
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# ── Logging Setup ──────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)

# Fix for Windows Unicode encoding issues
if sys.platform.startswith('win'):
    import io
    # Set stdout to UTF-8 encoding
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    # Create a custom handler that handles Unicode properly
    class UTF8StreamHandler(logging.StreamHandler):
        def __init__(self, stream=None):
            super().__init__(stream)
            if stream is None:
                stream = sys.stderr
            self.stream = stream

        def emit(self, record):
            try:
                msg = self.format(record)
                stream = self.stream
                # Handle Unicode encoding for Windows
                if hasattr(stream, 'encoding') and stream.encoding != 'utf-8':
                    msg = msg.encode('utf-8', errors='replace').decode('utf-8')
                stream.write(msg + self.terminator)
                self.flush()
            except Exception:
                self.handleError(record)

    # Use the custom handler
    handler = UTF8StreamHandler()
else:
    handler = logging.StreamHandler()

handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding='utf-8'),
        handler
    ]
)
logger = logging.getLogger("bot")


# ── Telegram ───────────────────────────────────────────────────────────────────
def send_alert(message: str) -> bool:
    """Send a Telegram message. Returns True on success."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("Telegram not configured — skipping alert")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=5)
        return r.status_code == 200
    except Exception as e:
        logger.warning(f"Telegram alert failed: {e}")
        return False


# ── Structured Log Helpers ─────────────────────────────────────────────────────
def log_signal(signal: str, confidence: float | None = None):
    icon = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(signal, "❓")
    msg  = f"{icon} Signal: <b>{signal}</b>"
    if confidence is not None:
        msg += f" | Confidence: {confidence:.1%}"
    logger.info(msg.replace("<b>", "").replace("</b>", ""))


def log_trade(signal: str, price: float, quantity: float, pnl: float | None = None):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg  = f"[{ts}] TRADE | {signal} | Price: {price:.4f} | Qty: {quantity:.6f}"
    if pnl is not None:
        msg += f" | PnL: {pnl:+.4f}"
    logger.info(msg)
    send_alert(f"✅ {msg}")


def log_balance(balance: float, drawdown: float | None = None):
    msg = f"💰 Balance: {balance:.2f} USDT"
    if drawdown is not None:
        msg += f" | Drawdown: {drawdown:.1%}"
    logger.info(msg)


def log_error(context: str, error: Exception):
    logger.error(f"❌ {context}: {error}")
    send_alert(f"❌ Error in <b>{context}</b>: {error}")
