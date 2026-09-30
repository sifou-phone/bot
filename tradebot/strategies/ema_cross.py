from __future__ import annotations

import pandas as pd

from .. import indicators as ind
from .base import BUY, HOLD, SELL, Strategy


class EmaCrossStrategy(Strategy):
    """Trend following: fast EMA crossing the slow EMA, filtered by a trend EMA and ADX."""

    name = "ema_cross"
    defaults = {"fast": 12, "slow": 26, "trend": 200, "adx_period": 14, "adx_min": 20.0}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        close = df["close"]
        fast, slow, trend = ind.ema(close, p["fast"]), ind.ema(close, p["slow"]), ind.ema(close, p["trend"])
        strength = ind.adx(df, p["adx_period"])

        cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        cross_down = (fast < slow) & (fast.shift(1) >= slow.shift(1))

        signals = pd.Series(HOLD, index=df.index, dtype=int)
        signals[cross_up & (close > trend) & (strength >= p["adx_min"])] = BUY
        signals[cross_down] = SELL
        return signals
