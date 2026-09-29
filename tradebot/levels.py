"""Support / resistance from confirmed swing pivots, and per-candle liquidity flow.

Everything here is causal: a pivot at bar ``j`` needs ``right`` later bars to be
confirmed, so it only becomes visible at bar ``j + right``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


def pivot_highs(high: pd.Series, left: int, right: int) -> pd.Series:
    """Pivot-high prices placed at their *confirmation* bar (NaN elsewhere)."""
    window = left + right + 1
    is_pivot = high.rolling(window).max() == high.shift(right)
    return high.shift(right).where(is_pivot)


def pivot_lows(low: pd.Series, left: int, right: int) -> pd.Series:
    window = left + right + 1
    is_pivot = low.rolling(window).min() == low.shift(right)
    return low.shift(right).where(is_pivot)


def resistance_support(df: pd.DataFrame, left: int = 10, right: int = 3,
                       lookback: int = 120) -> pd.DataFrame:
    """Per bar: the strongest confirmed resistance (highest pivot high) and the
    most recent confirmed support (last pivot low) within ``lookback`` bars."""
    ph = pivot_highs(df["high"], left, right)
    pl = pivot_lows(df["low"], left, right)
    resistance = ph.rolling(lookback, min_periods=1).max()
    support = pl.ffill(limit=lookback)
    return pd.DataFrame({"resistance": resistance, "support": support})


def liquidity_flow(df: pd.DataFrame, vol_period: int = 20, flow_period: int = 10) -> pd.DataFrame:
    """Liquidity read of every candle.

    * ``rvol``  - candle volume relative to the average of the previous ``vol_period`` candles
    * ``clv``   - where the close sits in the candle range: +1 at the high (buyers won), -1 at the low
    * ``flow``  - volume-weighted buying pressure over ``flow_period`` candles, in [-1, 1]
    * ``quote_volume`` - traded value (volume x close) of the candle
    """
    rng = (df["high"] - df["low"]).replace(0.0, np.nan)
    clv = (((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng).fillna(0.0)
    avg_vol = df["volume"].rolling(vol_period, min_periods=vol_period).mean().shift(1)
    rvol = df["volume"] / avg_vol.replace(0.0, np.nan)
    vol_sum = df["volume"].rolling(flow_period, min_periods=flow_period).sum().replace(0.0, np.nan)
    flow = (clv * df["volume"]).rolling(flow_period, min_periods=flow_period).sum() / vol_sum
    return pd.DataFrame({"rvol": rvol, "clv": clv, "flow": flow, "quote_volume": df["volume"] * df["close"]})


@dataclass
class Level:
    price: float
    touches: int
    kind: str  # "support" | "resistance"


def key_levels(df: pd.DataFrame, left: int = 10, right: int = 3, tolerance: float = 0.002,
               max_levels: int = 6) -> list[Level]:
    """Cluster recent pivots into horizontal levels (for display / the scanner).

    Pivots within ``tolerance`` (relative) of each other merge into one level; a level
    touched more times is stronger. Levels are labelled relative to the last close.
    """
    ph = pivot_highs(df["high"], left, right).dropna()
    pl = pivot_lows(df["low"], left, right).dropna()
    prices = sorted(pd.concat([ph, pl]).tolist())
    clusters: list[list[float]] = []
    for p in prices:
        if clusters and abs(p / np.mean(clusters[-1]) - 1) <= tolerance:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    last = float(df["close"].iloc[-1])
    levels = [Level(float(np.mean(c)), len(c), "resistance" if np.mean(c) > last else "support")
              for c in clusters]
    levels.sort(key=lambda lv: abs(lv.price / last - 1))
    return levels[:max_levels]
