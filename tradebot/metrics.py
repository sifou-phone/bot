"""Performance statistics for an equity curve and a list of closed trades."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

_TIMEFRAME_SECONDS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def timeframe_seconds(timeframe: str) -> int:
    unit = timeframe[-1]
    if unit not in _TIMEFRAME_SECONDS:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return int(timeframe[:-1]) * _TIMEFRAME_SECONDS[unit]


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    return float((1 - equity / peak).max())


def compute_metrics(equity: pd.Series, trades: list[dict[str, Any]], timeframe: str) -> dict[str, float]:
    if equity.empty:
        return {}
    start, end = float(equity.iloc[0]), float(equity.iloc[-1])
    periods_per_year = 365 * 86400 / timeframe_seconds(timeframe)
    returns = equity.pct_change().dropna()
    years = len(equity) / periods_per_year

    std = returns.std()
    downside = math.sqrt((returns.clip(upper=0) ** 2).mean()) if len(returns) else 0.0
    sharpe = float(returns.mean() / std * math.sqrt(periods_per_year)) if std and std > 0 else 0.0
    sortino = float(returns.mean() / downside * math.sqrt(periods_per_year)) if downside and downside > 0 else 0.0
    mdd = max_drawdown(equity)
    cagr = (end / start) ** (1 / years) - 1 if years > 0 and start > 0 and end > 0 else 0.0

    pnls = np.array([t["pnl"] for t in trades], dtype=float)
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    gross_loss = -losses.sum()
    return {
        "start_equity": start,
        "end_equity": end,
        "total_return_pct": (end / start - 1) * 100,
        "cagr_pct": cagr * 100,
        "max_drawdown_pct": mdd * 100,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": cagr / mdd if mdd > 0 else 0.0,
        "trades": len(pnls),
        "win_rate_pct": len(wins) / len(pnls) * 100 if len(pnls) else 0.0,
        "profit_factor": float(wins.sum() / gross_loss) if gross_loss > 0 else float("inf") if len(wins) else 0.0,
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "expectancy": float(pnls.mean()) if len(pnls) else 0.0,
        "fees_paid": float(sum(t.get("fees", 0.0) for t in trades)),
    }


def format_metrics(m: dict[str, float]) -> str:
    labels = [
        ("Start equity", "start_equity", "{:,.2f}"),
        ("End equity", "end_equity", "{:,.2f}"),
        ("Total return", "total_return_pct", "{:+.2f}%"),
        ("CAGR", "cagr_pct", "{:+.2f}%"),
        ("Max drawdown", "max_drawdown_pct", "{:.2f}%"),
        ("Sharpe", "sharpe", "{:.2f}"),
        ("Sortino", "sortino", "{:.2f}"),
        ("Calmar", "calmar", "{:.2f}"),
        ("Trades", "trades", "{:d}"),
        ("Win rate", "win_rate_pct", "{:.1f}%"),
        ("Profit factor", "profit_factor", "{:.2f}"),
        ("Avg win", "avg_win", "{:,.2f}"),
        ("Avg loss", "avg_loss", "{:,.2f}"),
        ("Expectancy/trade", "expectancy", "{:,.2f}"),
        ("Fees paid", "fees_paid", "{:,.2f}"),
    ]
    lines = []
    for label, key, fmt in labels:
        value = m.get(key, 0)
        value = int(value) if fmt == "{:d}" else value
        lines.append(f"  {label:<18}{fmt.format(value)}")
    return "\n".join(lines)
