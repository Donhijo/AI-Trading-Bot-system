"""
Core/risk.py - Risk management and position sizing.

This module provides comprehensive risk management including:
- Position sizing based on fixed fractional risk
- Stop-loss and take-profit calculations
- Drawdown monitoring and circuit breakers
- Risk-adjusted position limits
"""
import logging
from dataclasses import dataclass
from typing import Optional, Tuple, List

from config import (
    RISK_PER_TRADE,
    SL_PCT,
    TP_RATIO,
    MAX_DRAWDOWN_PCT,
    INITIAL_BALANCE,
    MAX_OPEN_TRADES,
)

logger = logging.getLogger("bot.risk")


@dataclass
class RiskParameters:
    """Container for risk management parameters."""
    risk_per_trade: float = RISK_PER_TRADE
    sl_pct: float = SL_PCT
    tp_ratio: float = TP_RATIO
    max_drawdown_pct: float = MAX_DRAWDOWN_PCT
    max_open_trades: int = MAX_OPEN_TRADES
    min_position_size: float = 0.001  # Minimum position in base asset
    max_position_size_pct: float = 0.5  # Max 50% of balance in one trade


class PositionSizer:
    """
    Fixed-fractional position sizing calculator.

    Calculates position size based on account risk percentage and
    the distance to stop-loss level.
    """

    def __init__(self, params: RiskParameters = None):
        self.params = params or RiskParameters()

    def calculate(
        self,
        balance: float,
        entry_price: float,
        stop_loss_price: float,
        confidence: Optional[float] = None,
    ) -> float:
        """
        Calculate position size using fixed fractional risk.

        Formula: Position Size = (Balance * Risk%) / |Entry - Stop|

        Args:
            balance: Current account balance
            entry_price: Intended entry price
            stop_loss_price: Stop-loss price level
            confidence: Optional AI confidence to scale position

        Returns:
            Position size in base asset units
        """
        risk_amount = balance * self.params.risk_per_trade
        price_risk = abs(entry_price - stop_loss_price)

        if price_risk == 0:
            logger.warning("Price risk is zero, cannot calculate position size")
            return 0.0

        position_size = risk_amount / price_risk

        # Apply confidence scaling if provided
        if confidence:
            position_size *= self._confidence_multiplier(confidence)

        # Apply maximum position limit
        max_position = (balance * self.params.max_position_size_pct) / entry_price
        position_size = min(position_size, max_position)

        # Apply minimum position threshold
        if position_size < self.params.min_position_size:
            logger.warning(f"Position size {position_size:.6f} below minimum threshold")
            return 0.0

        return round(position_size, 6)

    def _confidence_multiplier(self, confidence: float) -> float:
        """
        Scale position size based on AI confidence.

        Args:
            confidence: Model confidence (0.0 to 1.0)

        Returns:
            Multiplier to apply to position size
        """
        # Scale linearly from 0.5 (at 50% confidence) to 1.5 (at 100% confidence)
        if confidence < 0.5:
            return 0.5
        elif confidence > 0.9:
            return 1.5
        else:
            return 0.5 + confidence


class DrawdownController:
    """
    Monitors drawdown and implements circuit breakers.

    Prevents trading when account drawdown exceeds configured thresholds.
    """

    def __init__(
        self,
        max_drawdown_pct: float = MAX_DRAWDOWN_PCT,
        warning_threshold: float = 0.05,  # 5% warning
    ):
        self.max_drawdown_pct = max_drawdown_pct
        self.warning_threshold = warning_threshold
        self.peak_balance = INITIAL_BALANCE
        self.current_drawdown = 0.0
        self.trading_paused = False
        self.pause_until = None

    def update(self, current_balance: float) -> Tuple[bool, Optional[str]]:
        """
        Update drawdown calculations and check limits.

        Args:
            current_balance: Current account balance

        Returns:
            Tuple of (can_trade, message if blocked)
        """
        # Update peak
        if current_balance > self.peak_balance:
            self.peak_balance = current_balance
            self.current_drawdown = 0.0

        # Calculate current drawdown
        self.current_drawdown = max(
            0.0, (self.peak_balance - current_balance) / self.peak_balance
        )

        # Check if we're in a paused state
        if self.trading_paused:
            if self.current_drawdown < self.warning_threshold:
                self.trading_paused = False
                logger.info("Drawdown recovered - trading resumed")
            else:
                return False, f"Trading paused: drawdown {self.current_drawdown:.1%}"

        # Check max drawdown limit
        if self.current_drawdown >= self.max_drawdown_pct:
            self.trading_paused = True
            msg = f"Max drawdown hit: {self.current_drawdown:.1%} (limit: {self.max_drawdown_pct:.1%})"
            logger.error(msg)
            return False, msg

        # Warning at threshold
        if self.current_drawdown >= self.warning_threshold:
            logger.warning(f"Drawdown warning: {self.current_drawdown:.1%}")

        return True, None

    def get_drawdown_pct(self) -> float:
        """Return current drawdown as percentage."""
        return self.current_drawdown

    def get_peak_balance(self) -> float:
        """Return peak balance seen."""
        return self.peak_balance

    def reset(self):
        """Reset drawdown tracking."""
        self.peak_balance = INITIAL_BALANCE
        self.current_drawdown = 0.0
        self.trading_paused = False


class RiskManager:
    """
    Centralized risk management controller.

    Coordinates position sizing, drawdown control, and trade validation.
    """

    def __init__(self, params: RiskParameters = None):
        self.params = params or RiskParameters()
        self.position_sizer = PositionSizer(params)
        self.drawdown_controller = DrawdownController(params.max_drawdown_pct)
        self.open_trades: List[dict] = []

    def is_trading_allowed(
        self, current_balance: float, initial_balance: float = INITIAL_BALANCE
    ) -> bool:
        """
        Check if trading is allowed based on all risk criteria.

        Args:
            current_balance: Current account balance
            initial_balance: Initial account balance

        Returns:
            True if trading is permitted
        """
        # Check drawdown limits
        can_trade, msg = self.drawdown_controller.update(current_balance)
        if not can_trade:
            return False

        # Check max open trades
        if len(self.open_trades) >= self.params.max_open_trades:
            logger.warning(f"Max open trades reached: {len(self.open_trades)}")
            return False

        return True

    def calculate_position_size(
        self, balance: float, entry_price: float, stop_loss_price: float
    ) -> float:
        """
        Calculate position size using configured risk parameters.

        Args:
            balance: Current account balance
            entry_price: Entry price
            stop_loss_price: Stop-loss price

        Returns:
            Position size in base asset
        """
        return self.position_sizer.calculate(balance, entry_price, stop_loss_price)

    def calculate_sl_tp(self, entry_price: float, signal: str) -> Tuple[float, float]:
        """
        Calculate stop-loss and take-profit prices.

        Args:
            entry_price: Entry price
            signal: 'BUY' or 'SELL'

        Returns:
            Tuple of (stop_loss_price, take_profit_price)
        """
        sl_pct = self.params.sl_pct
        tp_ratio = self.params.tp_ratio

        if signal == "BUY":
            sl = entry_price * (1 - sl_pct)
            tp = entry_price * (1 + sl_pct * tp_ratio)
        else:  # SELL
            sl = entry_price * (1 + sl_pct)
            tp = entry_price * (1 - sl_pct * tp_ratio)

        return round(sl, 6), round(tp, 6)

    def validate_trade(
        self,
        signal: str,
        balance: float,
        entry_price: float,
        confidence: Optional[float] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate a potential trade against all risk rules.

        Args:
            signal: Trading signal ('BUY', 'SELL', 'HOLD')
            balance: Current balance
            entry_price: Proposed entry price
            confidence: Model confidence

        Returns:
            Tuple of (is_valid, reason_if_invalid)
        """
        if signal == "HOLD":
            return False, "Signal is HOLD"

        # Check if trading allowed
        if not self.is_trading_allowed(balance):
            return False, "Trading not allowed due to risk controls"

        # Calculate position size
        sl, _ = self.calculate_sl_tp(entry_price, signal)
        size = self.calculate_position_size(balance, entry_price, sl)

        if size <= 0:
            return False, f"Position size too small: {size}"

        return True, None

    def register_trade(self, trade: dict):
        """Register an open trade for tracking."""
        self.open_trades.append(trade)

    def close_trade(self, trade_id: str):
        """Remove a trade from open trades."""
        self.open_trades = [t for t in self.open_trades if t.get("id") != trade_id]

    def get_stats(self) -> dict:
        """Get risk management statistics."""
        return {
            "current_drawdown": self.drawdown_controller.get_drawdown_pct(),
            "peak_balance": self.drawdown_controller.get_peak_balance(),
            "max_drawdown_limit": self.params.max_drawdown_pct,
            "open_trades": len(self.open_trades),
            "max_open_trades": self.params.max_open_trades,
            "risk_per_trade": self.params.risk_per_trade,
        }
