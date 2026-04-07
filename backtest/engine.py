import pandas as pd
import matplotlib.pyplot as plt


def plot_equity_curve(results: dict):
    """Plot the equity curve from backtest results."""
    equity = results["equity_curve"]
    plt.figure(figsize=(12, 5))
    plt.plot(equity, color="royalblue", linewidth=1.5, label="Equity")
    plt.axhline(equity[0], color="gray", linestyle="--", linewidth=1, label="Starting Balance")
    plt.title("📈 Equity Curve", fontsize=14)
    plt.xlabel("Candles")
    plt.ylabel("Balance (USDT)")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.show()


class Backtester:
    def __init__(
        self,
        df,
        initial_balance: float = 1000,
        risk_per_trade: float = 0.02,
        sl_pct: float = 0.02,
        tp_ratio: float = 2.0,
        fee: float = 0.001,        # 0.1% Binance taker fee
        spread: float = 0.0005,    # 0.05% bid/ask spread
        slippage: float = 0.0005,  # 0.05% slippage
        latency: int = 1           # 1-candle execution delay
    ):
        self.df              = df.reset_index(drop=True)
        self.balance         = initial_balance
        self.initial_balance = initial_balance
        self.risk_per_trade  = risk_per_trade
        self.sl_pct          = sl_pct
        self.tp_ratio        = tp_ratio
        self.fee             = fee
        self.spread          = spread
        self.slippage        = slippage
        self.latency         = latency
        self.trades          = []
        self.equity_curve    = []

    # ── Main loop ──────────────────────────────────────────────────────────────
    def run(self, strategy_func) -> dict:
        position = None

        for i in range(50, len(self.df)):
            signal = strategy_func(self.df.iloc[:i])

            if i + self.latency >= len(self.df):
                break

            exec_row = self.df.iloc[i + self.latency]
            price    = exec_row["close"]
            pnl      = 0

            # Open new position
            if position is None and signal in ("BUY", "SELL"):
                if signal == "BUY":
                    entry = price * (1 + self.spread + self.slippage)
                else:
                    entry = price * (1 - self.spread - self.slippage)

                sl, tp = self._calc_sl_tp(entry, signal)
                risk_amt = self.balance * self.risk_per_trade
                size     = risk_amt / abs(entry - sl)

                position = {
                    "side":  signal,
                    "entry": entry,
                    "sl":    sl,
                    "tp":    tp,
                    "size":  size
                }

            # Manage open position
            elif position is not None:
                size = position["size"]
                gross_pnl, position = self._manage_position(position, exec_row)
                if gross_pnl != 0:
                    pnl = gross_pnl - (price * size * self.fee)

            if pnl != 0:
                self.balance += pnl
                self.trades.append(pnl)

            self.equity_curve.append(self.balance)

        return self.results()

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _calc_sl_tp(self, price: float, signal: str) -> tuple[float, float]:
        r = self.sl_pct
        if signal == "BUY":
            return price * (1 - r), price * (1 + r * self.tp_ratio)
        else:
            return price * (1 + r), price * (1 - r * self.tp_ratio)

    def _manage_position(self, position: dict, row) -> tuple[float, dict | None]:
        side, entry, sl, tp, size = (
            position["side"], position["entry"],
            position["sl"],   position["tp"], position["size"]
        )
        if side == "BUY":
            if row["low"]  <= sl: return (sl - entry) * size, None
            if row["high"] >= tp: return (tp - entry) * size, None
        elif side == "SELL":
            if row["high"] >= sl: return (entry - sl) * size, None
            if row["low"]  <= tp: return (entry - tp) * size, None
        return 0, position

    # ── Results ────────────────────────────────────────────────────────────────
    def results(self) -> dict:
        total  = len(self.trades)
        wins   = [t for t in self.trades if t > 0]
        losses = [t for t in self.trades if t <= 0]

        win_rate   = len(wins) / total * 100 if total else 0
        avg_win    = sum(wins)   / len(wins)   if wins   else 0
        avg_loss   = sum(losses) / len(losses) if losses else 0
        profit_factor = abs(sum(wins) / sum(losses)) if sum(losses) != 0 else float("inf")

        peak      = self.initial_balance
        max_dd    = 0.0
        for eq in self.equity_curve:
            peak  = max(peak, eq)
            dd    = (peak - eq) / peak
            max_dd = max(max_dd, dd)

        return {
            "final_balance":  round(self.balance, 2),
            "profit":         round(self.balance - self.initial_balance, 2),
            "profit_pct":     round((self.balance / self.initial_balance - 1) * 100, 2),
            "trades":         total,
            "win_rate":       round(win_rate, 2),
            "wins":           len(wins),
            "losses":         len(losses),
            "avg_win":        round(avg_win, 4),
            "avg_loss":       round(avg_loss, 4),
            "profit_factor":  round(profit_factor, 2),
            "max_drawdown":   round(max_dd * 100, 2),
            "equity_curve":   self.equity_curve,
        }
