"""Plain data objects shared by the modules."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OrderBook:
    exchange: str
    symbol: str
    bids: list[tuple[float, float]]  # (price, amount), best first
    asks: list[tuple[float, float]]
    received: float = field(default_factory=time.time)  # local receive time (seconds)
    exchange_ts: float | None = None

    @property
    def bid(self) -> float | None:
        return self.bids[0][0] if self.bids else None

    @property
    def ask(self) -> float | None:
        return self.asks[0][0] if self.asks else None

    def age_ms(self, now: float | None = None) -> float:
        return ((now or time.time()) - self.received) * 1000


def vwap_for_quote(levels: list[tuple[float, float]], quote_amount: float) -> tuple[float | None, float]:
    """Average price to spend/receive ``quote_amount`` walking the book.

    Returns ``(vwap, base_filled)``; vwap is None when the book is too thin.
    """
    remaining, base, cost = quote_amount, 0.0, 0.0
    for price, amount in levels:
        if price <= 0 or amount <= 0:
            continue
        take = min(amount, remaining / price)
        base += take
        cost += take * price
        remaining -= take * price
        if remaining <= 1e-9:
            return cost / base, base
    return None, base


def vwap_for_base(levels: list[tuple[float, float]], base_amount: float) -> float | None:
    """Average price to trade ``base_amount`` walking the book, None if too thin."""
    remaining, cost = base_amount, 0.0
    for price, amount in levels:
        take = min(amount, remaining)
        cost += take * price
        remaining -= take
        if remaining <= 1e-12:
            return cost / base_amount
    return None


@dataclass
class Opportunity:
    symbol: str
    buy_exchange: str
    sell_exchange: str
    buy_price: float  # best ask on the buy exchange
    sell_price: float  # best bid on the sell exchange
    buy_vwap: float  # expected average buy price for the trade size
    sell_vwap: float
    base_amount: float
    notional: float
    gross_pct: float  # (best bid - best ask) / best ask
    fees_pct: float
    withdrawal_pct: float
    slippage_pct: float
    net_pct: float
    net_profit_usdt: float
    detected_at: float = field(default_factory=time.time)
    actionable: bool = False
    id: int | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return self.symbol, self.buy_exchange, self.sell_exchange

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in (
            "id", "symbol", "buy_exchange", "sell_exchange", "buy_price", "sell_price", "buy_vwap",
            "sell_vwap", "base_amount", "notional", "gross_pct", "fees_pct", "withdrawal_pct",
            "slippage_pct", "net_pct", "net_profit_usdt", "detected_at", "actionable")}
