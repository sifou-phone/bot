"""Event-driven, bar-by-bar backtester.

Execution model (no look-ahead):
  * a signal computed on the close of bar ``i`` is filled at the open of bar ``i+1``;
  * stop-loss / take-profit are checked against each bar's high/low. If a bar
    gaps through the level, the fill happens at the open. If both levels are
    touched in the same bar the stop is assumed first (conservative);
  * every fill pays ``fee_rate`` and adverse ``slippage``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from . import indicators as ind
from .config import CostsConfig, RiskConfig
from .metrics import compute_metrics
from .risk import RiskManager
from .strategies import BUY, SELL, Strategy


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: list[dict[str, Any]]
    metrics: dict[str, float]
    halted: str | None = None
    signals: pd.Series = field(default_factory=lambda: pd.Series(dtype=int))

    def trades_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.trades)


class Backtester:
    def __init__(self, strategy: Strategy, risk: RiskConfig, costs: CostsConfig,
                 initial_capital: float = 10_000.0, timeframe: str = "1h") -> None:
        self.strategy = strategy
        self.risk = RiskManager(risk, costs)
        self.costs = costs
        self.initial_capital = initial_capital
        self.timeframe = timeframe

    def run(self, df: pd.DataFrame) -> BacktestResult:
        if df.empty:
            raise ValueError("No data to backtest")
        signals = self.strategy.generate_signals(df).reindex(df.index).fillna(0).astype(int)
        atr = ind.atr(df, self.risk.cfg.atr_period).to_numpy()
        o, h, l, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
        sig = signals.to_numpy()
        times = df.index
        fee, slip = self.costs.fee_rate, self.costs.slippage

        cash = self.initial_capital
        qty = 0.0
        pos: dict[str, Any] | None = None
        trades: list[dict[str, Any]] = []
        equity = np.empty(len(df))
        peak = cash
        day, day_start = None, cash
        halted: str | None = None
        pending = 0

        def close_position(i: int, price: float, reason: str) -> None:
            nonlocal cash, qty, pos
            fill = price * (1 - slip)
            proceeds = qty * fill
            exit_fee = proceeds * fee
            cash += proceeds - exit_fee
            fees = pos["entry_fee"] + exit_fee
            pnl = proceeds - exit_fee - (pos["cost"])
            trades.append({
                "entry_time": pos["time"], "exit_time": times[i], "entry": pos["entry"],
                "exit": fill, "qty": qty, "pnl": pnl, "return_pct": pnl / pos["cost"] * 100,
                "fees": fees, "reason": reason, "bars": i - pos["bar"],
            })
            qty, pos = 0.0, None

        for i in range(len(df)):
            today = times[i].date() if hasattr(times[i], "date") else None
            if today != day:
                day, day_start = today, (equity[i - 1] if i else cash)

            # 1) execute the order decided on the previous close, at this open
            if pending == SELL and pos is not None:
                close_position(i, o[i], "signal")
            elif pending == BUY and pos is None and halted is None:
                mark = equity[i - 1] if i else cash
                reason = self.risk.halt_reason(mark, day_start, peak)
                if reason:
                    if "drawdown" in reason:
                        halted = reason
                else:
                    fill = o[i] * (1 + slip)
                    plan = self.risk.plan_entry(cash, cash, fill, atr[i - 1] if i else np.nan)
                    if plan:
                        qty = plan.qty
                        entry_fee = qty * fill * fee
                        cash -= qty * fill + entry_fee
                        pos = {"time": times[i], "bar": i, "entry": fill, "stop": plan.stop,
                               "tp": plan.take_profit, "entry_fee": entry_fee, "cost": qty * fill + entry_fee}
            pending = 0

            # 2) protective exits within this bar
            if pos is not None:
                stop, tp = pos["stop"], pos["tp"]
                if o[i] <= stop:
                    close_position(i, o[i], "stop_loss")
                elif tp is not None and o[i] >= tp:
                    close_position(i, o[i], "take_profit")
                elif l[i] <= stop:
                    close_position(i, stop, "stop_loss")
                elif tp is not None and h[i] >= tp:
                    close_position(i, tp, "take_profit")
                else:
                    pos["stop"] = self.risk.trail_stop(stop, c[i], atr[i])

            equity[i] = cash + qty * c[i]
            peak = max(peak, equity[i])

            # 3) decide on this close, act on the next open
            if i >= self.strategy.warmup:
                pending = sig[i]

        if pos is not None:
            close_position(len(df) - 1, c[-1], "end_of_data")
            equity[-1] = cash

        curve = pd.Series(equity, index=df.index, name="equity")
        return BacktestResult(curve, trades, compute_metrics(curve, trades, self.timeframe), halted, signals)
