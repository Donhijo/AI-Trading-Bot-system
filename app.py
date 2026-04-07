"""
app.py — Streamlit Dashboard for AI Trading Bot.

Run with:
    streamlit run app.py
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import time

from ai.data_loader import get_historical_data
from ai.features import create_features
from ai.labels import create_target
from ai.predict import predict_signal_with_confidence
from backtest.engine import Backtester
from backtest.strategy_wrapper import ai_strategy
from rader import scan_market
from config import SYMBOL, TIMEFRAME, FEATURES, INITIAL_BALANCE

# ── Page Config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Trading Bot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Sidebar ────────────────────────────────────────────────────────────────────
st.sidebar.title("⚙️ Settings")
symbol    = st.sidebar.text_input("Symbol",    value=SYMBOL)
timeframe = st.sidebar.selectbox("Timeframe", ["1m","5m","15m","1h","4h","1d"], index=2)
limit     = st.sidebar.slider("Candles",      100, 1000, 500, step=100)
tab       = st.sidebar.radio("View", ["📊 Live Signal", "🔁 Backtest", "📡 Radar"])

st.sidebar.markdown("---")
st.sidebar.caption("🤖 AI Trading Bot v1.0")


# ── Data loader (cached) ───────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def load_data(sym, tf, lim):
    df = get_historical_data(symbol=sym, timeframe=tf, limit=lim)
    return create_features(df)


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 1 — Live Signal
# ══════════════════════════════════════════════════════════════════════════════
if tab == "📊 Live Signal":
    st.title(f"📊 Live Signal — {symbol} {timeframe}")

    with st.spinner("Loading data..."):
        df = load_data(symbol, timeframe, limit)

    # ── Signal ─────────────────────────────────────────────────────────────────
    latest      = df[FEATURES].tail(1)
    signal, conf = predict_signal_with_confidence(latest)

    col1, col2, col3, col4 = st.columns(4)
    icon = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(signal, "❓")
    col1.metric("Signal",      f"{icon} {signal}")
    col2.metric("Confidence",  f"{conf:.1%}")
    col3.metric("RSI",         f"{df['rsi'].iloc[-1]:.1f}")
    col4.metric("Close Price", f"${df['close'].iloc[-1]:,.4f}")

    # ── Candlestick Chart ──────────────────────────────────────────────────────
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name="Price"
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["ema"], name="EMA 20",
        line=dict(color="orange", width=1.5)
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["ema50"], name="EMA 50",
        line=dict(color="purple", width=1.5)
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["bb_upper"], name="BB Upper",
        line=dict(color="gray", dash="dot", width=1)
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["bb_lower"], name="BB Lower",
        line=dict(color="gray", dash="dot", width=1),
        fill="tonexty", fillcolor="rgba(128,128,128,0.05)"
    ))
    fig.update_layout(
        height=450, xaxis_rangeslider_visible=False,
        template="plotly_dark", margin=dict(l=0, r=0, t=30, b=0)
    )
    st.plotly_chart(fig, width='stretch')

    # ── RSI + MACD ─────────────────────────────────────────────────────────────
    c1, c2 = st.columns(2)
    with c1:
        fig_rsi = px.line(df.tail(100), y="rsi", title="RSI (14)",
                          template="plotly_dark")
        fig_rsi.add_hline(y=70, line_dash="dash", line_color="red",   annotation_text="OB 70")
        fig_rsi.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="OS 30")
        fig_rsi.update_layout(height=250, margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig_rsi, use_container_width=True)
    with c2:
        fig_macd = go.Figure()
        tail = df.tail(100)
        fig_macd.add_trace(go.Scatter(y=tail["macd"],        name="MACD",   line=dict(color="cyan")))
        fig_macd.add_trace(go.Scatter(y=tail["macd_signal"], name="Signal", line=dict(color="orange")))
        fig_macd.add_trace(go.Bar(y=tail["macd_diff"], name="Histogram",
                                  marker_color=["green" if v >= 0 else "red"
                                                for v in tail["macd_diff"]]))
        fig_macd.update_layout(title="MACD", height=250, template="plotly_dark",
                                margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig_macd, use_container_width=True)

    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 2 — Backtest
# ══════════════════════════════════════════════════════════════════════════════
elif tab == "🔁 Backtest":
    st.title("🔁 Backtest Results")

    col1, col2, col3 = st.columns(3)
    init_bal   = col1.number_input("Initial Balance ($)", 100, 100000, int(INITIAL_BALANCE))
    risk_pct   = col2.slider("Risk per Trade (%)", 0.5, 10.0, 2.0, step=0.5) / 100
    sl_pct     = col3.slider("Stop-Loss (%)", 0.5, 5.0, 2.0, step=0.25) / 100
    tp_ratio   = st.slider("TP Ratio (R:R)", 1.0, 5.0, 2.0, step=0.5)

    if st.button("▶️  Run Backtest"):
        with st.spinner("Running backtest..."):
            df = load_data(symbol, timeframe, limit)
            df = create_target(df)
            df = df.reset_index(drop=True)

            bt = Backtester(df, init_bal, risk_pct, sl_pct, tp_ratio)
            res = bt.run(ai_strategy)

        # ── Metrics ────────────────────────────────────────────────────────────
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Final Balance", f"${res['final_balance']:,.2f}",
                  f"{res['profit_pct']:+.2f}%")
        m2.metric("Net Profit",    f"${res['profit']:+,.2f}")
        m3.metric("Win Rate",      f"{res['win_rate']:.1f}%")
        m4.metric("Profit Factor", f"{res['profit_factor']:.2f}")
        m5.metric("Max Drawdown",  f"{res['max_drawdown']:.1f}%")

        st.markdown("---")
        c1, c2 = st.columns(2)
        c1.metric("Total Trades", res["trades"])
        c1.metric("Wins",         res["wins"])
        c1.metric("Losses",       res["losses"])
        c2.metric("Avg Win",      f"${res['avg_win']:,.4f}")
        c2.metric("Avg Loss",     f"${res['avg_loss']:,.4f}")

        # ── Equity Curve ───────────────────────────────────────────────────────
        eq_df = pd.DataFrame({"Balance": res["equity_curve"]})
        fig = px.area(eq_df, y="Balance", title="Equity Curve",
                      template="plotly_dark", color_discrete_sequence=["royalblue"])
        fig.add_hline(y=init_bal, line_dash="dash", line_color="gray",
                      annotation_text="Starting Balance")
        fig.update_layout(height=380, margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig, width='stretch')


# ══════════════════════════════════════════════════════════════════════════════
#  TAB 3 — Market Radar
# ══════════════════════════════════════════════════════════════════════════════
elif tab == "📡 Radar":
    st.title("📡 Market Radar")
    st.caption("Scans top pairs and ranks by AI signal strength")

    if st.button("🔍 Scan Market"):
        with st.spinner("Scanning pairs..."):
            radar_df = scan_market(timeframe=timeframe, limit=200)

        def color_signal(val):
            colors = {"BUY": "color: #00cc66", "SELL": "color: #ff4444", "HOLD": "color: gray"}
            return colors.get(val, "")

        st.dataframe(
            radar_df.style.map(color_signal, subset=["Signal"]),
            width='stretch',
            height=420
        )

        buy_count  = (radar_df["Signal"] == "BUY").sum()
        sell_count = (radar_df["Signal"] == "SELL").sum()
        hold_count = (radar_df["Signal"] == "HOLD").sum()

        fig = px.pie(
            values=[buy_count, sell_count, hold_count],
            names=["BUY", "SELL", "HOLD"],
            color_discrete_map={"BUY": "#00cc66", "SELL": "#ff4444", "HOLD": "#888888"},
            title="Signal Distribution",
            template="plotly_dark"
        )
        st.plotly_chart(fig, width='stretch')
