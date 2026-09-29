import time

import numpy as np
import pandas as pd
import pytest

from tradebot.config import BotConfig, CostsConfig, RiskConfig, ScannerConfig
from tradebot.data import synthetic_ohlcv
from tradebot.hunter import HunterEngine
from tradebot.exchange import PaperExchange
from tradebot.levels import key_levels, liquidity_flow, pivot_highs, resistance_support
from tradebot.risk import RiskManager
from tradebot.scanner import Scanner
from tradebot.state import BotState
from tradebot.strategies import BUY, SELL, create_strategy


def candles(closes, volumes=None, spread=0.001):
    closes = np.asarray(closes, dtype=float)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="min", tz="UTC")
    return pd.DataFrame({
        "open": opens, "close": closes,
        "high": np.maximum(opens, closes) * (1 + spread), "low": np.minimum(opens, closes) * (1 - spread),
        "volume": np.ones(len(closes)) if volumes is None else np.asarray(volumes, dtype=float),
    }, index=idx)


def test_pivot_is_known_only_after_confirmation():
    highs = pd.Series([1, 2, 3, 9, 3, 2, 1, 1], dtype=float)
    ph = pivot_highs(highs, left=3, right=3)
    assert np.isnan(ph.iloc[3]) and np.isnan(ph.iloc[5])  # not visible at the peak itself
    assert ph.iloc[6] == 9


def test_liquidity_flow_reads_buyers_and_volume_surge():
    df = candles([100] * 30 + [101], volumes=[10] * 30 + [50], spread=0.0)
    df.loc[df.index[-1], "high"] = 101.0
    df.loc[df.index[-1], "low"] = 100.0
    liq = liquidity_flow(df, vol_period=20, flow_period=5).iloc[-1]
    assert liq["rvol"] == pytest.approx(5.0)
    assert liq["clv"] == pytest.approx(1.0)  # closed at the high: buyers won
    assert liq["flow"] > 0


def test_key_levels_cluster_repeated_tops():
    base = [100 + np.sin(i / 3) * 2 for i in range(300)]
    levels = key_levels(candles(base), left=5, right=5)
    assert levels and max(lv.touches for lv in levels) > 1
    assert {lv.kind for lv in levels} <= {"support", "resistance"}


def breakout_frame():
    """A calm uptrend under a clear ceiling, then a high-volume breakout candle."""
    rng = np.random.default_rng(1)
    n = 1700
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.0005, n)))
    closes[-120:] = np.linspace(closes[-121], closes[-121] * 1.02, 120)
    closes[-60:-1] = np.minimum(closes[-60:-1], closes[-61])  # flat ceiling for an hour
    closes[-1] = closes[-2] * 1.002  # breakout, within 1.5 ATR of the level
    vols = np.full(n, 10.0)
    vols[-60:] = 20.0
    vols[-1] = 200.0
    df = candles(closes, vols, spread=0.0005)
    df.loc[df.index[-1], "high"] = df["close"].iloc[-1]  # close at the high
    return df


def test_breakout_strategy_buys_the_surge_and_sets_a_structural_stop():
    strat = create_strategy("liquidity_breakout", {"momentum_min": 0.001, "activity_min": 1.0})
    df = breakout_frame()
    sig = strat.generate_signals(df)
    assert sig.iloc[-1] == BUY
    stop = strat.stop_levels(df).iloc[-1]
    assert stop < df["close"].iloc[-1]


def test_breakout_strategy_exits_on_distribution():
    strat = create_strategy("liquidity_breakout")
    df = candles([100] * 400, volumes=[10] * 399 + [100])
    df.loc[df.index[-1], ["open", "high", "low", "close"]] = [100.0, 100.2, 98.0, 98.1]
    assert strat.generate_signals(df).iloc[-1] == SELL


def test_strict_stop_is_capped_and_void_setups_skipped():
    rm = RiskManager(RiskConfig(max_stop_pct=0.015, min_stop_pct=0.008, max_position_pct=1), CostsConfig(0, 0))
    assert rm.plan_entry(10_000, 10_000, 100, 1, stop_hint=90).stop == pytest.approx(98.5)   # capped
    assert rm.plan_entry(10_000, 10_000, 100, 1, stop_hint=99.9).stop == pytest.approx(99.2)  # floored
    assert rm.plan_entry(10_000, 10_000, 100, 1, stop_hint=100.5) is None  # price fell through the level


def test_breakeven_locks_in_costs():
    rm = RiskManager(RiskConfig(breakeven_rr=1.0), CostsConfig(fee_rate=0.001, slippage=0.0))
    assert rm.breakeven_stop(98, entry=100, initial_stop=98, price=101) == 98
    assert rm.breakeven_stop(98, entry=100, initial_stop=98, price=102) == pytest.approx(100.2)


class FakeMarket:
    def __init__(self, frames):
        self.frames = frames
        self.prices = {s: float(df["close"].iloc[-1]) for s, df in frames.items()}

    def fetch_tickers(self):
        return {s: {"quoteVolume": 1e9} for s in self.frames} | {"USDC/USDT": {"quoteVolume": 1e12},
                                                                 "BTC3L/USDT": {"quoteVolume": 1e12}}

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        df = self.frames[symbol]
        rows = df[df.index >= pd.Timestamp(since, unit="ms", tz="UTC")].head(limit) if since else df.tail(limit)
        rows = rows[["open", "high", "low", "close", "volume"]]  # exchange (OHLCV) column order
        return [[int(ts.timestamp() * 1000), *r] for ts, r in zip(rows.index, rows.to_numpy().tolist())]

    def fetch_ticker(self, symbol):
        return {"last": self.prices[symbol]}


@pytest.fixture
def market():
    hot = breakout_frame()
    calm = synthetic_ohlcv(1700, timeframe="1m", start="2026-01-01", seed=3)
    # Date the candles so the last one closed just now (the fetcher pages up to the clock).
    last_open = pd.Timestamp(time.time() // 60 * 60 - 60, unit="s", tz="UTC")
    hot.index = calm.index = pd.date_range(end=last_open, periods=len(hot), freq="min", tz="UTC")
    return FakeMarket({"HOT/USDT": hot, "CALM/USDT": calm})


def make_scanner(market):
    strat = create_strategy("liquidity_breakout", {"momentum_min": 0.001, "activity_min": 1.0})
    cfg = ScannerConfig(min_quote_volume_24h=1)
    return Scanner(market, strat, cfg, "1m", history_bars=1600), strat


def test_scanner_filters_universe_and_ranks_breakout_first(market):
    scanner, _ = make_scanner(market)
    now = market.frames["HOT/USDT"].index[-1].timestamp() + 65
    assert set(scanner.universe(now)) == {"HOT/USDT", "CALM/USDT"}  # stablecoin + leveraged token dropped
    cands = scanner.scan(now)
    assert cands[0].symbol == "HOT/USDT" and cands[0].status == "BUY"
    assert cands[0].rvol > 3 and cands[0].stop < cands[0].price


def test_hunter_buys_the_breakout_then_stops_out(market, tmp_path):
    scanner, strat = make_scanner(market)
    cfg = BotConfig(timeframe="1m", history_bars=1600, state_file=str(tmp_path / "s.json"),
                    symbol="CALM/USDT")
    cfg.risk = RiskConfig(risk_per_trade=0.005, max_stop_pct=0.015, min_stop_pct=0.004, max_position_pct=0.5)
    ex = PaperExchange(cfg.exchange, "CALM/USDT", CostsConfig(), 1_000, market_data=market)
    hunter = HunterEngine(cfg, ex, strat, scanner, state=BotState())
    now = market.frames["HOT/USDT"].index[-1].timestamp() + 65

    hunter.tick(now)
    pos = hunter.state.position
    assert pos is not None and pos.symbol == "HOT/USDT"
    assert ex.symbol == "HOT/USDT" and ex.base_balance == pytest.approx(pos.qty)
    assert pos.stop >= pos.entry * (1 - 0.015)  # strict stop

    market.prices["HOT/USDT"] = pos.stop * 0.999
    hunter.tick(now + 5)
    assert hunter.state.position is None
    trade = hunter.state.trades[-1]
    assert trade["reason"] == "stop_loss" and trade["symbol"] == "HOT/USDT"
    assert trade["pnl"] > -1_000 * 0.005 * 1.6  # loss stays near the 0.5% risk budget


def test_taker_delta_is_the_real_buy_sell_imbalance():
    df = candles([100] * 30, volumes=[10] * 30)
    df["taker_buy"] = 8.0  # 8 bought at market, 2 sold -> delta +0.6
    real = liquidity_flow(df, 20, 5, use_taker=True).iloc[-1]
    est = liquidity_flow(df, 20, 5, use_taker=False).iloc[-1]
    assert real["delta"] == pytest.approx(0.6) and real["flow"] == pytest.approx(0.6)
    assert est["delta"] == pytest.approx(0.0)  # flat candles: shape says nothing


def test_binance_candles_carry_taker_volume():
    from tradebot.data import fetch_candles_raw, ohlcv_to_frame

    class FakeBinance:
        id = "binance"
        timeframes = {"1m": "1m"}

        def load_markets(self):
            return {}

        def market(self, symbol):
            return {"id": "BTCUSDT", "spot": True}

        def publicGetKlines(self, req):
            assert req == {"symbol": "BTCUSDT", "interval": "1m", "startTime": 0, "limit": 2}
            return [[0, "1", "2", "0.5", "1.5", "10", 59999, "15", 7, "6", "9", "0"]]

    df = ohlcv_to_frame(fetch_candles_raw(FakeBinance(), "BTC/USDT", "1m", since=0, limit=2))
    assert df["taker_buy"].iloc[0] == 6.0 and df["close"].iloc[0] == 1.5
