"""
Core/execution_.py - Central execution engine for order management.

This module provides the main execution logic that coordinates between
strategy signals, risk management, and broker interactions.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List, Callable
import pandas as pd

from config import SYMBOL, SL_PCT, TP_RATIO, INITIAL_BALANCE, RISK_PER_TRADE

logger = logging.getLogger("bot.execution")


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    ERROR = "error"


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"


@dataclass
class Order:
    """Represents a trading order."""
    symbol: str
    side: OrderSide
    quantity: float
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    order_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    filled_qty: float = 0.0
    avg_price: Optional[float] = None
    fee: float = 0.0
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert order to dictionary."""
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "order_type": self.order_type.value,
            "price": self.price,
            "stop_price": self.stop_price,
            "status": self.status.value,
            "order_id": self.order_id,
            "timestamp": self.timestamp.isoformat(),
            "filled_qty": self.filled_qty,
            "avg_price": self.avg_price,
            "fee": self.fee,
            "metadata": self.metadata,
        }


@dataclass
class Position:
    """Represents an open position."""
    symbol: str
    side: OrderSide
    entry_price: float
    quantity: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    open_time: datetime = field(default_factory=datetime.now)
    unrealized_pnl: float = 0.0

    def calculate_pnl(self, current_price: float) -> float:
        """Calculate unrealized PnL at current price."""
        if self.side == OrderSide.BUY:
            return (current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - current_price) * self.quantity

    def check_exit(self, high: float, low: float) -> Optional[str]:
        """Check if position should exit based on SL/TP."""
        if self.side == OrderSide.BUY:
            if low <= self.stop_loss:
                return "stop_loss"
            if high >= self.take_profit:
                return "take_profit"
        else:  # SELL
            if high >= self.stop_loss:
                return "stop_loss"
            if low <= self.take_profit:
                return "take_profit"
        return None


class ExecutionEngine:
    """
    Central execution engine that manages order lifecycle.

    Coordinates between strategy signals, risk management, and broker execution.
    """

    def __init__(
        self,
        broker_client=None,
        risk_manager=None,
        initial_balance: float = INITIAL_BALANCE,
        symbol: str = SYMBOL,
    ):
        self.broker = broker_client
        self.risk_manager = risk_manager
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.symbol = symbol

        self.open_position: Optional[Position] = None
        self.order_history: List[Order] = []
        self.trade_history: List[Dict] = []
        self.equity_curve: List[float] = [initial_balance]

        # Callbacks
        self.on_order_fill: Optional[Callable] = None
        self.on_position_close: Optional[Callable] = None

        self.logger = logging.getLogger("bot.execution")

    def can_trade(self) -> bool:
        """Check if trading conditions are met."""
        if self.risk_manager and not self.risk_manager.is_trading_allowed(
            self.current_balance, self.initial_balance
        ):
            self.logger.warning("Risk manager blocked trading")
            return False
        return True

    def process_signal(
        self,
        signal: str,
        current_price: float,
        features: Optional[pd.DataFrame] = None
    ) -> Optional[Order]:
        """
        Process a trading signal and execute if conditions are met.

        Args:
            signal: 'BUY', 'SELL', or 'HOLD'
            current_price: Current market price
            features: Optional feature DataFrame for risk calculations

        Returns:
            Order if executed, None otherwise
        """
        if signal == "HOLD":
            return None

        if not self.can_trade():
            return None

        # Check if we need to close existing position
        if self.open_position:
            if self._should_close_position(signal):
                return self._close_position(current_price)
            return None

        # Open new position
        if signal in ["BUY", "SELL"]:
            return self._open_position(signal, current_price)

        return None

    def _should_close_position(self, signal: str) -> bool:
        """Determine if current position should be closed based on signal."""
        if not self.open_position:
            return False

        current_side = self.open_position.side.value

        # Close on opposite signal
        if signal == "BUY" and current_side == "SELL":
            return True
        if signal == "SELL" and current_side == "BUY":
            return True

        return False

    def _open_position(self, signal: str, current_price: float) -> Optional[Order]:
        """Open a new position based on signal."""
        side = OrderSide.BUY if signal == "BUY" else OrderSide.SELL

        # Calculate position size
        if self.risk_manager:
            sl_price, tp_price = self.risk_manager.calculate_sl_tp(
                current_price, signal
            )
            quantity = self.risk_manager.calculate_position_size(
                self.current_balance, current_price, sl_price
            )
        else:
            # Default sizing
            sl_pct = SL_PCT
            tp_ratio = TP_RATIO
            if signal == "BUY":
                sl_price = current_price * (1 - sl_pct)
                tp_price = current_price * (1 + sl_pct * tp_ratio)
            else:
                sl_price = current_price * (1 + sl_pct)
                tp_price = current_price * (1 - sl_pct * tp_ratio)

            risk_amount = self.current_balance * RISK_PER_TRADE
            price_risk = abs(current_price - sl_price)
            quantity = risk_amount / price_risk if price_risk > 0 else 0

        if quantity <= 0:
            self.logger.warning(f"Position size too small: {quantity}")
            return None

        # Create and execute order
        order = Order(
            symbol=self.symbol,
            side=side,
            quantity=quantity,
            order_type=OrderType.MARKET,
        )

        # Execute via broker
        if self.broker:
            try:
                broker_order = self.broker.place_order(
                    self.symbol, side.value, quantity
                )
                order.order_id = str(broker_order.get("orderId", ""))
                order.status = OrderStatus.FILLED
                order.filled_qty = float(broker_order.get("executedQty", quantity))

                fills = broker_order.get("fills", [{}])
                if fills:
                    order.avg_price = float(fills[0].get("price", current_price))
                    order.fee = float(fills[0].get("commission", 0))

            except Exception as e:
                self.logger.error(f"Order execution failed: {e}")
                order.status = OrderStatus.ERROR
                return None
        else:
            # Simulation mode
            order.status = OrderStatus.FILLED
            order.avg_price = current_price
            order.filled_qty = quantity

        # Create position
        self.open_position = Position(
            symbol=self.symbol,
            side=side,
            entry_price=order.avg_price or current_price,
            quantity=order.filled_qty,
            stop_loss=sl_price,
            take_profit=tp_price,
        )

        self.order_history.append(order)

        self.logger.info(
            f"Position opened: {side.value} {quantity} @ {order.avg_price:.2f}"
        )

        if self.on_order_fill:
            self.on_order_fill(order)

        return order

    def _close_position(self, current_price: float) -> Optional[Order]:
        """Close the current open position."""
        if not self.open_position:
            return None

        position = self.open_position
        exit_side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY

        order = Order(
            symbol=self.symbol,
            side=exit_side,
            quantity=position.quantity,
            order_type=OrderType.MARKET,
        )

        # Execute via broker
        if self.broker:
            try:
                broker_order = self.broker.place_order(
                    self.symbol, exit_side.value, position.quantity
                )
                order.order_id = str(broker_order.get("orderId", ""))
                order.status = OrderStatus.FILLED
                order.filled_qty = float(broker_order.get("executedQty", position.quantity))

                fills = broker_order.get("fills", [{}])
                if fills:
                    order.avg_price = float(fills[0].get("price", current_price))
            except Exception as e:
                self.logger.error(f"Position close failed: {e}")
                order.status = OrderStatus.ERROR
                return None
        else:
            order.status = OrderStatus.FILLED
            order.avg_price = current_price
            order.filled_qty = position.quantity

        # Calculate PnL
        exit_price = order.avg_price or current_price
        pnl = position.calculate_pnl(exit_price)

        # Update balance
        self.current_balance += pnl
        self.equity_curve.append(self.current_balance)

        # Record trade
        trade = {
            "symbol": position.symbol,
            "side": position.side.value,
            "entry_price": position.entry_price,
            "exit_price": exit_price,
            "quantity": position.quantity,
            "pnl": pnl,
            "pnl_pct": (pnl / self.initial_balance) * 100,
            "entry_time": position.open_time.isoformat(),
            "exit_time": datetime.now().isoformat(),
            "reason": "signal",
        }
        self.trade_history.append(trade)

        self.order_history.append(order)

        self.logger.info(
            f"Position closed: PnL=${pnl:.2f} ({trade['pnl_pct']:.2f}%)"
        )

        # Clear position
        self.open_position = None

        if self.on_position_close:
            self.on_position_close(trade)

        return order

    def check_position_exits(self, high: float, low: float, close: float) -> Optional[Order]:
        """Check if open position should exit based on SL/TP levels."""
        if not self.open_position:
            return None

        exit_reason = self.open_position.check_exit(high, low)
        if exit_reason:
            self.logger.info(f"Position exit triggered: {exit_reason}")
            return self._close_position_at_sl_tp(exit_reason, high, low, close)

        # Update unrealized PnL
        self.open_position.unrealized_pnl = self.open_position.calculate_pnl(close)

        return None

    def _close_position_at_sl_tp(
        self, reason: str, high: float, low: float, close: float
    ) -> Optional[Order]:
        """Close position at SL or TP price."""
        if not self.open_position:
            return None

        position = self.open_position

        # Determine exit price
        if position.side == OrderSide.BUY:
            exit_price = position.stop_loss if reason == "stop_loss" else position.take_profit
        else:
            exit_price = position.stop_loss if reason == "stop_loss" else position.take_profit

        exit_side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY

        order = Order(
            symbol=self.symbol,
            side=exit_side,
            quantity=position.quantity,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
            avg_price=exit_price,
            filled_qty=position.quantity,
        )

        # Calculate PnL
        pnl = position.calculate_pnl(exit_price)
        self.current_balance += pnl
        self.equity_curve.append(self.current_balance)

        trade = {
            "symbol": position.symbol,
            "side": position.side.value,
            "entry_price": position.entry_price,
            "exit_price": exit_price,
            "quantity": position.quantity,
            "pnl": pnl,
            "pnl_pct": (pnl / self.initial_balance) * 100,
            "entry_time": position.open_time.isoformat(),
            "exit_time": datetime.now().isoformat(),
            "reason": reason,
        }
        self.trade_history.append(trade)
        self.order_history.append(order)

        self.logger.info(
            f"Position {reason}: PnL=${pnl:.2f} ({trade['pnl_pct']:.2f}%)"
        )

        self.open_position = None

        if self.on_position_close:
            self.on_position_close(trade)

        return order

    def get_stats(self) -> Dict:
        """Get execution statistics."""
        total_trades = len(self.trade_history)
        wins = [t for t in self.trade_history if t["pnl"] > 0]
        losses = [t for t in self.trade_history if t["pnl"] <= 0]

        total_pnl = sum(t["pnl"] for t in self.trade_history)

        return {
            "total_trades": total_trades,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": len(wins) / total_trades * 100 if total_trades > 0 else 0,
            "total_pnl": total_pnl,
            "total_pnl_pct": (total_pnl / self.initial_balance) * 100,
            "current_balance": self.current_balance,
            "current_drawdown": (self.initial_balance - self.current_balance)
            / self.initial_balance
            if self.current_balance < self.initial_balance
            else 0,
            "open_position": self.open_position.to_dict() if self.open_position else None,
        }
