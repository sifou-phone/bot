from __future__ import annotations

import pandas as pd

from .. import indicators as ind
from .base import BUY, HOLD, SELL, Strategy


class MacdTrendStrategy(Strategy):
    """MACD histogram flips, confirmed by price above the trend EMA and RSI not overbought."""

    name = "macd_trend"
    defaults = {"fast": 12, "slow": 26, "signal": 9, "trend": 100, "rsi_period": 14, "rsi_max": 70.0}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        close = df["close"]
        m = ind.macd(close, p["fast"], p["slow"], p["signal"])
        trend = ind.ema(close, p["trend"])
        r = ind.rsi(close, p["rsi_period"])

        hist, prev = m["hist"], m["hist"].shift(1)
        signals = pd.Series(HOLD, index=df.index, dtype=int)
        signals[(hist > 0) & (prev <= 0) & (close > trend) & (r < p["rsi_max"])] = BUY
        signals[(hist < 0) & (prev >= 0)] = SELL
        return signals
