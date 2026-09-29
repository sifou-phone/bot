import pandas as pd
import pytest

from tradebot.config import BotConfig, CostsConfig
from tradebot.data import synthetic_ohlcv
from tradebot.engine import TradingEngine
from tradebot.exchange import PaperExchange
from tradebot.state import BotState
from tradebot.strategies import BUY, HOLD, SELL, Strategy


class FakeMarket:
    """Mimics the two ccxt calls used by PaperExchange."""

    def __init__(self, df):
        self.df = df
        self.price = float(df["close"].iloc[-1])

    def fetch_ohlcv(self, symbol, timeframe, limit=None, since=None):
        rows = self.df.tail(limit)
        return [[int(ts.timestamp() * 1000), *row] for ts, row in zip(rows.index, rows.to_numpy().tolist())]

    def fetch_ticker(self, symbol):
        return {"last": self.price}


class Fixed(Strategy):
    name = "fixed"
    defaults = {}
    signal = HOLD

    @property
    def warmup(self):
        return 20

    def generate_signals(self, df):
        s = pd.Series(HOLD, index=df.index)
        s.iloc[-1] = self.signal
        return s


@pytest.fixture
def setup(tmp_path):
    cfg = BotConfig(state_file=str(tmp_path / "state.json"), history_bars=100)
    cfg.costs = CostsConfig(fee_rate=0.001, slippage=0)
    df = synthetic_ohlcv(200)
    market = FakeMarket(df)
    ex = PaperExchange(cfg.exchange, cfg.symbol, cfg.costs, 10_000, market_data=market)
    strat = Fixed()
    engine = TradingEngine(cfg, ex, strat, state=BotState())
    # "now" is just after the last candle closed
    now = (df.index[-1] + pd.Timedelta(hours=1)).timestamp() + 5
    return cfg, market, ex, strat, engine, now


def test_buy_then_sell_on_signal_and_persist(setup):
    cfg, market, ex, strat, engine, now = setup
    strat.signal = BUY
    engine.tick(now)
    pos = engine.state.position
    assert pos is not None and pos.qty > 0 and pos.stop < pos.entry
    assert ex.base_balance == pytest.approx(pos.qty)

    engine.tick(now + 10)  # same candle -> no duplicate order
    assert ex.base_balance == pytest.approx(pos.qty)

    restored = BotState.load(cfg.state_file)
    assert restored.position.qty == pytest.approx(pos.qty)
    assert restored.paper_quote == pytest.approx(ex.quote_balance)

    # next candle closes with a sell signal
    market.df = pd.concat([market.df, market.df.iloc[[-1]].set_axis([market.df.index[-1] + pd.Timedelta(hours=1)])])
    strat.signal = SELL
    engine.tick(now + 3600)
    assert engine.state.position is None
    assert len(engine.state.trades) == 1
    assert ex.base_balance == pytest.approx(0)


def test_stop_loss_triggers_on_live_price(setup):
    _, market, ex, strat, engine, now = setup
    strat.signal = BUY
    engine.tick(now)
    stop = engine.state.position.stop
    market.price = stop * 0.99
    strat.signal = HOLD
    engine.tick(now + 30)
    assert engine.state.position is None
    assert engine.state.trades[-1]["reason"] == "stop_loss"
    assert engine.state.trades[-1]["pnl"] < 0


def test_drawdown_halts_new_entries(setup):
    _, _, ex, strat, engine, now = setup
    engine.state.peak_equity = 20_000  # equity 10k -> 50% drawdown
    strat.signal = BUY
    engine.tick(now)
    assert engine.state.position is None
    assert "drawdown" in engine.state.halted


def test_forming_candle_is_ignored(setup):
    _, market, _, strat, engine, now = setup
    engine.tick(now - 3600)  # the last candle is still forming at this time
    assert engine.state.last_candle == market.df.index[-2].isoformat()
