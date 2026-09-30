"""ArbBot: pricing math, detection, paper fills and execution recovery paths."""

import asyncio
import time

import pytest

from arbbot.config import Settings
from arbbot.detector import ArbitrageDetector, compute_opportunity
from arbbot.executor import Executor, Fill, PaperBroker
from arbbot.models import OrderBook, vwap_for_base, vwap_for_quote
from arbbot.storage import Storage


def settings(**kw):
    base = dict(exchanges=["a", "b"], symbols=["BTC/USDT"], trade_size_usdt=1000, min_net_spread_pct=0.3,
                slippage_buffer_pct=0.0, include_withdrawal_fee=False, taker_fees={"a": 0.001, "b": 0.001},
                cooldown_seconds=0, paper_quote_balance=10_000, paper_base_value_usdt=5_000)
    base.update(kw)
    return Settings(**base)


def book(ex, bid, ask, size=10.0, sym="BTC/USDT"):
    return OrderBook(ex, sym, [(bid, size), (bid * 0.999, size)], [(ask, size), (ask * 1.001, size)], time.time())


# ---------------------------------------------------------------- math
def test_vwap_walks_levels():
    levels = [(100.0, 1.0), (101.0, 1.0)]
    avg, base = vwap_for_quote(levels, 150.0)  # 100 + 50 at 101
    assert base == pytest.approx(1 + 50 / 101)
    assert avg == pytest.approx(150 / base)
    assert vwap_for_quote(levels, 10_000)[0] is None  # too thin
    assert vwap_for_base(levels, 1.5) == pytest.approx((100 + 50.5) / 1.5)


def test_net_spread_subtracts_fees_withdrawal_and_slippage():
    s = settings(include_withdrawal_fee=True, withdrawal_fees={"BTC": 0.0001, "USDT": 1.0},
                 rebalance_batch_usdt=10_000, slippage_buffer_pct=0.05)
    opp = compute_opportunity(s, book("a", 99.0, 100.0), book("b", 101.0, 102.0))
    assert opp.gross_pct == pytest.approx(1.0)
    assert opp.fees_pct == pytest.approx(0.2)
    assert opp.withdrawal_pct == pytest.approx((0.0001 * 101 + 1.0) / 10_000 * 100)
    assert opp.slippage_pct == pytest.approx(0.05)  # book deep enough: only the buffer
    assert opp.net_pct == pytest.approx(1.0 - 0.2 - opp.withdrawal_pct - 0.05)
    assert opp.actionable and opp.net_profit_usdt == pytest.approx(opp.net_pct / 100 * 1000)


def test_depth_slippage_and_threshold():
    s = settings()
    thin_buy = OrderBook("a", "BTC/USDT", [(99, 5)], [(100, 5), (101, 20)], time.time())  # 1000$ walks 2 levels
    opp = compute_opportunity(s, thin_buy, book("b", 100.6, 101))
    assert opp.buy_vwap > 100 and opp.slippage_pct > 0
    assert not opp.actionable  # 0.6% gross - 0.2% fees - depth slippage < 0.3%
    assert compute_opportunity(s, book("a", 99, 100, size=1), book("b", 101, 102)) is None  # too thin


def test_detector_evaluates_every_direction():
    s = settings(exchanges=["a", "b", "c"], taker_fees={"a": 0.001, "b": 0.001, "c": 0.001})
    books = [book("a", 99, 100), book("b", 101, 102), book("c", 99.5, 100.5)]
    det = ArbitrageDetector(s, lambda sym: books)
    actionable = det.evaluate("BTC/USDT")
    assert len(det.latest) == 6  # 3 exchanges -> 6 ordered pairs
    assert [(o.buy_exchange, o.sell_exchange) for o in actionable][0] == ("a", "b")
    assert all(o.net_pct >= 0.3 for o in actionable)


# ---------------------------------------------------------------- paper broker
def run(coro):
    return asyncio.run(coro)


def test_paper_fill_respects_limit_fee_and_balance():
    s = settings()
    b = book("a", 99, 100, size=1.0)  # asks: 1 @ 100, 1 @ 100.1
    pb = PaperBroker("a", s, lambda ex, sym: b)
    pb.ensure_asset("BTC/USDT")
    fill = run(pb.ioc("BTC/USDT", "buy", 1.5, limit_price=100.0))
    assert fill.filled == pytest.approx(1.0) and fill.avg_price == 100.0  # 2nd level above the limit
    assert fill.fee_quote == pytest.approx(0.1)
    assert pb.assets["USDT"] == pytest.approx(10_000 - 100 - 0.1)
    s.paper_fail_rate = 1.0
    assert run(pb.market("BTC/USDT", "sell", 0.1)).error


# ---------------------------------------------------------------- executor
class StubBroker:
    """Scripted broker to force partial fills and failures."""

    def __init__(self, name, fills, balances=None, market_fill=None):
        self.name = name
        self.fills = fills
        self.market_fill = market_fill
        self.bal = balances or {"USDT": 100_000, "BTC": 100}
        self.market_calls = []

    async def balances(self):
        return self.bal

    async def ioc(self, symbol, side, amount, limit_price):
        f = self.fills[side]
        return Fill(self.name, side, amount, f[0] if f[0] is not None else amount, f[1], f[2], error=f[3] if len(f) > 3 else None)

    async def market(self, symbol, side, amount):
        self.market_calls.append((side, amount))
        if self.market_fill == "fail":
            return Fill(self.name, side, amount, error="exchange down")
        return Fill(self.name, side, amount, amount, 100.0, amount * 100 * 0.001)

    async def cancel_open_orders(self):
        return None


def opportunity(s, net=1.0):
    opp = compute_opportunity(s, book("a", 99, 100), book("b", 101, 102))
    opp.net_pct = net
    return opp


def execute(buy_broker, sell_broker, s=None):
    s = s or settings()
    store = Storage(":memory:")
    ex = Executor(s, store, {"a": buy_broker, "b": sell_broker})
    row = run(ex.execute(opportunity(s)))
    return ex, row, store


def test_both_legs_filled():
    amount = 10.0
    ex, row, store = execute(StubBroker("a", {"buy": (amount, 100.0, 1.0)}),
                             StubBroker("b", {"sell": (amount, 101.0, 1.01)}))
    assert row["status"] == "filled"
    assert row["pnl_usdt"] == pytest.approx(10 * 101 - 1.01 - 10 * 100 - 1.0)
    assert store.recent_executions()[0]["status"] == "filled"


def test_partial_fill_is_hedged_on_the_overfilled_exchange():
    buy = StubBroker("a", {"buy": (10.0, 100.0, 1.0)})
    sell = StubBroker("b", {"sell": (6.0, 101.0, 0.6)})
    ex, row, _ = execute(buy, sell)
    assert row["status"] == "partial_hedged"
    assert buy.market_calls == [("sell", pytest.approx(4.0))]  # excess coin sold where it was bought
    legs = row["detail"]["legs"]
    net_base = sum(l["filled"] if l["side"] == "buy" else -l["filled"] for l in legs)
    assert net_base == pytest.approx(0.0)
    assert not ex.state.killed


def test_one_leg_failure_is_unwound():
    buy = StubBroker("a", {"buy": (10.0, 100.0, 1.0)})
    sell = StubBroker("b", {"sell": (0.0, 0.0, 0.0, "insufficient balance")})
    _, row, _ = execute(buy, sell)
    assert row["status"] == "one_leg_unwound"
    assert buy.market_calls == [("sell", pytest.approx(10.0))]


def test_short_side_overfill_buys_back_on_sell_exchange():
    buy = StubBroker("a", {"buy": (0.0, 0.0, 0.0, "timeout")})
    sell = StubBroker("b", {"sell": (10.0, 101.0, 1.0)})
    _, row, _ = execute(buy, sell)
    assert row["status"] == "one_leg_unwound" and sell.market_calls == [("buy", pytest.approx(10.0))]


def test_failed_hedge_records_exposure_and_trips_kill_switch():
    buy = StubBroker("a", {"buy": (10.0, 100.0, 1.0)}, market_fill="fail")
    sell = StubBroker("b", {"sell": (0.0, 0.0, 0.0, "rejected")})
    ex, row, _ = execute(buy, sell)
    assert row["status"] == "hedge_failed"
    assert ex.state.killed and ex.state.exposures[0]["amount"] == pytest.approx(10.0)
    assert abs(row["pnl_usdt"]) < 20  # the open long is marked to market, not a -1000 loss


def test_unhedged_short_is_not_reported_as_profit():
    buy = StubBroker("a", {"buy": (0.0, 0.0, 0.0, "rejected")})
    sell = StubBroker("b", {"sell": (10.0, 101.0, 1.0)}, market_fill="fail")
    ex, row, _ = execute(buy, sell)
    assert row["status"] == "hedge_failed" and ex.state.killed
    assert row["pnl_usdt"] < 20  # proceeds of 1010 minus the short valued at the mid price


def test_nothing_filled_and_insufficient_inventory():
    _, row, _ = execute(StubBroker("a", {"buy": (0.0, 0, 0)}), StubBroker("b", {"sell": (0.0, 0, 0)}))
    assert row["status"] == "not_filled" and row["pnl_usdt"] == 0
    s = settings()
    poor = StubBroker("b", {"sell": (1, 1, 0)}, balances={"USDT": 0, "BTC": 0})
    ex, row, _ = execute(StubBroker("a", {"buy": (1, 1, 0)}), poor, s)
    assert row is None and "not enough BTC" in ex.state.last_skip["BTC/USDT"]


def test_kill_switch_blocks_new_orders_and_daily_loss_trips_it():
    s = settings()

    async def scenario():
        ex = Executor(s, Storage(":memory:"), {"a": StubBroker("a", {}), "b": StubBroker("b", {})})
        ex.kill("test")
        assert ex.submit(opportunity(s)) is None and "kill switch" in ex.state.last_skip["BTC/USDT"]
        ex.reset_kill()
        ex._roll_day()
        ex.state.day_pnl = -s.max_daily_loss_usdt
        assert ex.submit(opportunity(s)) is None and ex.state.killed
    run(scenario())


def test_paper_end_to_end_execution_changes_balances():
    s = settings(trade_size_usdt=500)
    books = {"a": book("a", 99, 100), "b": book("b", 101, 102)}
    brokers = {n: PaperBroker(n, s, lambda ex, sym: books[ex]) for n in ("a", "b")}
    store = Storage(":memory:")

    async def scenario():
        ex = Executor(s, store, brokers)
        opp = compute_opportunity(s, books["a"], books["b"])
        assert opp.actionable
        await ex.submit(opp)
        return ex
    ex = run(scenario())
    row = store.recent_executions()[0]
    assert row["status"] == "filled" and row["pnl_usdt"] > 0
    assert brokers["a"].assets["BTC"] > brokers["b"].assets["BTC"]  # coin moved from b's inventory to a's


def test_unknown_coin_withdrawal_is_never_free():
    s = settings(include_withdrawal_fee=True, withdrawal_fees={"USDT": 1.0}, rebalance_batch_usdt=1000,
                 default_withdrawal_fee_usdt=2.0)
    wif = lambda ex, bid, ask: OrderBook(ex, "WIF/USDT", [(bid, 5000)], [(ask, 5000)], time.time())
    opp = compute_opportunity(s, wif("a", 0.99, 1.0), wif("b", 1.02, 1.03))
    assert opp.withdrawal_pct == pytest.approx((2.0 + 1.0) / 1000 * 100)  # default for WIF + USDT


def test_route_with_suspended_transfers_is_blocked():
    s = settings()
    status = {("a", "BTC"): {"deposit": False, "withdraw": False}}
    transfers = lambda ex, coin: status.get((ex, coin), {})
    opp = compute_opportunity(s, book("a", 99, 100), book("b", 101, 102), transfers=transfers)
    assert opp.net_pct > s.min_net_spread_pct and not opp.actionable
    assert opp.blocked == "BTC withdraw suspended on a"
    back = compute_opportunity(s, book("b", 99, 100), book("a", 101, 102), transfers=transfers)
    assert back.blocked == "BTC deposit suspended on a"
    assert compute_opportunity(s, book("a", 99, 100), book("b", 101, 102),
                               transfers=lambda ex, coin: {}).actionable  # unknown status = open


def test_suspicious_gap_is_never_traded():
    s = settings(max_gross_spread_pct=3.0)
    opp = compute_opportunity(s, book("a", 99, 100), book("b", 113, 114))  # a 13% "opportunity"
    assert opp.net_pct > 10 and not opp.actionable and "suspicious" in opp.blocked


def test_detector_does_not_signal_blocked_routes():
    s = settings()
    books = [book("a", 99, 100), book("b", 101, 102)]
    det = ArbitrageDetector(s, lambda sym: books,
                            transfers=lambda ex, coin: {"withdraw": False} if ex == "a" else {})
    assert det.evaluate("BTC/USDT") == []
    assert any(o.blocked for o in det.latest.values())
