"""
main.py — FastAPI REST API

Endpoints:
    GET  /           → health check
    GET  /signal     → current AI signal for a symbol
    GET  /balance    → live USDT balance
    POST /train      → trigger model retraining
    GET  /radar      → market radar scan
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd

from ai.data_loader import get_historical_data
from ai.features import create_features
from ai.predict import predict_signal_with_confidence, reload_model
from ai.train import train
from live.broker import get_account_balance
from rader import scan_market
from config import SYMBOL, TIMEFRAME, FEATURES

app = FastAPI(
    title="AI Trading Bot API",
    version="1.0.0",
    description="REST API for the AI Trading Bot"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/")
def health():
    return {"status": "✅ AI Trading Bot Running", "version": "1.0.0"}


@app.get("/signal")
def get_signal(
    symbol:    str = Query(default=SYMBOL),
    timeframe: str = Query(default=TIMEFRAME),
    limit:     int = Query(default=200)
):
    """Get the current AI trading signal for a symbol."""
    try:
        df = get_historical_data(symbol=symbol, timeframe=timeframe, limit=limit)
        df = create_features(df)
        latest = df[FEATURES].tail(1)
        signal, confidence = predict_signal_with_confidence(latest)
        return {
            "symbol":     symbol,
            "timeframe":  timeframe,
            "signal":     signal,
            "confidence": round(confidence, 4),
            "rsi":        round(float(df["rsi"].iloc[-1]), 2),
            "macd":       round(float(df["macd"].iloc[-1]), 6),
            "close":      round(float(df["close"].iloc[-1]), 4),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/balance")
def get_balance():
    """Get the current USDT balance."""
    try:
        balance = get_account_balance("USDT")
        return {"asset": "USDT", "balance": balance}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/train")
def retrain():
    """Trigger model retraining and reload."""
    try:
        train()
        reload_model()
        return {"status": "✅ Model retrained and reloaded"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/radar")
def radar(
    timeframe: str = Query(default="15m"),
    limit:     int = Query(default=200)
):
    """Scan the market watchlist and return signals."""
    try:
        df = scan_market(timeframe=timeframe, limit=limit)
        return {"results": df.to_dict(orient="records")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
