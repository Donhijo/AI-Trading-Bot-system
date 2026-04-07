"""
api/main.py - Full REST API for the trading bot.

Provides comprehensive API endpoints for:
- Signal generation
- Account management
- Trade execution
- Backtesting
- System monitoring
- Configuration
"""
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, Query, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

import pandas as pd
import uvicorn

# Bot modules
from ai.data_loader import get_historical_data
from ai.features import create_features
from ai.labels import create_target
from ai.train import train
from ai.models import train_model, load_model
from ai.predict import predict_signal_with_confidence, reload_model

from backtest.engine import Backtester
from backtest.strategy_wrapper import ai_strategy

from Core.execution_ import ExecutionEngine
from Core.risk import RiskManager, RiskParameters
from Core.strategy import create_strategy

from Services.broker import get_broker, BinanceBroker
from Services.data_feed import HistoricalDataService

from Workers.rader import RadarWorker, RadarConfig, run_single_scan
from Workers.monitor import MonitoringWorker, NotificationService

from Database.db import get_db, log_trade, log_signal, get_trading_stats
from Database.models import Trade, SignalLog, BacktestResult

from live.broker import get_account_balance, place_order
from rader import scan_market

from config import (
    SYMBOL, TIMEFRAME, FEATURES,
    INITIAL_BALANCE, RISK_PER_TRADE, SL_PCT, TP_RATIO,
    BINANCE_API_KEY, BINANCE_SECRET_KEY,
)

# === API Models ===

class SignalResponse(BaseModel):
    symbol: str
    timeframe: str
    signal: str
    confidence: float
    price: float
    rsi: Optional[float]
    macd: Optional[float]
    timestamp: str

    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "BTCUSDT",
                "timeframe": "15m",
                "signal": "BUY",
                "confidence": 0.75,
                "price": 45000.50,
                "rsi": 45.2,
                "macd": 0.0015,
                "timestamp": "2024-01-01T12:00:00"
            }
        }


class BalanceResponse(BaseModel):
    asset: str
    free: float
    locked: float
    total: float
    timestamp: str


class TradeRequest(BaseModel):
    symbol: str = Field(default=SYMBOL, description="Trading pair")
    side: str = Field(..., description="BUY or SELL", pattern="^(BUY|SELL)$")
    quantity: float = Field(..., gt=0, description="Amount to trade")
    order_type: str = Field(default="MARKET", description="MARKET or LIMIT")
    price: Optional[float] = Field(None, description="Limit price (required for LIMIT)")
    test: bool = Field(default=False, description="Test order without execution")


class BacktestRequest(BaseModel):
    symbol: str = Field(default=SYMBOL)
    timeframe: str = Field(default=TIMEFRAME)
    limit: int = Field(default=1000, ge=100, le=5000)
    initial_balance: float = Field(default=INITIAL_BALANCE)
    risk_per_trade: float = Field(default=RISK_PER_TRADE)
    sl_pct: float = Field(default=SL_PCT)
    tp_ratio: float = Field(default=TP_RATIO)


class BacktestResponse(BaseModel):
    final_balance: float
    profit: float
    profit_pct: float
    total_trades: int
    win_rate: float
    wins: int
    losses: int
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_drawdown: float


class RadarRequest(BaseModel):
    symbols: List[str] = Field(default_factory=lambda: [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"
    ])
    timeframe: str = Field(default=TIMEFRAME)
    min_confidence: float = Field(default=0.5, ge=0, le=1)


class TrainingRequest(BaseModel):
    symbol: str = Field(default=SYMBOL)
    timeframe: str = Field(default=TIMEFRAME)
    limit: int = Field(default=2000, ge=100, le=10000)
    force: bool = Field(default=False, description="Force retrain even if model exists")


class TrainingResponse(BaseModel):
    success: bool
    message: str
    model_path: Optional[str]
    training_time: Optional[float]


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: str
    components: Dict[str, Any]


# === FastAPI App ===

app = FastAPI(
    title="AI Trading Bot API",
    description="REST API for AI-powered cryptocurrency trading bot",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Endpoints ===

@app.get("/", response_model=HealthResponse)
def health_check():
    """Health check endpoint."""
    broker = get_broker()

    return HealthResponse(
        status="operational",
        version="1.0.0",
        timestamp=datetime.now().isoformat(),
        components={
            "broker": {
                "configured": broker.is_configured(),
            },
            "api": {
                "status": "running",
            },
        },
    )


@app.get("/signal", response_model=SignalResponse)
def get_signal(
    symbol: str = Query(default=SYMBOL, description="Trading pair symbol"),
    timeframe: str = Query(default=TIMEFRAME, description="Candle timeframe"),
    limit: int = Query(default=200, ge=50, le=1000, description="Number of candles to analyze"),
):
    """
    Get current AI trading signal for a symbol.

    Returns BUY, SELL, or HOLD signal with confidence score and technical indicators.
    """
    try:
        df = get_historical_data(symbol=symbol, timeframe=timeframe, limit=limit)
        df = create_features(df)

        latest = df[FEATURES].tail(1)
        signal, confidence = predict_signal_with_confidence(latest)

        # Log signal to database
        log_signal(symbol, signal, confidence, float(df["close"].iloc[-1]))

        return SignalResponse(
            symbol=symbol,
            timeframe=timeframe,
            signal=signal,
            confidence=round(confidence, 4),
            price=round(float(df["close"].iloc[-1]), 4),
            rsi=round(float(df["rsi"].iloc[-1]), 2) if "rsi" in df else None,
            macd=round(float(df["macd"].iloc[-1]), 6) if "macd" in df else None,
            timestamp=datetime.now().isoformat(),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/balance", response_model=BalanceResponse)
def get_balance(asset: str = Query(default="USDT", description="Asset to check")):
    """
    Get current account balance for specified asset.
    """
    try:
        broker = get_broker()
        balance_data = broker.get_account_balance(asset)

        return BalanceResponse(
            asset=asset,
            free=balance_data.get("free", 0.0),
            locked=balance_data.get("locked", 0.0),
            total=balance_data.get("total", 0.0),
            timestamp=datetime.now().isoformat(),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/trade")
def execute_trade(request: TradeRequest):
    """
    Execute a trade order.

    Places a market or limit order on the exchange.
    Set test=True to simulate without actual execution.
    """
    try:
        broker = get_broker()

        if not broker.is_configured():
            raise HTTPException(status_code=400, detail="Broker not configured")

        # Execute order
        result = broker.place_order(
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            price=request.price,
            test=request.test,
        )

        return {
            "success": True,
            "test": request.test,
            "order": result,
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/backtest", response_model=BacktestResponse)
def run_backtest(request: BacktestRequest):
    """
    Run a backtest with the AI strategy.

    Simulates trading over historical data and returns performance metrics.
    """
    try:
        # Fetch data
        df = get_historical_data(
            symbol=request.symbol,
            timeframe=request.timeframe,
            limit=request.limit,
        )

        df = create_features(df)
        df = create_target(df)
        df = df.reset_index(drop=True)

        # Run backtest
        bt = Backtester(
            df,
            initial_balance=request.initial_balance,
            risk_per_trade=request.risk_per_trade,
            sl_pct=request.sl_pct,
            tp_ratio=request.tp_ratio,
        )

        results = bt.run(ai_strategy)

        return BacktestResponse(
            final_balance=results["final_balance"],
            profit=results["profit"],
            profit_pct=results["profit_pct"],
            total_trades=results["trades"],
            win_rate=results["win_rate"],
            wins=results["wins"],
            losses=results["losses"],
            avg_win=results["avg_win"],
            avg_loss=results["avg_loss"],
            profit_factor=results["profit_factor"],
            max_drawdown=results["max_drawdown"],
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/radar")
def get_radar(
    timeframe: str = Query(default=TIMEFRAME),
    limit: int = Query(default=200),
):
    """
    Scan market watchlist and return signals for all pairs.
    """
    try:
        results = scan_market(timeframe=timeframe, limit=limit)
        return {
            "timeframe": timeframe,
            "pairs_analyzed": len(results),
            "timestamp": datetime.now().isoformat(),
            "results": results.to_dict(orient="records"),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/radar/scan")
def radar_scan(request: RadarRequest):
    """
    Run on-demand market radar scan for specified symbols.
    """
    try:
        df = run_single_scan(
            symbols=request.symbols,
            timeframe=request.timeframe,
        )

        # Filter by confidence
        if not df.empty:
            df = df[df["confidence"] >= request.min_confidence]

        return {
            "symbols_scanned": len(request.symbols),
            "min_confidence": request.min_confidence,
            "timestamp": datetime.now().isoformat(),
            "results": df.to_dict("records") if not df.empty else [],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/train", response_model=TrainingResponse)
def train_model_endpoint(request: TrainingRequest):
    """
    Trigger model retraining.

    Fetches fresh data and retrains the XGBoost model.
    """
    import time
    start_time = time.time()

    try:
        # Check if model exists and we're not forcing
        from config import MODEL_PATH
        if os.path.exists(MODEL_PATH) and not request.force:
            return TrainingResponse(
                success=True,
                message="Model already exists. Use force=True to retrain.",
                model_path=MODEL_PATH,
                training_time=0,
            )

        # Fetch data
        df = get_historical_data(
            symbol=request.symbol,
            timeframe=request.timeframe,
            limit=request.limit,
        )

        df = create_features(df)
        df = create_target(df)

        # Train model
        model = train_model(df)

        # Reload model in memory
        reload_model()

        elapsed = time.time() - start_time

        return TrainingResponse(
            success=True,
            message="Model trained successfully",
            model_path=MODEL_PATH,
            training_time=round(elapsed, 2),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stats")
def get_stats(days: int = Query(default=30, ge=1, le=365)):
    """
    Get trading statistics for the specified period.
    """
    try:
        stats = get_trading_stats(days=days)
        return {
            "period_days": days,
            "timestamp": datetime.now().isoformat(),
            "stats": stats,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/history/price")
def get_price_history(
    symbol: str = Query(default=SYMBOL),
    timeframe: str = Query(default=TIMEFRAME),
    limit: int = Query(default=500, ge=10, le=1000),
):
    """
    Get historical price data.
    """
    try:
        df = get_historical_data(symbol=symbol, timeframe=timeframe, limit=limit)
        df = create_features(df)

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(df),
            "data": [
                {
                    "timestamp": idx.isoformat(),
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row["volume"],
                    "rsi": row.get("rsi"),
                    "macd": row.get("macd"),
                    "ema": row.get("ema"),
                }
                for idx, row in df.iterrows()
            ],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    return {
        "error": str(exc),
        "timestamp": datetime.now().isoformat(),
    }


# Main entry point
if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
