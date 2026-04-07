import os
import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException
from config import RECV_WINDOW

logger = logging.getLogger("bot")

# Lazy client initialization
_client = None


def _get_client():
    """Get or create the Binance client (lazy initialization)."""
    global _client
    if _client is None:
        _client = Client(
            os.getenv("BINANCE_API_KEY", ""),
            os.getenv("BINANCE_SECRET_KEY", ""),
            requests_params={'timeout': 30},  # Increase timeout to 30 seconds
            # Enable automatic timestamp adjustment
            tld='com'  # Top level domain
        )
        # Sync time with Binance server
        try:
            _client.get_server_time()
        except Exception as e:
            logger.warning(f"Could not sync time with Binance: {e}")
    return _client


def place_order(symbol: str, side: str, quantity: float) -> dict:
    """Place a market order. Raises on failure."""
    client = _get_client()
    order = client.create_order(
        symbol=symbol,
        side=side,
        type="MARKET",
        quantity=quantity,
        recvWindow=RECV_WINDOW
    )
    logger.info(f"📋 Order placed: {side} {quantity} {symbol} → orderId={order['orderId']}")
    return order


def get_open_positions(symbol: str) -> list:
    """Return open orders for a symbol."""
    return _get_client().get_open_orders(symbol=symbol, recvWindow=RECV_WINDOW)


def cancel_order(symbol: str, order_id: int) -> dict:
    return _get_client().cancel_order(symbol=symbol, orderId=order_id, recvWindow=RECV_WINDOW)


def get_account_balance(asset: str = "USDT") -> float:
    """Return free balance of given asset."""
    client = _get_client()
    account = client.get_account(recvWindow=RECV_WINDOW)
    for b in account["balances"]:
        if b["asset"] == asset:
            return float(b["free"])
    return 0.0


def get_ticker_price(symbol: str) -> float:
    """Return latest price for symbol."""
    ticker = _get_client().get_symbol_ticker(symbol=symbol)
    return float(ticker["price"])