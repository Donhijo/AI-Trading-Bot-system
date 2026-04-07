"""
Database/models.py - SQLAlchemy ORM models.

Defines database schema for the trading bot including:
- Trade history
- Order records
- Balance snapshots
- Signal logs
- Backtest results
"""
import json
from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Boolean,
    Text,
    ForeignKey,
    Index,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class JSONEncodedDict:
    """Mixin for handling JSON fields."""

    @staticmethod
    def encode(data: Dict[str, Any]) -> str:
        return json.dumps(data) if data else "{}"

    @staticmethod
    def decode(data: str) -> Dict[str, Any]:
        return json.loads(data) if data else {}


class Trade(Base):
    """
    Trade record - completed trades with PnL.
    """
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)  # BUY or SELL

    # Prices
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)

    # Quantities
    quantity = Column(Float, nullable=False)
    filled_qty = Column(Float, nullable=True)

    # PnL
    pnl = Column(Float, nullable=False)
    pnl_pct = Column(Float, nullable=False)

    # Risk parameters
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)

    # Fees
    entry_fee = Column(Float, default=0.0)
    exit_fee = Column(Float, default=0.0)

    # Timing
    entry_time = Column(DateTime, default=datetime.utcnow)
    exit_time = Column(DateTime, default=datetime.utcnow)

    # Trade duration in minutes
    duration_minutes = Column(Float, nullable=True)

    # Exit reason
    exit_reason = Column(String(50), default="signal")  # signal, stop_loss, take_profit

    # Strategy info
    strategy = Column(String(50), default="hybrid")
    confidence = Column(Float, nullable=True)

    # Extra data
    extra_data_json = Column("extra_data", Text, default="{}")

    # Relationships
    orders = relationship("Order", back_populates="trade")

    __table_args__ = (
        Index("ix_trades_symbol_time", "symbol", "entry_time"),
        Index("ix_trades_exit_time", "exit_time"),
    )

    @property
    def extra_data(self) -> Dict[str, Any]:
        return JSONEncodedDict.decode(self.extra_data_json)

    @extra_data.setter
    def extra_data(self, value: Dict[str, Any]):
        self.extra_data_json = JSONEncodedDict.encode(value)

    def __repr__(self):
        return f"<Trade({self.id}: {self.side} {self.symbol} PnL=${self.pnl:.2f})>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert trade to dictionary."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "exit_reason": self.exit_reason,
            "strategy": self.strategy,
            "confidence": self.confidence,
            "extra_data": self.extra_data,
        }


class Order(Base):
    """
    Order record - individual orders (entry, exit, partial fills).
    """
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=True)

    # Order details
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)  # BUY or SELL
    order_type = Column(String(20), nullable=False)  # MARKET, LIMIT, etc.

    # Quantities
    quantity = Column(Float, nullable=False)
    filled_qty = Column(Float, default=0.0)

    # Prices
    price = Column(Float, nullable=True)  # For limit orders
    avg_price = Column(Float, nullable=True)  # Average fill price

    # Fees
    fee = Column(Float, default=0.0)
    fee_asset = Column(String(10), default="USDT")

    # Status
    status = Column(String(20), default="pending")  # pending, filled, partial, cancelled

    # External order ID from exchange
    exchange_order_id = Column(String(100), nullable=True, index=True)

    # Timing
    created_at = Column(DateTime, default=datetime.utcnow)
    filled_at = Column(DateTime, nullable=True)

    # Error info
    error_message = Column(Text, nullable=True)

    # Relationships
    trade = relationship("Trade", back_populates="orders")

    def __repr__(self):
        return f"<Order({self.id}: {self.side} {self.filled_qty}/{self.quantity} {self.symbol})>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert order to dictionary."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "quantity": self.quantity,
            "filled_qty": self.filled_qty,
            "price": self.price,
            "avg_price": self.avg_price,
            "fee": self.fee,
            "status": self.status,
            "exchange_order_id": self.exchange_order_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
        }


class BalanceSnapshot(Base):
    """
    Account balance snapshots for tracking equity curve.
    """
    __tablename__ = "balance_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    asset = Column(String(10), default="USDT")
    balance = Column(Float, nullable=False)
    equity = Column(Float, nullable=True)  # Total account value including positions

    # Drawdown tracking
    peak_balance = Column(Float, nullable=True)
    current_drawdown_pct = Column(Float, nullable=True)

    # Timestamp
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    # Open position info
    open_position_value = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)

    __table_args__ = (
        Index("ix_balance_asset_time", "asset", "timestamp"),
    )

    def __repr__(self):
        return f"<BalanceSnapshot({self.asset}: {self.balance:.2f} @ {self.timestamp})>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary."""
        return {
            "id": self.id,
            "asset": self.asset,
            "balance": self.balance,
            "equity": self.equity,
            "peak_balance": self.peak_balance,
            "current_drawdown_pct": self.current_drawdown_pct,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "open_position_value": self.open_position_value,
            "unrealized_pnl": self.unrealized_pnl,
        }


class SignalLog(Base):
    """
    Log of all generated signals (even those not acted upon).
    """
    __tablename__ = "signal_logs"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    signal = Column(String(10), nullable=False)  # BUY, SELL, HOLD
    confidence = Column(Float, nullable=False)

    # Market data at signal time
    price = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    # Strategy info
    strategy = Column(String(50), default="hybrid")

    # Technical indicators snapshot
    rsi = Column(Float, nullable=True)
    macd = Column(Float, nullable=True)
    ema = Column(Float, nullable=True)

    # Full features JSON
    features_json = Column("features", Text, nullable=True)

    # Was this signal acted upon?
    executed = Column(Boolean, default=False)
    trade_id = Column(Integer, ForeignKey("trades.id"), nullable=True)

    # Reason if not executed
    skip_reason = Column(String(100), nullable=True)

    __table_args__ = (
        Index("ix_signals_symbol_time", "symbol", "timestamp"),
    )

    @property
    def features(self) -> Optional[Dict[str, Any]]:
        if self.features_json:
            return JSONEncodedDict.decode(self.features_json)
        return None

    @features.setter
    def features(self, value: Dict[str, Any]):
        self.features_json = JSONEncodedDict.encode(value) if value else None

    def __repr__(self):
        return f"<SignalLog({self.symbol}: {self.signal} @{self.price:.2f})>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert signal log to dictionary."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "signal": self.signal,
            "confidence": self.confidence,
            "price": self.price,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "strategy": self.strategy,
            "rsi": self.rsi,
            "macd": self.macd,
            "ema": self.ema,
            "executed": self.executed,
            "skip_reason": self.skip_reason,
            "features": self.features,
        }


class BacktestResult(Base):
    """
    Store backtest results for comparison and analysis.
    """
    __tablename__ = "backtest_results"

    id = Column(Integer, primary_key=True, index=True)

    # Configuration
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    strategy = Column(String(50), nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)

    # Parameters
    initial_balance = Column(Float, nullable=False)
    risk_per_trade = Column(Float, nullable=False)
    sl_pct = Column(Float, nullable=False)
    tp_ratio = Column(Float, nullable=False)

    # Results
    final_balance = Column(Float, nullable=False)
    total_return_pct = Column(Float, nullable=False)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    profit_factor = Column(Float, default=0.0)
    max_drawdown_pct = Column(Float, default=0.0)
    sharpe_ratio = Column(Float, nullable=True)

    # Additional metrics JSON
    metrics_json = Column("metrics", Text, default="{}")

    # Equity curve (stored as JSON array)
    equity_curve_json = Column("equity_curve", Text, nullable=True)

    # Trades list (stored as JSON)
    trades_json = Column("trades", Text, nullable=True)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def metrics(self) -> Dict[str, Any]:
        return JSONEncodedDict.decode(self.metrics_json)

    @metrics.setter
    def metrics(self, value: Dict[str, Any]):
        self.metrics_json = JSONEncodedDict.encode(value)

    @property
    def equity_curve(self) -> Optional[list]:
        if self.equity_curve_json:
            return json.loads(self.equity_curve_json)
        return None

    @equity_curve.setter
    def equity_curve(self, value: list):
        self.equity_curve_json = json.dumps(value) if value else None

    @property
    def trades(self) -> Optional[list]:
        if self.trades_json:
            return json.loads(self.trades_json)
        return None

    @trades.setter
    def trades(self, value: list):
        self.trades_json = json.dumps(value) if value else None

    def __repr__(self):
        return f"<BacktestResult({self.symbol} {self.strategy}: {self.total_return_pct:.2f}%)>"

    def to_dict(self) -> Dict[str, Any]:
        """Convert backtest result to dictionary."""
        return {
            "id": self.id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "strategy": self.strategy,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "initial_balance": self.initial_balance,
            "final_balance": self.final_balance,
            "total_return_pct": self.total_return_pct,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe_ratio": self.sharpe_ratio,
            "metrics": self.metrics,
            "equity_curve": self.equity_curve,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Configuration(Base):
    """
    Store bot configuration settings.
    """
    __tablename__ = "configurations"

    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Configuration({self.key}: {self.value})>"


# Create indexes for common queries
Index("ix_trades_pnl", Trade.pnl)
Index("ix_trades_strategy", Trade.strategy)
Index("ix_signals_executed", SignalLog.executed)
Index("ix_backtest_symbol_strategy", BacktestResult.symbol, BacktestResult.strategy)
