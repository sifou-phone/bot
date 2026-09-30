"""Cross-exchange arbitrage detection.

For every ordered pair of exchanges (A, B) and every symbol: buy on A at A's
ask, sell on B at B's bid. For the configured trade size the detector walks
both order books to get the prices the trade would really get, then subtracts:

  * taker fees on both legs;
  * re-balancing: after trading, coin piles up on A and USDT on B. Moving them
    back costs one coin withdrawal (A -> B) plus one USDT withdrawal (B -> A).
    Traders re-balance after a batch of trades, so that cost is spread over
    ``rebalance_batch_usdt`` of volume (set it equal to the trade size for the
    most conservative, per-trade view). Only when ``include_withdrawal_fee``;
  * a slippage buffer for latency (books move before the orders land).

A signal is raised only when the net spread >= ``min_net_spread_pct`` and both
books are fresh.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from .config import Settings
from .models import Opportunity, OrderBook, vwap_for_base, vwap_for_quote
from .storage import Storage

log = logging.getLogger(__name__)


def compute_opportunity(settings: Settings, buy: OrderBook, sell: OrderBook,
                        now: float | None = None) -> Opportunity | None:
    """Evaluate buying on ``buy.exchange`` and selling on ``sell.exchange``.

    Returns None when either book is empty or too thin for the trade size.
    """
    if not buy.asks or not sell.bids or buy.exchange == sell.exchange:
        return None
    notional = settings.trade_size_usdt
    buy_vwap, base = vwap_for_quote(buy.asks, notional)
    if buy_vwap is None or base <= 0:
        return None
    sell_vwap = vwap_for_base(sell.bids, base)
    if sell_vwap is None:
        return None

    best_ask, best_bid = buy.asks[0][0], sell.bids[0][0]
    gross_pct = (best_bid - best_ask) / best_ask * 100
    executable_pct = (sell_vwap - buy_vwap) / buy_vwap * 100
    depth_slippage_pct = max(gross_pct - executable_pct, 0.0)
    fees_pct = (settings.taker_fee(buy.exchange) + settings.taker_fee(sell.exchange)) * 100
    asset = buy.symbol.split("/")[0]
    rebalance_cost = settings.withdrawal_fee(asset) * sell_vwap + settings.withdrawal_fee("USDT")
    withdrawal_pct = (rebalance_cost / max(settings.rebalance_batch_usdt, notional) * 100
                      if settings.include_withdrawal_fee else 0.0)
    slippage_pct = depth_slippage_pct + settings.slippage_buffer_pct
    net_pct = gross_pct - fees_pct - withdrawal_pct - slippage_pct
    return Opportunity(
        symbol=buy.symbol, buy_exchange=buy.exchange, sell_exchange=sell.exchange,
        buy_price=best_ask, sell_price=best_bid, buy_vwap=buy_vwap, sell_vwap=sell_vwap,
        base_amount=base, notional=notional, gross_pct=gross_pct, fees_pct=fees_pct,
        withdrawal_pct=withdrawal_pct, slippage_pct=slippage_pct, net_pct=net_pct,
        net_profit_usdt=net_pct / 100 * notional, detected_at=now or time.time(),
        actionable=net_pct >= settings.min_net_spread_pct,
    )


class ArbitrageDetector:
    def __init__(self, settings: Settings, books: Callable[[str], list[OrderBook]], storage: Storage | None = None,
                 on_signal: Callable[[Opportunity], Awaitable[None] | None] | None = None) -> None:
        self.settings = settings
        self._books = books
        self.storage = storage
        self.on_signal = on_signal
        self.latest: dict[tuple[str, str, str], Opportunity] = {}  # every pair, for the dashboard
        self.active_since: dict[tuple[str, str, str], float] = {}  # how long a signal has lasted
        self._last_recorded: dict[tuple[str, str, str], float] = {}
        self.evaluations = 0
        self.signals = 0

    def evaluate(self, symbol: str, now: float | None = None) -> list[Opportunity]:
        """Recompute every exchange pair for ``symbol``; return actionable ones, best first."""
        now = now or time.time()
        books = self._books(symbol)
        seen = set()
        actionable = []
        for buy in books:
            for sell in books:
                opp = compute_opportunity(self.settings, buy, sell, now)
                if opp is None:
                    continue
                seen.add(opp.key)
                self.latest[opp.key] = opp
                if opp.actionable:
                    self.active_since.setdefault(opp.key, now)
                    actionable.append(opp)
                else:
                    self.active_since.pop(opp.key, None)
        for key in [k for k in self.latest if k[0] == symbol and k not in seen]:  # stale pairs
            self.latest.pop(key, None)
            self.active_since.pop(key, None)
        self.evaluations += 1
        actionable.sort(key=lambda o: o.net_pct, reverse=True)
        return actionable

    def on_book_update(self, exchange: str, symbol: str) -> None:
        """Callback from the exchange service (runs inside the event loop)."""
        for opp in self.evaluate(symbol):
            self.signals += 1
            asyncio.get_running_loop().create_task(self._handle(opp))

    async def _handle(self, opp: Opportunity) -> None:
        now = opp.detected_at
        if self.storage is not None and now - self._last_recorded.get(opp.key, 0) >= self.settings.record_interval_seconds:
            # Record a persisting opportunity at most once per interval, not on every tick.
            self._last_recorded[opp.key] = now
            opp.id = await self.storage.a_insert_opportunity(opp)
            log.info("Opportunity %s buy %s @ %.6g sell %s @ %.6g gross %.3f%% net %.3f%% (~%.2f USDT)",
                     opp.symbol, opp.buy_exchange, opp.buy_vwap, opp.sell_exchange, opp.sell_vwap,
                     opp.gross_pct, opp.net_pct, opp.net_profit_usdt)
        if self.on_signal is not None:
            result = self.on_signal(opp)
            if asyncio.iscoroutine(result):
                await result

    def spreads(self) -> list[dict]:
        """Best (highest net) direction per symbol plus every pair, for the dashboard."""
        rows = []
        for opp in sorted(self.latest.values(), key=lambda o: (o.symbol, -o.net_pct)):
            d = opp.to_dict()
            since = self.active_since.get(opp.key)
            d["active_for"] = (time.time() - since) if since else None
            rows.append(d)
        return rows
