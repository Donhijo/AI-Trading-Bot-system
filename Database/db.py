"""
Database/db.py - Database connection and session management.

Provides SQLAlchemy engine creation, session management, and
convenience functions for database operations.
"""
import os
import logging
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

from Database.models import Base

logger = logging.getLogger("bot.database")

# Default database URL - can be overridden via environment
DEFAULT_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://trader:password@localhost:5432/trading_bot"
)


class DatabaseManager:
    """
    Central database manager for the trading bot.

    Handles connection pooling, session management, and schema creation.
    """

    _instance: Optional["DatabaseManager"] = None
    _engine = None
    _SessionLocal = None

    def __new__(cls, database_url: str = None):
        """Singleton pattern to ensure single database connection pool."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init(database_url or DEFAULT_DATABASE_URL)
        return cls._instance

    def _init(self, database_url: str):
        """Initialize the database engine and session factory."""
        self.database_url = database_url

        # Create engine with connection pooling
        self._engine = create_engine(
            database_url,
            poolclass=QueuePool,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,  # Verify connections before use
            pool_recycle=3600,   # Recycle connections after 1 hour
        )

        # Add event listeners for debugging
        if os.getenv("DB_DEBUG", "false").lower() == "true":
            event.listen(self._engine, "connect", self._on_connect)
            event.listen(self._engine, "checkout", self._on_checkout)

        self._SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self._engine
        )

        logger.info("Database manager initialized")

    @staticmethod
    def _on_connect(dbapi_conn, connection_record):
        """Callback on new connection."""
        logger.debug("New database connection established")

    @staticmethod
    def _on_checkout(dbapi_conn, connection_record, connection_proxy):
        """Callback on connection checkout."""
        logger.debug("Database connection checked out")

    def create_tables(self):
        """Create all tables defined in models."""
        Base.metadata.create_all(bind=self._engine)
        logger.info("Database tables created")

    def drop_tables(self):
        """Drop all tables - use with caution!"""
        Base.metadata.drop_all(bind=self._engine)
        logger.warning("Database tables dropped")

    def get_session(self) -> Session:
        """Get a new database session."""
        return self._SessionLocal()

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """
        Provide a transactional scope around a series of operations.

        Usage:
            with db.session_scope() as session:
                session.add(trade)
                # Automatically committed or rolled back
        """
        session = self._SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database transaction failed: {e}")
            raise
        finally:
            session.close()

    def close(self):
        """Close all database connections."""
        if self._engine:
            self._engine.dispose()
            logger.info("Database connections closed")


# Global instance getter
def get_db(database_url: str = None) -> DatabaseManager:
    """
    Get the database manager instance.

    Args:
        database_url: Optional database URL override

    Returns:
        DatabaseManager instance
    """
    return DatabaseManager(database_url)


# FastAPI dependency
def get_db_session() -> Generator[Session, None, None]:
    """
    FastAPI dependency for database sessions.

    Usage in FastAPI:
        @app.get("/trades")
        def get_trades(db: Session = Depends(get_db_session)):
            return db.query(Trade).all()
    """
    db = DatabaseManager().get_session()
    try:
        yield db
    finally:
        db.close()


# Convenience functions for common operations
def init_database(database_url: str = None):
    """
    Initialize the database - create tables and connections.

    Call this at application startup.
    """
    db = get_db(database_url)
    db.create_tables()
    return db


def log_trade(
    symbol: str,
    side: str,
    entry_price: float,
    exit_price: float,
    quantity: float,
    pnl: float,
    pnl_pct: float,
    **kwargs
):
    """Log a trade to the database."""
    from Database.models import Trade

    db = get_db()
    with db.session_scope() as session:
        trade = Trade(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            **kwargs
        )
        session.add(trade)
        logger.info(f"Trade logged: {side} {symbol} PnL: ${pnl:.2f}")


def log_signal(
    symbol: str,
    signal: str,
    confidence: float,
    price: float,
    features: dict = None,
):
    """Log a signal to the database."""
    from Database.models import SignalLog

    db = get_db()
    with db.session_scope() as session:
        log = SignalLog(
            symbol=symbol,
            signal=signal,
            confidence=confidence,
            price=price,
            features=features,
        )
        session.add(log)


def save_balance_snapshot(balance: float, asset: str = "USDT"):
    """Save a balance snapshot."""
    from Database.models import BalanceSnapshot

    db = get_db()
    with db.session_scope() as session:
        snapshot = BalanceSnapshot(balance=balance, asset=asset)
        session.add(snapshot)


# Alias for backward compatibility
log_balance_snapshot = save_balance_snapshot


def get_recent_trades(limit: int = 100):
    """Get recent trades from database."""
    from Database.models import Trade

    db = get_db()
    with db.session_scope() as session:
        return (
            session.query(Trade)
            .order_by(Trade.exit_time.desc())
            .limit(limit)
            .all()
        )


def get_trading_stats(days: int = 30) -> dict:
    """
    Get trading statistics for the specified period.

    Returns:
        Dictionary with trading statistics
    """
    from Database.models import Trade
    from sqlalchemy import func
    from datetime import datetime, timedelta

    db = get_db()
    with db.session_scope() as session:
        start_date = datetime.utcnow() - timedelta(days=days)

        trades = (
            session.query(Trade)
            .filter(Trade.entry_time >= start_date)
            .all()
        )

        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "avg_pnl": 0,
            }

        total = len(trades)
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        total_pnl = sum(t.pnl for t in trades)

        return {
            "total_trades": total,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": len(wins) / total * 100,
            "total_pnl": total_pnl,
            "avg_pnl": total_pnl / total,
            "best_trade": max(t.pnl for t in wins) if wins else 0,
            "worst_trade": min(t.pnl for t in losses) if losses else 0,
        }
