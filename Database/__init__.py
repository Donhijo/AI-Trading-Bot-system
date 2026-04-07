"""
Database module - Database management and ORM models.

Provides SQLAlchemy-based database connectivity for:
- Trade logging
- Order history
- Performance tracking
- Strategy backtest results
"""

from Database.db import DatabaseManager, get_db
from Database.models import (
    Base,
    Trade,
    Order,
    BalanceSnapshot,
    SignalLog,
    BacktestResult,
)

__all__ = [
    "DatabaseManager",
    "get_db",
    "Base",
    "Trade",
    "Order",
    "BalanceSnapshot",
    "SignalLog",
    "BacktestResult",
]
