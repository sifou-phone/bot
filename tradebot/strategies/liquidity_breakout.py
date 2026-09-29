from __future__ import annotations

import numpy as np
import pandas as pd

from .. import indicators as ind
from ..levels import liquidity_flow, resistance_support
from .base import BUY, HOLD, SELL, Strategy


class LiquidityBreakoutStrategy(Strategy):
    """Momentum breakout driven by liquidity, built for 1-minute candles.

    Entry (all must hold on the closed candle):
      * the coin is "exploding": up at least ``momentum_min`` over the last
        ``momentum_bars`` candles, with traded value over that window at least
        ``activity_min`` x its average for the last ``activity_window`` candles;
      * the close breaks above resistance (strongest confirmed swing high);
      * the breakout candle carries a liquidity surge: volume >= ``rvol_min`` x average;
      * buyers control the candle (close in the top of its range, ``clv >= clv_min``)
        and the recent volume-weighted flow is positive (``flow >= flow_min``);
      * price is above the trend EMA and not over-extended past the level;
      * the average traded value per candle is at least ``min_quote_volume``.

    Exit - "follow the liquidity": there is no fixed profit target. The trade is held
    while buyers keep supplying liquidity and closed when
      * a heavy *selling* candle prints (distribution: volume surge closing near its low), or
      * the volume-weighted flow turns negative (``flow <= flow_exit``), or
      * price closes back below the last swing support.

    The protective stop sits just under the broken level (``stop_levels``); the risk
    manager caps it with ``risk.max_stop_pct``, moves it to break-even and trails it.
    """

    name = "liquidity_breakout"
    defaults = {
        "pivot_left": 10, "pivot_right": 3, "level_lookback": 120,
        "vol_period": 20, "flow_period": 10,
        "rvol_min": 3.0, "clv_min": 0.4, "flow_min": 0.2,
        "trend": 50, "atr_period": 14, "max_extension_atr": 1.5, "stop_buffer_atr": 0.5,
        "exit_rvol": 2.5, "exit_clv": -0.5, "flow_exit": -0.25,
        "min_quote_volume": 0.0,
        "momentum_bars": 60, "momentum_min": 0.015, "activity_window": 1440, "activity_min": 1.2,
        # "candle": flow from where candles close in their range (thresholds above are calibrated
        # on it); "taker": real taker buy/sell delta where the exchange reports it (Binance).
        "flow_source": "candle",
    }

    def __init__(self, **params):
        super().__init__(**params)
        if self.params["flow_source"] not in ("candle", "taker"):
            raise ValueError("flow_source must be 'candle' or 'taker'")

    @property
    def warmup(self) -> int:
        p = self.params
        return max(p["level_lookback"], p["trend"] * 3, p["vol_period"] + p["flow_period"],
                   p["activity_window"] if p["activity_min"] > 0 else 0) + p["pivot_right"]

    def features(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        f = liquidity_flow(df, p["vol_period"], p["flow_period"], p["flow_source"] == "taker")
        lv = resistance_support(df, p["pivot_left"], p["pivot_right"], p["level_lookback"])
        f["resistance"] = lv["resistance"].shift(1)  # the level as known *before* this candle
        f["support"] = lv["support"]
        f["atr"] = ind.atr(df, p["atr_period"])
        f["trend"] = ind.ema(df["close"], p["trend"])
        f["avg_quote_volume"] = f["quote_volume"].rolling(p["vol_period"]).mean()
        n, w = p["momentum_bars"], p["activity_window"]
        f["momentum"] = df["close"] / df["close"].shift(n) - 1
        f["activity"] = f["quote_volume"].rolling(n).sum() / (f["quote_volume"].rolling(w).sum() * n / w)
        return f

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        p = self.params
        f = self.features(df)
        close = df["close"]
        breakout = (close > f["resistance"]) & (close.shift(1) <= f["resistance"])
        surge = f["rvol"] >= p["rvol_min"]
        buyers = (f["clv"] >= p["clv_min"]) & (f["flow"] >= p["flow_min"])
        trend_up = (close > f["trend"]) & (f["trend"] > f["trend"].shift(5))
        not_extended = (close - f["resistance"]) <= p["max_extension_atr"] * f["atr"]
        liquid = f["avg_quote_volume"] >= p["min_quote_volume"]
        exploding = (f["momentum"] >= p["momentum_min"]) & (
            (f["activity"] >= p["activity_min"]) if p["activity_min"] > 0 else True)

        distribution = (f["rvol"] >= p["exit_rvol"]) & (f["clv"] <= p["exit_clv"])
        flow_gone = f["flow"] <= p["flow_exit"]
        structure_broken = close < f["support"]

        signals = pd.Series(HOLD, index=df.index, dtype=int)
        signals[breakout & surge & buyers & trend_up & not_extended & liquid & exploding] = BUY
        signals[distribution | flow_gone | structure_broken] = SELL
        return signals

    def stop_levels(self, df: pd.DataFrame) -> pd.Series:
        f = self.features(df)
        stop = f["resistance"] - self.params["stop_buffer_atr"] * f["atr"]
        return stop.where(stop > 0, np.nan)
