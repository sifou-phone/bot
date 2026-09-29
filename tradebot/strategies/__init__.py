from __future__ import annotations

from typing import Any

from .base import BUY, HOLD, SELL, Strategy
from .ema_cross import EmaCrossStrategy
from .macd_trend import MacdTrendStrategy
from .rsi_reversion import RsiReversionStrategy

STRATEGIES: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (EmaCrossStrategy, RsiReversionStrategy, MacdTrendStrategy)
}


def create_strategy(name: str, params: dict[str, Any] | None = None) -> Strategy:
    try:
        cls = STRATEGIES[name]
    except KeyError:
        raise ValueError(f"Unknown strategy '{name}'. Available: {sorted(STRATEGIES)}") from None
    return cls(**(params or {}))


__all__ = ["BUY", "SELL", "HOLD", "Strategy", "STRATEGIES", "create_strategy"]
