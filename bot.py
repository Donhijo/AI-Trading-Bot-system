"""
bot.py — Main live trading loop.

Flow each cycle:
    1. Merge historical + live WebSocket candles
    2. Engineer features
    3. Get AI signal (with optional hybrid confirmation)
    4. Risk check → execute order
    5. Log everything → Telegram alert

Usage:
    python bot.py
"""
import time
import logging

from ai.data_loader import get_historical_data
from ai.features import create_features
from ai.predict import predict_signal_with_confidence

from live.execution_ import execute_signal
from live.monitor import send_alert, log_signal, log_balance, log_trade, log_error
from live.data_feed import start_feed, stop_feed, get_live_df
from live.risk import is_drawdown_safe, get_drawdown
from live.strategy import hybrid_strategy
from live.broker import get_account_balance

from config import (
    SYMBOL, TIMEFRAME, FEATURES,
    INITIAL_BALANCE, POLL_INTERVAL, LIMIT
)

logger = logging.getLogger("bot")


def run_bot():
    logger.info("=" * 55)
    logger.info("🤖  AI Trading Bot  —  Starting Up")
    logger.info("=" * 55)
    send_alert(f"🤖 <b>AI Trading Bot LIVE</b>\n📌 {SYMBOL} | {TIMEFRAME}")

    # ── Seed with historical data ──────────────────────────────────────────────
    logger.info("📥 Seeding historical data...")
    try:
        df = get_historical_data(limit=LIMIT)
        logger.info(f"📊 Loaded {len(df)} historical candles")
    except Exception as e:
        logger.error(f"Failed to load historical data: {e}")
        return

    # ── Start live WebSocket feed ──────────────────────────────────────────────
    start_feed(SYMBOL, TIMEFRAME)
    time.sleep(3)  # Let the feed warm up

    try:
        break_loop = False
        while True:
            if break_loop:
                break
            # ── Merge live candles ─────────────────────────────────────────────
            live_df = get_live_df()
            if not live_df.empty:
                df = df.combine_first(live_df).sort_index().iloc[-LIMIT:]

            # ── Feature engineering ───────────────────────────────────────────
            df_feat = create_features(df.copy())
            if len(df_feat) < 50:
                logger.warning("⏳ Waiting for enough candles...")
                time.sleep(POLL_INTERVAL)
                continue

            # ── AI prediction ─────────────────────────────────────────────────
            latest = df_feat[FEATURES].tail(1)
            ai_signal, confidence = predict_signal_with_confidence(latest)

            # ── Hybrid confirmation ───────────────────────────────────────────
            final_signal = hybrid_strategy(df_feat, ai_signal)
            log_signal(final_signal, confidence)

            # ── Balance & drawdown ────────────────────────────────────────────
            try:
                balance  = get_account_balance("USDT")
                drawdown = get_drawdown(balance, INITIAL_BALANCE)
                log_balance(balance, drawdown)

                if not is_drawdown_safe(balance, INITIAL_BALANCE):
                    msg = f"⛔ Max drawdown hit ({drawdown:.1%}) — bot paused"
                    logger.warning(msg)
                    send_alert(msg)
                    time.sleep(300)
                    continue
            except Exception as e:
                logger.warning(f"Could not fetch balance: {e}. Using default values.")
                balance = INITIAL_BALANCE
                drawdown = 0.0
                log_balance(balance, drawdown)

            # ── Execute ───────────────────────────────────────────────────────
            try:
                order = execute_signal(final_signal, SYMBOL, INITIAL_BALANCE)
                if order:
                    price = float(order.get("fills", [{}])[0].get("price", 0))
                    qty   = float(order.get("executedQty", 0))
                    log_trade(final_signal, price, qty)
            except Exception as e:
                logger.warning(f"Could not execute trade: {e}. Skipping execution.")

            logger.info(f"⏱  Next cycle in {POLL_INTERVAL}s\n")
            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped manually")
        send_alert("🛑 Bot <b>stopped</b> manually")
    except Exception as e:
        # Handle specific Binance time sync errors
        if "Timestamp for this request is outside of the recvWindow" in str(e):
            log_error("bot main loop", "Time sync issue - adjusting system clock")
            send_alert("⏰ Time sync issue - please check system clock synchronization")
            # Wait a bit and let the loop continue naturally
            time.sleep(60)
        else:
            log_error("bot main loop", e)
            send_alert(f"💥 Bot crashed: {e}")
            # For other errors, we'll exit the loop naturally through the while condition
            # Set a flag to break out of the loop
            break_loop = True
    finally:
        stop_feed()


if __name__ == "__main__":
    run_bot()
