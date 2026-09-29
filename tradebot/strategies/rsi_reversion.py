from __future__ import annotations

import pandas as pd

from .. import indicators as ind
from .base import BUY, HOLD, SELL, Strategy


class RsiReversionStrategy(Strategy):
    """Mean reversion: buy oversold dips below the lower Bollinger band, exit on recovery.

    Dips are only bought while price is above the long ``trend`` EMA (0 disables the filter),
    which avoids catching falling knives in a downtrend.
    """

    name = "rsi_reversion"
    defaults = {"rsi_period": 14, "oversold": 30.0, "overbought": 65.0, "bb_period": 20, "bb_std": 2.0,
                "trend": 200}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        close = df["close"]
        r = ind.rsi(close, p["rsi_period"])
        bands = ind.bollinger(close, p["bb_period"], p["bb_std"])

        uptrend = close > ind.ema(close, p["trend"]) if p["trend"] else pd.Series(True, index=df.index)

        signals = pd.Series(HOLD, index=df.index, dtype=int)
        signals[(r < p["oversold"]) & (close < bands["lower"]) & uptrend] = BUY
        signals[(r > p["overbought"]) | (close > bands["mid"] + (bands["upper"] - bands["mid"]) * 0.5)] = SELL
        return signals
