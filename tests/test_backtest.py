import numpy as np
import pandas as pd
import pytest

from tradebot.backtest import Backtester
from tradebot.config import CostsConfig, RiskConfig
from tradebot.data import synthetic_ohlcv
from tradebot.strategies import BUY, HOLD, STRATEGIES, SELL, Strategy, create_strategy


class Scripted(Strategy):
    name = "scripted"
    defaults = {}

    def __init__(self, signals):
        super().__init__()
        self._signals = signals

    @property
    def warmup(self):
        return 0

    def generate_signals(self, df):
        return pd.Series(self._signals, index=df.index)


def frame(opens, highs=None, lows=None, closes=None):
    n = len(opens)
    opens = np.array(opens, dtype=float)
    closes = np.array(closes if closes is not None else opens, dtype=float)
    return pd.DataFrame({
        "open": opens, "close": closes,
        "high": np.array(highs if highs is not None else np.maximum(opens, closes) + 0.5, dtype=float),
        "low": np.array(lows if lows is not None else np.minimum(opens, closes) - 0.5, dtype=float),
        "volume": np.ones(n),
    }, index=pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"))


RISK = RiskConfig(risk_per_trade=0.01, atr_period=3, stop_atr_mult=5, take_profit_rr=0,
                  max_position_pct=1, max_drawdown=0.9, daily_loss_limit=0.9, min_notional=1)
NO_COST = CostsConfig(fee_rate=0, slippage=0)


def test_signal_fills_on_next_open():
    df = frame([100, 100, 100, 100, 110, 120, 130, 140])
    sig = [HOLD] * 4 + [BUY, HOLD, SELL, HOLD]
    res = Backtester(Scripted(sig), RISK, NO_COST, 10_000).run(df)
    (t,) = res.trades
    assert t["entry"] == 120 and t["exit"] == 140  # bar after each signal
    assert t["pnl"] == pytest.approx(t["qty"] * 20)
    assert res.equity.iloc[-1] == pytest.approx(10_000 + t["pnl"])


def test_stop_loss_fills_at_stop_or_gap_open():
    base = [100.0] * 6
    df = frame(base + [100, 100], lows=[99.5] * 6 + [99.5, 50], closes=base + [100, 60])
    res = Backtester(Scripted([HOLD] * 5 + [BUY, HOLD, HOLD]), RISK, NO_COST).run(df)
    (t,) = res.trades
    assert t["reason"] == "stop_loss"
    assert t["exit"] == pytest.approx(100 - 5 * 1.0, rel=0.05)  # ATR ~ 1 -> stop ~ 95

    gap = frame(base + [100, 80], lows=[99.5] * 6 + [99.5, 79], closes=base + [100, 80])
    (t,) = Backtester(Scripted([HOLD] * 5 + [BUY, HOLD, HOLD]), RISK, NO_COST).run(gap).trades
    assert t["exit"] == 80  # gapped below the stop -> filled at the open


def test_costs_reduce_pnl():
    df = synthetic_ohlcv(1500)
    strat = create_strategy("macd_trend")
    free = Backtester(strat, RiskConfig(), NO_COST).run(df)
    paid = Backtester(strat, RiskConfig(), CostsConfig(fee_rate=0.001, slippage=0.001)).run(df)
    assert paid.metrics["end_equity"] < free.metrics["end_equity"]
    assert paid.metrics["fees_paid"] > 0


@pytest.mark.parametrize("name", sorted(STRATEGIES))
def test_strategies_have_no_lookahead(name):
    df = synthetic_ohlcv(1200, seed=7)
    strat = create_strategy(name)
    full = strat.generate_signals(df)
    partial = strat.generate_signals(df.iloc[:900])
    pd.testing.assert_series_equal(full.iloc[:900], partial)
    assert set(full.unique()) <= {BUY, SELL, HOLD}


@pytest.mark.parametrize("name", sorted(STRATEGIES))
def test_backtest_runs_and_equity_never_negative(name):
    res = Backtester(create_strategy(name), RiskConfig(), CostsConfig()).run(synthetic_ohlcv(2000))
    assert (res.equity > 0).all()
    assert res.metrics["trades"] == len(res.trades)


def test_unknown_strategy_param_rejected():
    with pytest.raises(ValueError):
        create_strategy("ema_cross", {"nope": 1})
