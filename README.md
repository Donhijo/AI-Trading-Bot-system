# 🤖 AI Trading Bot

XGBoost-powered crypto trading bot with live Binance execution, backtesting, Streamlit dashboard, and FastAPI REST interface.

---

## 📁 Project Structure

```
trading_bot/
├── ai/
│   ├── data_loader.py      # Fetch OHLCV from Binance
│   ├── features.py         # RSI, MACD, EMA, Bollinger, returns
│   ├── labels.py           # Create BUY/HOLD/SELL target labels
│   ├── models.py           # XGBoost train/load/predict
│   ├── predict.py          # predict_signal() with confidence
│   └── train.py            # Training pipeline script
│
├── backtest/
│   ├── engine.py           # Backtester class (SL/TP/fees/slippage/latency)
│   ├── backtester.py       # Re-export convenience wrapper
│   ├── strategy_wrapper.py # AI model as backtest strategy function
│
├── live/
│   ├── broker.py           # Binance REST order placement
│   ├── data_feed.py        # WebSocket live kline feed
│   ├── execution_.py       # Full execution pipeline with risk checks
│   ├── monitor.py          # Logging + Telegram alerts
│   ├── risk.py             # Position sizing, SL/TP, drawdown check
│   └── strategy.py         # Rule-based + hybrid strategy
│
├── bot.py                  # 🔴 Main live trading loop
├── run.py                  # 🔁 Run backtest
├── rader.py                # 📡 Market radar scanner
├── app.py                  # 📊 Streamlit dashboard
├── main.py                 # 🌐 FastAPI REST API
├── config.py               # ⚙️  Central configuration
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## 🚀 Quick Start

### 1. Clone & configure
```bash
cp .env.example .env
# Edit .env with your Binance API keys
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Train the model
```bash
python ai/train.py
```

### 4. Run a backtest
```bash
python run.py
```

### 5. Launch the dashboard
```bash
streamlit run app.py
```

### 6. Scan the market
```bash
python rader.py --timeframe 15m
```

### 7. Start the live bot
```bash
python bot.py
```

---

## 🐳 Docker

```bash
docker-compose up --build
```

| Service    | URL                    |
|------------|------------------------|
| Bot        | (background)           |
| API        | http://localhost:8000  |
| Dashboard  | http://localhost:8501  |

---

## 🌐 REST API Endpoints

| Method | Endpoint   | Description                    |
|--------|------------|--------------------------------|
| GET    | /          | Health check                   |
| GET    | /signal    | Current AI signal for symbol   |
| GET    | /balance   | Live USDT balance              |
| POST   | /train     | Retrain & reload model         |
| GET    | /radar     | Market radar scan              |

---

## ⚠️ Disclaimer

This bot is for **educational purposes only**. Crypto trading involves significant risk. Never trade with money you cannot afford to lose.
