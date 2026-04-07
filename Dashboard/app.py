"""
Dashboard/app.py - Web dashboard using FastAPI and WebSocket.

Provides a real-time web interface for monitoring the trading bot
with live charts, trade history, and system status.
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

import pandas as pd
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder

# Import bot modules
from ai.data_loader import get_historical_data
from ai.features import create_features
from ai.predict import predict_signal_with_confidence
from Core.execution_ import ExecutionEngine
from Services.broker import get_broker
from Services.data_feed import HistoricalDataService
from Workers.monitor import MonitoringWorker, NotificationService, AlertLevel
from Workers.rader import RadarWorker, RadarConfig
from Database.db import get_db, get_trading_stats
from config import SYMBOL, TIMEFRAME, FEATURES, INITIAL_BALANCE

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot.dashboard")

# Create FastAPI app
app = FastAPI(
    title="AI Trading Bot Dashboard",
    version="1.0.0",
    description="Real-time trading dashboard",
)

# Setup templates and static files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Create static files directory if needed
static_dir = os.path.join(BASE_DIR, "static")
os.makedirs(static_dir, exist_ok=True)
os.makedirs(os.path.join(static_dir, "js"), exist_ok=True)
os.makedirs(os.path.join(static_dir, "css"), exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Global state
class DashboardState:
    """Shared dashboard state."""
    def __init__(self):
        self.monitor: Optional[MonitoringWorker] = None
        self.radar: Optional[RadarWorker] = None
        self.execution_engine: Optional[ExecutionEngine] = None
        self.websocket_clients: List[WebSocket] = []
        self.is_live_mode = False

    def broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connected WebSocket clients."""
        import asyncio

        disconnected = []
        for client in self.websocket_clients:
            try:
                asyncio.create_task(client.send_json(message))
            except Exception:
                disconnected.append(client)

        # Remove disconnected clients
        for client in disconnected:
            if client in self.websocket_clients:
                self.websocket_clients.remove(client)


state = DashboardState()


# === Routes ===

@app.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """Main dashboard page."""
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
    })


@app.get("/api/status")
async def get_status():
    """Get overall system status."""
    broker = get_broker()

    status = {
        "timestamp": datetime.now().isoformat(),
        "is_live": state.is_live_mode,
        "components": {
            "broker": {
                "configured": broker.is_configured(),
                "connected": False,  # Would need actual connection check
            },
            "monitor": {
                "running": state.monitor.is_alive() if state.monitor else False,
            },
            "radar": {
                "running": state.radar.is_alive() if state.radar else False,
            },
        },
    }

    return JSONResponse(status)


@app.get("/api/balance")
async def get_balance():
    """Get current account balance."""
    try:
        broker = get_broker()
        balance_data = broker.get_account_balance("USDT")

        return JSONResponse({
            "asset": "USDT",
            "free": balance_data.get("free", 0.0),
            "locked": balance_data.get("locked", 0.0),
            "total": balance_data.get("total", 0.0),
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error(f"Balance fetch failed: {e}")
        return JSONResponse(
            {"error": str(e)},
            status_code=500
        )


@app.get("/api/signal")
async def get_current_signal(symbol: str = SYMBOL):
    """Get current AI signal for symbol."""
    try:
        df = get_historical_data(symbol=symbol, timeframe=TIMEFRAME, limit=200)
        df = create_features(df)

        latest = df[FEATURES].tail(1)
        signal, confidence = predict_signal_with_confidence(latest)

        return JSONResponse({
            "symbol": symbol,
            "signal": signal,
            "confidence": round(confidence, 4),
            "price": round(df["close"].iloc[-1], 4),
            "rsi": round(df["rsi"].iloc[-1], 2),
            "macd": round(df["macd"].iloc[-1], 6),
            "timestamp": datetime.now().isoformat(),
        })
    except Exception as e:
        logger.error(f"Signal generation failed: {e}")
        return JSONResponse(
            {"error": str(e)},
            status_code=500
        )


@app.get("/api/trades")
async def get_trades(limit: int = 50):
    """Get recent trades."""
    try:
        stats = get_trading_stats(days=30)
        return JSONResponse({
            "stats": stats,
            "limit": limit,
        })
    except Exception as e:
        logger.error(f"Trades fetch failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/radar")
async def get_radar_results():
    """Get latest radar scan results."""
    if state.radar:
        results = state.radar.get_results_dataframe()
        if not results.empty:
            return JSONResponse({
                "results": results.to_dict("records"),
                "last_scan": state.radar.get_status().get("last_scan"),
            })

    # Fallback to on-demand scan
    try:
        from Workers.rader import run_single_scan
        df = run_single_scan(
            symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"],
            timeframe=TIMEFRAME,
        )
        return JSONResponse({
            "results": df.to_dict("records") if not df.empty else [],
            "on_demand": True,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/chart/price")
async def get_price_chart(symbol: str = SYMBOL, limit: int = 100):
    """Get price chart data."""
    try:
        df = get_historical_data(symbol=symbol, timeframe=TIMEFRAME, limit=limit)
        df = create_features(df)

        fig = go.Figure()

        # Candlestick chart
        fig.add_trace(go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Price"
        ))

        # EMAs
        fig.add_trace(go.Scatter(
            x=df.index, y=df["ema"],
            name="EMA 20",
            line=dict(color="orange", width=1)
        ))

        fig.add_trace(go.Scatter(
            x=df.index, y=df["ema50"],
            name="EMA 50",
            line=dict(color="purple", width=1)
        ))

        # Bollinger Bands
        fig.add_trace(go.Scatter(
            x=df.index, y=df["bb_upper"],
            name="BB Upper",
            line=dict(color="gray", dash="dot"),
            showlegend=True,
        ))

        fig.add_trace(go.Scatter(
            x=df.index, y=df["bb_lower"],
            name="BB Lower",
            line=dict(color="gray", dash="dot"),
            fill="tonexty",
            fillcolor="rgba(128,128,128,0.1)",
        ))

        fig.update_layout(
            title=f"{symbol} Price Chart",
            yaxis_title="Price",
            xaxis_title="Time",
            template="plotly_white",
            height=500,
        )

        return JSONResponse(json.loads(fig.to_json()))

    except Exception as e:
        logger.error(f"Chart generation failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# === WebSocket for real-time updates ===

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await websocket.accept()
    state.websocket_clients.append(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                action = message.get("action")

                if action == "get_signal":
                    symbol = message.get("symbol", SYMBOL)
                    df = get_historical_data(symbol=symbol, timeframe=TIMEFRAME, limit=200)
                    df = create_features(df)
                    latest = df[FEATURES].tail(1)
                    signal, confidence = predict_signal_with_confidence(latest)

                    await websocket.send_json({
                        "type": "signal_update",
                        "data": {
                            "symbol": symbol,
                            "signal": signal,
                            "confidence": confidence,
                            "price": df["close"].iloc[-1],
                        }
                    })

                elif action == "start_monitor":
                    if not state.monitor:
                        state.monitor = MonitoringWorker()
                        state.monitor.start()
                        await websocket.send_json({
                            "type": "status",
                            "message": "Monitor started"
                        })

                elif action == "stop_monitor":
                    if state.monitor:
                        state.monitor.stop()
                        state.monitor = None
                        await websocket.send_json({
                            "type": "status",
                            "message": "Monitor stopped"
                        })

            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON"
                })

    except WebSocketDisconnect:
        state.websocket_clients.remove(websocket)
        logger.info("WebSocket client disconnected")


# === HTML Template (inline for simplicity) ===

TEMPLATE_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AI Trading Bot Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
    <style>
        .signal-buy { background-color: #10b981; }
        .signal-sell { background-color: #ef4444; }
        .signal-hold { background-color: #6b7280; }
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    <div class="container mx-auto px-4 py-6">
        <!-- Header -->
        <header class="bg-white rounded-lg shadow-md p-6 mb-6">
            <div class="flex justify-between items-center">
                <div>
                    <h1 class="text-3xl font-bold text-gray-800">🤖 AI Trading Bot</h1>
                    <p class="text-gray-600 mt-1">{{ symbol }} | {{ timeframe }}</p>
                </div>
                <div class="flex gap-3">
                    <span id="connection-status" class="px-3 py-1 bg-yellow-100 text-yellow-800 rounded-full text-sm">
                        Connecting...
                    </span>
                    <button onclick="refreshAll()" class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
                        Refresh
                    </button>
                </div>
            </div>
        </header>

        <!-- Stats Grid -->
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
            <!-- Balance Card -->
            <div class="bg-white rounded-lg shadow-md p-6">
                <div class="flex items-center justify-between">
                    <div>
                        <p class="text-gray-500 text-sm">Balance (USDT)</p>
                        <p id="balance-value" class="text-2xl font-bold text-gray-800">--</p>
                    </div>
                    <i data-lucide="wallet" class="w-8 h-8 text-blue-500"></i>
                </div>
            </div>

            <!-- Current Signal Card -->
            <div class="bg-white rounded-lg shadow-md p-6">
                <div class="flex items-center justify-between">
                    <div>
                        <p class="text-gray-500 text-sm">Current Signal</p>
                        <p id="signal-value" class="text-2xl font-bold text-gray-800">--</p>
                    </div>
                    <i data-lucide="activity" class="w-8 h-8 text-purple-500"></i>
                </div>
                <p id="signal-confidence" class="text-sm text-gray-500 mt-2">Confidence: --</p>
            </div>

            <!-- Win Rate Card -->
            <div class="bg-white rounded-lg shadow-md p-6">
                <div class="flex items-center justify-between">
                    <div>
                        <p class="text-gray-500 text-sm">Win Rate</p>
                        <p id="winrate-value" class="text-2xl font-bold text-gray-800">--</p>
                    </div>
                    <i data-lucide="trending-up" class="w-8 h-8 text-green-500"></i>
                </div>
            </div>

            <!-- Active Trades Card -->
            <div class="bg-white rounded-lg shadow-md p-6">
                <div class="flex items-center justify-between">
                    <div>
                        <p class="text-gray-500 text-sm">Total Trades</p>
                        <p id="trades-value" class="text-2xl font-bold text-gray-800">--</p>
                    </div>
                    <i data-lucide="bar-chart-2" class="w-8 h-8 text-orange-500"></i>
                </div>
            </div>
        </div>

        <!-- Charts Row -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            <!-- Price Chart -->
            <div class="bg-white rounded-lg shadow-md p-6">
                <h2 class="text-xl font-bold text-gray-800 mb-4">Price Chart</h2>
                <div id="price-chart" style="height: 400px;"></div>
            </div>

            <!-- Radar Results -->
            <div class="bg-white rounded-lg shadow-md p-6">
                <h2 class="text-xl font-bold text-gray-800 mb-4">Market Radar</h2>
                <div id="radar-results" class="overflow-auto">
                    <table class="w-full text-sm">
                        <thead class="bg-gray-50">
                            <tr>
                                <th class="px-4 py-2 text-left">Symbol</th>
                                <th class="px-4 py-2 text-left">Signal</th>
                                <th class="px-4 py-2 text-left">Conf</th>
                                <th class="px-4 py-2 text-left">Price</th>
                            </tr>
                        </thead>
                        <tbody id="radar-table-body">
                            <tr><td colspan="4" class="text-center py-4 text-gray-500">Loading...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Controls -->
        <div class="bg-white rounded-lg shadow-md p-6 mb-6">
            <h2 class="text-xl font-bold text-gray-800 mb-4">Controls</h2>
            <div class="flex gap-4">
                <button onclick="startMonitor()" class="px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700">
                    Start Monitor
                </button>
                <button onclick="stopMonitor()" class="px-6 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700">
                    Stop Monitor
                </button>
                <button onclick="scanRadar()" class="px-6 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700">
                    Scan Market
                </button>
            </div>
        </div>
    </div>

    <script>
        let ws;
        let priceChart;

        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            lucide.createIcons();
            connectWebSocket();
            loadInitialData();
        });

        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

            ws.onopen = () => {
                document.getElementById('connection-status').textContent = 'Connected';
                document.getElementById('connection-status').className = 'px-3 py-1 bg-green-100 text-green-800 rounded-full text-sm';
            };

            ws.onclose = () => {
                document.getElementById('connection-status').textContent = 'Disconnected';
                document.getElementById('connection-status').className = 'px-3 py-1 bg-red-100 text-red-800 rounded-full text-sm';
                setTimeout(connectWebSocket, 5000);
            };

            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                handleWebSocketMessage(msg);
            };
        }

        function handleWebSocketMessage(msg) {
            if (msg.type === 'signal_update') {
                updateSignalDisplay(msg.data);
            } else if (msg.type === 'status') {
                showNotification(msg.message);
            }
        }

        async function loadInitialData() {
            await Promise.all([
                loadBalance(),
                loadSignal(),
                loadTrades(),
                loadPriceChart(),
                loadRadar(),
            ]);
        }

        async function loadBalance() {
            try {
                const res = await fetch('/api/balance');
                const data = await res.json();
                if (data.total !== undefined) {
                    document.getElementById('balance-value').textContent = `$${data.total.toFixed(2)}`;
                }
            } catch (e) {
                console.error('Failed to load balance:', e);
            }
        }

        async function loadSignal() {
            try {
                const res = await fetch('/api/signal');
                const data = await res.json();
                updateSignalDisplay(data);
            } catch (e) {
                console.error('Failed to load signal:', e);
            }
        }

        function updateSignalDisplay(data) {
            const signalEl = document.getElementById('signal-value');
            signalEl.textContent = data.signal || '--';
            signalEl.className = `text-2xl font-bold ${
                data.signal === 'BUY' ? 'text-green-600' :
                data.signal === 'SELL' ? 'text-red-600' : 'text-gray-600'
            }`;
            document.getElementById('signal-confidence').textContent =
                `Confidence: ${(data.confidence * 100).toFixed(1)}%`;
        }

        async function loadTrades() {
            try {
                const res = await fetch('/api/trades');
                const data = await res.json();
                if (data.stats) {
                    document.getElementById('winrate-value').textContent =
                        `${data.stats.win_rate?.toFixed(1) || 0}%`;
                    document.getElementById('trades-value').textContent =
                        data.stats.total_trades || 0;
                }
            } catch (e) {
                console.error('Failed to load trades:', e);
            }
        }

        async function loadPriceChart() {
            try {
                const res = await fetch('/api/chart/price');
                const data = await res.json();
                if (!data.error) {
                    Plotly.newPlot('price-chart', data.data, data.layout);
                }
            } catch (e) {
                console.error('Failed to load chart:', e);
            }
        }

        async function loadRadar() {
            try {
                const res = await fetch('/api/radar');
                const data = await res.json();
                updateRadarTable(data.results || []);
            } catch (e) {
                console.error('Failed to load radar:', e);
            }
        }

        function updateRadarTable(results) {
            const tbody = document.getElementById('radar-table-body');
            if (results.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" class="text-center py-4 text-gray-500">No signals</td></tr>';
                return;
            }

            tbody.innerHTML = results.map(r => `
                <tr class="border-b hover:bg-gray-50">
                    <td class="px-4 py-2 font-medium">${r.symbol}</td>
                    <td class="px-4 py-2">
                        <span class="px-2 py-1 rounded text-white text-xs ${
                            r.signal === 'BUY' ? 'bg-green-500' :
                            r.signal === 'SELL' ? 'bg-red-500' : 'bg-gray-500'
                        }">${r.signal}</span>
                    </td>
                    <td class="px-4 py-2">${(r.confidence * 100).toFixed(1)}%</td>
                    <td class="px-4 py-2">$${r.price?.toFixed(4) || '--'}</td>
                </tr>
            `).join('');
        }

        function startMonitor() {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ action: 'start_monitor' }));
            }
        }

        function stopMonitor() {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ action: 'stop_monitor' }));
            }
        }

        function scanRadar() {
            loadRadar();
            showNotification('Market scan initiated');
        }

        function refreshAll() {
            loadInitialData();
            showNotification('Data refreshed');
        }

        function showNotification(message) {
            // Simple notification - could be enhanced with toast library
            console.log('Notification:', message);
        }

        // Auto-refresh every 60 seconds
        setInterval(refreshAll, 60000);
    </script>
</body>
</html>
'''


# Write template file on startup
@app.on_event("startup")
async def startup_event():
    """Create template files on startup."""
    template_dir = os.path.join(BASE_DIR, "templates")
    os.makedirs(template_dir, exist_ok=True)

    template_path = os.path.join(template_dir, "dashboard.html")
    if not os.path.exists(template_path):
        with open(template_path, "w") as f:
            f.write(TEMPLATE_HTML)
        logger.info(f"Created template: {template_path}")


# Main entry point
if __name__ == "__main__":
    uvicorn.run(
        "Dashboard.app:app",
        host="0.0.0.0",
        port=8502,
        reload=True,
    )
