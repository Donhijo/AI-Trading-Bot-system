"""
backtester.py — Convenience re-export.
Import from here or directly from backtest.engine — both work.
"""
from backtest.engine import Backtester, plot_equity_curve  # noqa: F401

__all__ = ["Backtester", "plot_equity_curve"]
