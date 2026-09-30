"""Order execution for arbitrage signals.

Both legs (buy on A, sell on B) are sent concurrently with ``asyncio.gather``
as IOC limit orders: they fill immediately up to a protective price or not at
all, so nothing is left resting on the book. Afterwards the fills are
reconciled:

  * both legs filled the same amount           -> ``filled``
  * one leg filled more than the other          -> the difference is closed at
    market on the exchange that over-filled     -> ``partial_hedged``
  * one leg failed, the other filled            -> the filled leg is reversed
                                                  -> ``one_leg_unwound``
  * nothing filled                              -> ``not_filled``
  * a hedge/unwind itself failed                -> ``hedge_failed``: the open
    exposure is recorded and the kill switch trips.

Paper mode (default) simulates fills by walking the live order books.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .config import Settings
from .models import Opportunity, OrderBook
from .storage import Storage

log = logging.getLogger(__name__)
EPS = 1e-9


@dataclass
class Fill:
    exchange: str
    side: str
    requested: float
    filled: float = 0.0
    avg_price: float = 0.0
    fee_quote: float = 0.0
    order_id: str | None = None
    error: str | None = None

    @property
    def cost(self) -> float:
        return self.filled * self.avg_price

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class Broker(Protocol):
    name: str

    async def balances(self) -> dict[str, float]: ...
    async def ioc(self, symbol: str, side: str, amount: float, limit_price: float) -> Fill: ...
    async def market(self, symbol: str, side: str, amount: float) -> Fill: ...
    async def cancel_open_orders(self) -> None: ...


# ---------------------------------------------------------------------------- paper
class PaperBroker:
    """Simulated account: fills against the current live order book, pays taker fees."""

    def __init__(self, name: str, settings: Settings, books: Callable[[str, str], OrderBook | None],
                 rng: random.Random | None = None) -> None:
        self.name = name
        self.settings = settings
        self._books = books
        self.rng = rng or random.Random()
        self.assets: dict[str, float] = {"USDT": settings.paper_quote_balance}
        self._seq = 0

    def ensure_asset(self, symbol: str) -> None:
        """Give the paper account its starting inventory of a coin (worth paper_base_value_usdt)."""
        base = symbol.split("/")[0]
        if base in self.assets:
            return
        book = self._books(self.name, symbol)
        if book and book.bid and book.ask:
            self.assets[base] = self.settings.paper_base_value_usdt / ((book.bid + book.ask) / 2)

    async def balances(self) -> dict[str, float]:
        return dict(self.assets)

    async def cancel_open_orders(self) -> None:  # IOC orders never rest
        return None

    async def _fill(self, symbol: str, side: str, amount: float, limit: float | None) -> Fill:
        await asyncio.sleep(0.02)  # a little latency, like a real round trip
        self._seq += 1
        fill = Fill(self.name, side, amount, order_id=f"paper-{self.name}-{self._seq}")
        if self.settings.paper_fail_rate and self.rng.random() < self.settings.paper_fail_rate:
            fill.error = "simulated exchange error"
            return fill
        book = self._books(self.name, symbol)
        if book is None:
            fill.error = "no order book"
            return fill
        base, quote = symbol.split("/")
        fee_rate = self.settings.taker_fee(self.name)
        levels = book.asks if side == "buy" else book.bids
        remaining, filled, cost = amount, 0.0, 0.0
        for price, size in levels:
            if limit is not None and ((side == "buy" and price > limit) or (side == "sell" and price < limit)):
                break
            take = min(size, remaining)
            if side == "buy":  # cannot spend more quote than the account holds
                affordable = (self.assets.get(quote, 0.0) - cost * (1 + fee_rate)) / (price * (1 + fee_rate))
                take = min(take, max(affordable, 0.0))
            else:
                take = min(take, max(self.assets.get(base, 0.0) - filled, 0.0))
            if take <= EPS:
                break
            filled += take
            cost += take * price
            remaining -= take
            if remaining <= EPS:
                break
        if filled <= EPS:
            fill.error = fill.error or "no liquidity within the limit price / insufficient balance"
            return fill
        fee = cost * fee_rate
        if side == "buy":
            self.assets[quote] = self.assets.get(quote, 0.0) - cost - fee
            self.assets[base] = self.assets.get(base, 0.0) + filled
        else:
            self.assets[base] = self.assets.get(base, 0.0) - filled
            self.assets[quote] = self.assets.get(quote, 0.0) + cost - fee
        fill.filled, fill.avg_price, fill.fee_quote = filled, cost / filled, fee
        return fill

    async def ioc(self, symbol: str, side: str, amount: float, limit_price: float) -> Fill:
        return await self._fill(symbol, side, amount, limit_price)

    async def market(self, symbol: str, side: str, amount: float) -> Fill:
        return await self._fill(symbol, side, amount, None)


# ---------------------------------------------------------------------------- live
class LiveBroker:
    """Real orders through an authenticated ccxt.pro client."""

    def __init__(self, name: str, client: Any, settings: Settings) -> None:
        self.name = name
        self.client = client
        self.settings = settings

    async def balances(self) -> dict[str, float]:
        bal = await self.client.fetch_balance()
        return {k: float(v) for k, v in (bal.get("free") or {}).items() if v}

    async def cancel_open_orders(self) -> None:
        try:
            for order in await self.client.fetch_open_orders():
                await self.client.cancel_order(order["id"], order["symbol"])
        except Exception as exc:  # noqa: BLE001 - best effort during a kill switch
            log.error("%s: could not cancel open orders: %s", self.name, exc)

    def _to_fill(self, side: str, amount: float, order: dict[str, Any]) -> Fill:
        filled = float(order.get("filled") or 0.0)
        avg = float(order.get("average") or order.get("price") or 0.0)
        fee = 0.0
        for f in order.get("fees") or ([order["fee"]] if order.get("fee") else []):
            if f and f.get("cost"):
                cost = float(f["cost"])
                cur = f.get("currency")
                quote = order.get("symbol", "/").split("/")[-1]
                fee += cost if cur == quote else cost * avg if cur == order.get("symbol", "/").split("/")[0] else 0.0
        if filled and not fee:
            fee = filled * avg * self.settings.taker_fee(self.name)  # estimate when not reported
        return Fill(self.name, side, amount, filled, avg, fee, order.get("id"))

    async def _order(self, symbol: str, side: str, amount: float, price: float | None) -> Fill:
        c = self.client
        try:
            qty = float(c.amount_to_precision(symbol, amount))
            if price is None:
                order = await c.create_order(symbol, "market", side, qty)
            else:
                px = float(c.price_to_precision(symbol, price))
                order = await c.create_order(symbol, "limit", side, qty, px, {"timeInForce": "IOC"})
            if order.get("status") not in ("closed", "canceled", "expired") or order.get("filled") is None:
                await asyncio.sleep(0.3)
                order = await c.fetch_order(order["id"], symbol)
            return self._to_fill(side, amount, order)
        except Exception as exc:  # noqa: BLE001 - reported as a failed leg
            return Fill(self.name, side, amount, error=f"{type(exc).__name__}: {str(exc)[:300]}")

    async def ioc(self, symbol: str, side: str, amount: float, limit_price: float) -> Fill:
        return await self._order(symbol, side, amount, limit_price)

    async def market(self, symbol: str, side: str, amount: float) -> Fill:
        return await self._order(symbol, side, amount, None)


# ---------------------------------------------------------------------------- executor
@dataclass
class ExecutorState:
    trading_enabled: bool = True
    killed: bool = False
    kill_reason: str | None = None
    in_flight: dict[str, dict[str, Any]] = field(default_factory=dict)
    exposures: list[dict[str, Any]] = field(default_factory=list)  # unhedged residuals
    last_skip: dict[str, str] = field(default_factory=dict)
    executions: int = 0
    day: str = ""
    day_pnl: float = 0.0


class Executor:
    def __init__(self, settings: Settings, storage: Storage, brokers: dict[str, Broker], mode: str = "paper",
                 on_kill: Callable[[str], None] | None = None) -> None:
        self.settings = settings
        self.storage = storage
        self.brokers = brokers
        self.mode = mode
        self.state = ExecutorState()
        self.on_kill = on_kill
        self._cooldown: dict[tuple[str, str, str], float] = {}
        self._busy: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ control
    def kill(self, reason: str) -> None:
        """Block all new orders immediately. In-flight trades still finish their hedge."""
        if not self.state.killed:
            log.critical("KILL SWITCH: %s", reason)
        self.state.killed, self.state.kill_reason = True, reason
        if self.on_kill:
            self.on_kill(reason)

    def reset_kill(self) -> None:
        self.state.killed, self.state.kill_reason = False, None
        log.warning("Kill switch reset by user")

    def _skip(self, opp: Opportunity, reason: str) -> None:
        self.state.last_skip[opp.symbol] = reason
        log.debug("Skip %s %s->%s: %s", opp.symbol, opp.buy_exchange, opp.sell_exchange, reason)

    def _roll_day(self) -> None:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if self.state.day != today:
            self.state.day, self.state.day_pnl = today, 0.0

    # ------------------------------------------------------------------ entry point
    def submit(self, opp: Opportunity) -> asyncio.Task | None:
        """Called for every actionable signal; starts an execution when allowed."""
        self._roll_day()
        if self.state.killed:
            return self._skip(opp, f"kill switch: {self.state.kill_reason}")
        if not self.state.trading_enabled:
            return self._skip(opp, "trading disabled")
        if opp.symbol in self._busy:
            return self._skip(opp, "a trade on this symbol is in progress")
        if time.time() - self._cooldown.get(opp.key, 0) < self.settings.cooldown_seconds:
            return self._skip(opp, "cooldown")
        if self.state.day_pnl <= -self.settings.max_daily_loss_usdt:
            self.kill(f"daily loss limit {self.settings.max_daily_loss_usdt} USDT reached")
            return None
        if opp.buy_exchange not in self.brokers or opp.sell_exchange not in self.brokers:
            return self._skip(opp, "no broker for exchange")
        self._busy.add(opp.symbol)
        task = asyncio.get_running_loop().create_task(self._run(opp))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _run(self, opp: Opportunity) -> None:
        try:
            await self.execute(opp)
        except Exception:  # noqa: BLE001
            log.exception("Execution crashed for %s", opp.symbol)
            self.kill(f"execution error on {opp.symbol}; check positions")
        finally:
            self._busy.discard(opp.symbol)
            self._cooldown[opp.key] = time.time()

    async def wait_idle(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # ------------------------------------------------------------------ one arbitrage
    async def execute(self, opp: Opportunity) -> dict[str, Any] | None:
        buy_b, sell_b = self.brokers[opp.buy_exchange], self.brokers[opp.sell_exchange]
        base, quote = opp.symbol.split("/")
        for b in (buy_b, sell_b):
            if isinstance(b, PaperBroker):
                b.ensure_asset(opp.symbol)

        # Inventory check: cross-exchange arbitrage needs quote on the buy side and coin on the sell side.
        buy_bal, sell_bal = await asyncio.gather(buy_b.balances(), sell_b.balances())
        need_quote = opp.notional * (1 + self.settings.taker_fee(opp.buy_exchange)) * 1.01
        amount = opp.base_amount
        if buy_bal.get(quote, 0.0) < need_quote:
            self._skip(opp, f"not enough {quote} on {opp.buy_exchange}")
            return None
        if sell_bal.get(base, 0.0) < amount:
            self._skip(opp, f"not enough {base} on {opp.sell_exchange}")
            return None

        # Protective limit prices: never give away more than half the expected net edge each side.
        tol = min(self.settings.price_tolerance_pct, max(opp.net_pct, 0.0) / 2) / 100
        buy_limit, sell_limit = opp.buy_vwap * (1 + tol), opp.sell_vwap * (1 - tol)
        started = time.time()
        self.state.in_flight[opp.symbol] = {"symbol": opp.symbol, "buy": opp.buy_exchange,
                                             "sell": opp.sell_exchange, "amount": amount, "since": started}
        log.info("[%s] EXECUTE %s: buy %.8g on %s <= %.6g | sell on %s >= %.6g (net %.3f%%)",
                 self.mode.upper(), opp.symbol, amount, opp.buy_exchange, buy_limit, opp.sell_exchange,
                 sell_limit, opp.net_pct)
        try:
            buy_fill, sell_fill = await asyncio.gather(
                buy_b.ioc(opp.symbol, "buy", amount, buy_limit),
                sell_b.ioc(opp.symbol, "sell", amount, sell_limit),
            )
            legs = [buy_fill, sell_fill]
            status, hedges = await self._reconcile(opp, buy_fill, sell_fill)
            legs += hedges
        finally:
            self.state.in_flight.pop(opp.symbol, None)

        bought = sum(f.cost + f.fee_quote for f in legs if f.side == "buy")
        sold = sum(f.cost - f.fee_quote for f in legs if f.side == "sell")
        fees = sum(f.fee_quote for f in legs)
        # Any coin left unhedged (only after a failed hedge) is valued at the mid price, so an
        # open short never shows up as profit and an open long never as a loss of its full cost.
        net_base = sum(f.filled for f in legs if f.side == "buy") - sum(f.filled for f in legs if f.side == "sell")
        mark = (opp.buy_vwap + opp.sell_vwap) / 2
        pnl = sold - bought + net_base * mark if status != "not_filled" else 0.0
        self.state.day_pnl += pnl
        self.state.executions += 1
        row = {
            "ts": started, "opportunity_id": opp.id, "mode": self.mode, "symbol": opp.symbol,
            "buy_exchange": opp.buy_exchange, "sell_exchange": opp.sell_exchange, "status": status,
            "buy_filled": buy_fill.filled, "buy_avg": buy_fill.avg_price or None,
            "sell_filled": sell_fill.filled, "sell_avg": sell_fill.avg_price or None,
            "fees_usdt": fees, "pnl_usdt": pnl,
            "detail": {"legs": [f.to_dict() for f in legs], "expected_net_pct": opp.net_pct,
                       "elapsed_ms": round((time.time() - started) * 1000)},
        }
        row["id"] = await self.storage.a_insert_execution(row)
        if opp.id:
            await self.storage.a_mark_executed(opp.id)
        log.info("[%s] %s %s -> %s pnl %.4f USDT (fees %.4f)", self.mode.upper(), opp.symbol, status,
                 "ok" if status in ("filled", "partial_hedged") else "check", pnl, fees)
        if self.state.day_pnl <= -self.settings.max_daily_loss_usdt:
            self.kill(f"daily loss limit {self.settings.max_daily_loss_usdt} USDT reached")
        return row

    async def _reconcile(self, opp: Opportunity, buy: Fill, sell: Fill) -> tuple[str, list[Fill]]:
        """Bring the net coin exposure back to zero after the two legs."""
        diff = buy.filled - sell.filled
        if buy.filled <= EPS and sell.filled <= EPS:
            return "not_filled", []
        if abs(diff) <= max(buy.filled, sell.filled) * 1e-6:
            return "filled", []
        one_leg = buy.filled <= EPS or sell.filled <= EPS
        if diff > 0:  # bought more than sold: sell the excess back where it was bought
            hedge = await self.brokers[opp.buy_exchange].market(opp.symbol, "sell", diff)
        else:  # sold more than bought: buy the shortfall back where it was sold
            hedge = await self.brokers[opp.sell_exchange].market(opp.symbol, "buy", -diff)
        residual = abs(diff) - hedge.filled
        if hedge.error or residual > abs(diff) * 1e-6:
            exposure = {"symbol": opp.symbol, "exchange": hedge.exchange, "side": hedge.side,
                        "amount": residual, "error": hedge.error, "ts": time.time()}
            self.state.exposures.append(exposure)
            self.kill(f"could not close {residual:.8g} {opp.symbol} on {hedge.exchange}: {hedge.error}")
            return "hedge_failed", [hedge]
        log.warning("%s %s: legs filled %.8g / %.8g, closed the difference on %s",
                    opp.symbol, "one leg failed" if one_leg else "partial fill", buy.filled, sell.filled,
                    hedge.exchange)
        return ("one_leg_unwound" if one_leg else "partial_hedged"), [hedge]
