"""
run.py — Run a full backtest of the AI strategy and print results.

Usage:
    python run.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai.data_loader import get_historical_data
from ai.features import create_features
from ai.labels import create_target
from backtest.engine import Backtester, plot_equity_curve
from backtest.strategy_wrapper import ai_strategy
from config import INITIAL_BALANCE, RISK_PER_TRADE, SL_PCT, TP_RATIO


def main():
    print("📥 Fetching historical data...")
    df = get_historical_data(limit=1000)

    print("⚙️  Engineering features...")
    df = create_features(df)

    print("🏷️  Generating labels...")
    df = create_target(df)
    df = df.reset_index(drop=True)

    print("🔁 Running backtest...\n")
    bt = Backtester(
        df,
        initial_balance=INITIAL_BALANCE,
        risk_per_trade=RISK_PER_TRADE,
        sl_pct=SL_PCT,
        tp_ratio=TP_RATIO
    )
    results = bt.run(ai_strategy)

    print("=" * 45)
    print("       BACKTEST RESULTS")
    print("=" * 45)
    print(f"  Initial Balance : ${INITIAL_BALANCE:,.2f}")
    print(f"  Final Balance   : ${results['final_balance']:,.2f}")
    print(f"  Net Profit      : ${results['profit']:+,.2f}  ({results['profit_pct']:+.2f}%)")
    print(f"  Total Trades    : {results['trades']}")
    print(f"  Win Rate        : {results['win_rate']:.2f}%")
    print(f"  Wins / Losses   : {results['wins']} / {results['losses']}")
    print(f"  Avg Win         : ${results['avg_win']:,.4f}")
    print(f"  Avg Loss        : ${results['avg_loss']:,.4f}")
    print(f"  Profit Factor   : {results['profit_factor']:.2f}")
    print(f"  Max Drawdown    : {results['max_drawdown']:.2f}%")
    print("=" * 45)

    plot_equity_curve(results)


if __name__ == "__main__":
    main()
