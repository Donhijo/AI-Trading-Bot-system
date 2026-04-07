"""
Services/broker.py - Exchange broker service layer.

Provides a unified interface for exchange operations with:
- Order placement and management
- Account balance queries
- Market data access
- Error handling and retry logic
"""
import os
import time
import logging
from typing import Optional, Dict, List, Any
from decimal import Decimal, ROUND_DOWN
from functools import wraps

from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException

from config import BINANCE_API_KEY, BINANCE_SECRET_KEY

logger = logging.getLogger("bot.broker")


def retry_on_error(max_retries: int = 3, delay: float = 1.0):
    """Decorator to retry API calls on failure."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    logger.warning(f"Retry {attempt + 1}/{max_retries} for {func.__name__}: {e}")
                    time.sleep(delay * (attempt + 1))
            return None
        return wrapper
    return decorator


class BinanceBroker:
    """
    Binance exchange broker interface.

    Provides a clean abstraction over the python-binance client
    with error handling, logging, and retry logic.
    """

    def __init__(
        self,
        api_key: str = None,
        api_secret: str = None,
        testnet: bool = False,
    ):
        """
        Initialize the Binance broker.

        Args:
            api_key: Binance API key (defaults to env/BINANCE_API_KEY)
            api_secret: Binance API secret (defaults to env/BINANCE_SECRET_KEY)
            testnet: Use Binance testnet for paper trading
        """
        self.api_key = api_key or BINANCE_API_KEY
        self.api_secret = api_secret or BINANCE_SECRET_KEY
        self.testnet = testnet

        if not self.api_key or not self.api_secret:
            logger.warning("Binance API credentials not configured!")

        self.client = Client(
            self.api_key,
            self.api_secret,
            testnet=testnet,
        )

        self.logger = logging.getLogger("bot.broker")
        self._symbol_info_cache: Dict[str, Any] = {}

    def is_configured(self) -> bool:
        """Check if broker is properly configured with credentials."""
        return bool(self.api_key and self.api_secret)

    @retry_on_error(max_retries=3)
    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        test: bool = False,
    ) -> Dict[str, Any]:
        """
        Place an order on Binance.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            side: "BUY" or "SELL"
            quantity: Amount to trade
            order_type: "MARKET", "LIMIT", "STOP_LOSS", etc.
            price: Limit price (required for LIMIT orders)
            test: If True, test the order without execution

        Returns:
            Order response from Binance

        Raises:
            BinanceAPIException: If order fails
        """
        # Adjust quantity to symbol precision
        adjusted_qty = self._adjust_quantity(symbol, quantity)

        if adjusted_qty <= 0:
            raise ValueError(f"Quantity too small after adjustment: {adjusted_qty}")

        params = {
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": adjusted_qty,
        }

        if order_type == "LIMIT" and price:
            params["price"] = self._adjust_price(symbol, price)
            params["timeInForce"] = "GTC"

        self.logger.info(
            f"Placing {side} {order_type} order: {adjusted_qty} {symbol}"
        )

        if test:
            result = self.client.create_test_order(**params)
            self.logger.info(f"Test order successful: {result}")
        else:
            result = self.client.create_order(**params)
            self.logger.info(
                f"Order filled: ID={result.get('orderId')}, "
                f"Qty={result.get('executedQty')}, "
                f"Price={result.get('fills', [{}])[0].get('price', 'N/A')}"
            )

        return result

    @retry_on_error(max_retries=3)
    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
    ) -> Dict[str, Any]:
        """Convenience method for market orders."""
        return self.place_order(symbol, side, quantity, "MARKET")

    @retry_on_error(max_retries=3)
    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """Cancel an open order."""
        self.logger.info(f"Cancelling order {order_id} for {symbol}")
        return self.client.cancel_order(symbol=symbol, orderId=order_id)

    @retry_on_error(max_retries=3)
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all open orders (or for specific symbol)."""
        return self.client.get_open_orders(symbol=symbol)

    @retry_on_error(max_retries=3)
    def get_order_status(self, symbol: str, order_id: str) -> Dict[str, Any]:
        """Get status of a specific order."""
        return self.client.get_order(symbol=symbol, orderId=order_id)

    @retry_on_error(max_retries=3)
    def get_account_balance(self, asset: Optional[str] = None) -> Dict[str, float]:
        """
        Get account balance.

        Args:
            asset: Specific asset (e.g., "USDT") or None for all

        Returns:
            Dict of asset -> balance, or single balance if asset specified
        """
        account = self.client.get_account()
        balances = {}

        for b in account["balances"]:
            asset_name = b["asset"]
            free = float(b["free"])
            locked = float(b["locked"])

            if free > 0 or locked > 0:
                balances[asset_name] = {
                    "free": free,
                    "locked": locked,
                    "total": free + locked,
                }

        if asset:
            return balances.get(asset, {"free": 0.0, "locked": 0.0, "total": 0.0})

        return balances

    @retry_on_error(max_retries=3)
    def get_ticker_price(self, symbol: str) -> float:
        """Get current ticker price for symbol."""
        ticker = self.client.get_symbol_ticker(symbol=symbol)
        return float(ticker["price"])

    @retry_on_error(max_retries=3)
    def get_orderbook(self, symbol: str, limit: int = 5) -> Dict[str, Any]:
        """Get order book for symbol."""
        return self.client.get_order_book(symbol=symbol, limit=limit)

    @retry_on_error(max_retries=3)
    def get_24h_ticker(self, symbol: str) -> Dict[str, Any]:
        """Get 24-hour statistics for symbol."""
        return self.client.get_ticker(symbol=symbol)

    @retry_on_error(max_retries=3)
    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> List[List[Any]]:
        """
        Get historical kline/candlestick data.

        Args:
            symbol: Trading pair
            interval: Kline interval (1m, 5m, 15m, 1h, 4h, 1d, etc.)
            limit: Number of candles (max 1000)
            start_time: Start time in milliseconds
            end_time: End time in milliseconds

        Returns:
            List of kline data
        """
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        return self.client.get_klines(**params)

    def _get_symbol_info(self, symbol: str) -> Dict[str, Any]:
        """Get and cache symbol info for precision calculations."""
        if symbol not in self._symbol_info_cache:
            info = self.client.get_symbol_info(symbol)
            if info:
                self._symbol_info_cache[symbol] = info
            else:
                raise ValueError(f"Symbol {symbol} not found on Binance")
        return self._symbol_info_cache[symbol]

    def _adjust_quantity(self, symbol: str, quantity: float) -> float:
        """Adjust quantity to symbol's step size requirements."""
        try:
            info = self._get_symbol_info(symbol)
            filters = {f["filterType"]: f for f in info.get("filters", [])}

            if "LOT_SIZE" in filters:
                step_size = float(filters["LOT_SIZE"]["stepSize"])
                min_qty = float(filters["LOT_SIZE"]["minQty"])

                # Round down to step size
                decimal_places = len(str(step_size).split(".")[-1].rstrip("0"))
                quantity = float(Decimal(str(quantity)).quantize(
                    Decimal("0." + "0" * decimal_places),
                    rounding=ROUND_DOWN
                ))

                # Check minimum quantity
                if quantity < min_qty:
                    return 0.0

            return quantity
        except Exception as e:
            self.logger.warning(f"Could not adjust quantity: {e}")
            return round(quantity, 6)  # Fallback

    def _adjust_price(self, symbol: str, price: float) -> float:
        """Adjust price to symbol's tick size requirements."""
        try:
            info = self._get_symbol_info(symbol)
            filters = {f["filterType"]: f for f in info.get("filters", [])}

            if "PRICE_FILTER" in filters:
                tick_size = float(filters["PRICE_FILTER"]["tickSize"])
                decimal_places = len(str(tick_size).split(".")[-1].rstrip("0"))
                price = float(Decimal(str(price)).quantize(
                    Decimal("0." + "0" * decimal_places),
                    rounding=ROUND_DOWN
                ))

            return price
        except Exception as e:
            self.logger.warning(f"Could not adjust price: {e}")
            return round(price, 2)  # Fallback

    def get_exchange_info(self) -> Dict[str, Any]:
        """Get exchange info including trading rules."""
        return self.client.get_exchange_info()


# Singleton instance
_broker_instance: Optional[BinanceBroker] = None


def get_broker() -> BinanceBroker:
    """Get or create the singleton broker instance."""
    global _broker_instance
    if _broker_instance is None:
        _broker_instance = BinanceBroker()
    return _broker_instance


def reset_broker():
    """Reset the broker singleton (useful for testing)."""
    global _broker_instance
    _broker_instance = None
