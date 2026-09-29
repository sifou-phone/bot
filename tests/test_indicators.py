import numpy as np
import pandas as pd

from tradebot import indicators as ind
from tradebot.data import synthetic_ohlcv


def test_sma_and_ema_basic():
    s = pd.Series([1.0, 2, 3, 4, 5])
    assert ind.sma(s, 5).iloc[-1] == 3
    assert np.isnan(ind.sma(s, 5).iloc[3])
    e = ind.ema(s, 2)
    assert e.iloc[-1] > ind.sma(s, 2).iloc[-2]  # EMA weights recent values


def test_rsi_bounds_and_extremes():
    up = pd.Series(np.arange(1, 60, dtype=float))
    assert ind.rsi(up).iloc[-1] == 100
    down = pd.Series(np.arange(60, 1, -1, dtype=float))
    assert ind.rsi(down).iloc[-1] < 1
    r = ind.rsi(synthetic_ohlcv(500)["close"]).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_atr_positive_and_bollinger_ordering():
    df = synthetic_ohlcv(300)
    assert (ind.atr(df).dropna() > 0).all()
    bb = ind.bollinger(df["close"]).dropna()
    assert ((bb["lower"] <= bb["mid"]) & (bb["mid"] <= bb["upper"])).all()


def test_indicators_are_causal():
    """Values at bar i must not change when future bars are appended."""
    df = synthetic_ohlcv(400)
    head = df.iloc[:300]
    for fn in (lambda d: ind.rsi(d["close"]), ind.atr, ind.adx, lambda d: ind.macd(d["close"])["hist"]):
        pd.testing.assert_series_equal(fn(head), fn(df).iloc[:300], check_names=False)
