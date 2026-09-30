"""The bot controller: wires market data -> detector -> executor, owns modes and switches."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

from .config import Settings
from .detector import ArbitrageDetector
from .exchange_service import ExchangeService, make_client
from .executor import Executor, LiveBroker, PaperBroker
from .models import Opportunity
from .storage import Storage

log = logging.getLogger(__name__)
LIVE_CONFIRM_PHRASE = "LIVE"


class ModeError(Exception):
    """A mode switch that is not allowed; the message is shown to the user."""


class ArbBot:
    def __init__(self, settings: Settings, storage: Storage | None = None,
                 service: ExchangeService | None = None) -> None:
        self.settings = settings
        self.storage = storage or Storage(settings.db_path)
        self.service = service or ExchangeService(settings)
        self.service.on_update = self._on_book_update
        self.detector = ArbitrageDetector(settings, self.service.fresh_books, self.storage, self._on_signal,
                                          self.service.transfer_status)
        self.paper_brokers = {ex: PaperBroker(ex, settings, self.service.book) for ex in settings.exchanges}
        self.executor = Executor(settings, self.storage, dict(self.paper_brokers), "paper", on_kill=self._on_kill)
        self.mode = "paper"
        self.monitoring = False
        self.started_at = time.time()
        self.live_clients: dict[str, Any] = {}
        self.balances: dict[str, dict[str, float]] = {}
        self.balance_errors: dict[str, str] = {}
        self.balances_at: float | None = None
        self.events: deque[dict[str, Any]] = deque(maxlen=50)
        self._balance_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ events
    def event(self, level: str, message: str) -> None:
        self.events.appendleft({"ts": time.time(), "level": level, "message": message})
        getattr(log, "warning" if level == "warning" else "error" if level == "error" else "info")(message)

    def _on_book_update(self, exchange: str, symbol: str) -> None:
        self.detector.on_book_update(exchange, symbol)

    def _on_signal(self, opp: Opportunity) -> None:
        if self.monitoring:
            self.executor.submit(opp)

    def _on_kill(self, reason: str) -> None:
        self.event("error", f"⛔ إيقاف طارئ: {reason}")
        if self.mode == "live":
            for broker in self.executor.brokers.values():
                asyncio.get_running_loop().create_task(broker.cancel_open_orders())

    # ------------------------------------------------------------------ monitoring
    async def start_monitoring(self) -> None:
        async with self._lock:
            if self.monitoring:
                return
            await self.service.start()
            self.monitoring = True
            self.event("info", "بدأت المراقبة")
        if self._balance_task is None or self._balance_task.done():
            self._balance_task = asyncio.create_task(self._balance_loop(), name="balances")

    async def stop_monitoring(self) -> None:
        async with self._lock:
            if not self.monitoring:
                return
            self.monitoring = False
            await self.executor.wait_idle()  # let a running trade finish its hedge
            await self.service.stop()
            self.detector.latest.clear()
            self.detector.active_since.clear()
            self.event("info", "توقفت المراقبة")

    async def shutdown(self) -> None:
        await self.stop_monitoring()
        if self._balance_task:
            self._balance_task.cancel()
            await asyncio.gather(self._balance_task, return_exceptions=True)
        await self._close_live_clients()
        self.storage.close()

    # ------------------------------------------------------------------ kill switch
    def kill(self, reason: str = "manual kill switch") -> None:
        self.executor.kill(reason)

    def reset_kill(self) -> None:
        self.executor.reset_kill()
        self.event("warning", "أُعيد تفعيل التداول بعد الإيقاف الطارئ")

    # ------------------------------------------------------------------ mode
    def live_blockers(self) -> list[str]:
        """Why live trading cannot be enabled right now (empty list = allowed)."""
        reasons = []
        if self.settings.paper_mode:
            reasons.append("PAPER_MODE=true in .env; set PAPER_MODE=false and restart to allow live trading")
        missing = [ex for ex in self.settings.exchanges if not self.settings.credentials.get(ex)
                   or not self.settings.credentials[ex].configured]
        if missing:
            reasons.append("missing API keys for: " + ", ".join(missing))
        if self.executor.state.killed:
            reasons.append("the kill switch is active")
        return reasons

    async def set_mode(self, mode: str, confirm: bool = False, phrase: str = "") -> None:
        if mode not in ("paper", "live"):
            raise ModeError("mode must be 'paper' or 'live'")
        if mode == self.mode:
            return
        if self.executor.state.in_flight:
            raise ModeError("a trade is in progress, try again in a moment")
        if mode == "paper":
            self.executor.brokers = dict(self.paper_brokers)
            self.executor.mode = self.mode = "paper"
            await self._close_live_clients()
            self.event("info", "تم التبديل إلى وضع المحاكاة")
            return
        # Live: gate 1 = PAPER_MODE=false in the environment, gate 2 = explicit double confirmation.
        blockers = self.live_blockers()
        if blockers:
            raise ModeError("; ".join(blockers))
        if not confirm or phrase.strip() != LIVE_CONFIRM_PHRASE:
            raise ModeError(f"double confirmation required: tick the box and type {LIVE_CONFIRM_PHRASE}")
        brokers = {}
        try:
            for ex in self.settings.exchanges:
                client = make_client(ex, self.settings, authenticated=True)
                self.live_clients[ex] = client
                await client.load_markets()
                broker = LiveBroker(ex, client, self.settings)
                await broker.balances()  # proves the key works before any order
                brokers[ex] = broker
        except Exception as exc:
            await self._close_live_clients()
            raise ModeError(f"could not connect with API keys: {type(exc).__name__}: {str(exc)[:200]}") from exc
        self.executor.brokers = brokers
        self.executor.mode = self.mode = "live"
        self.event("warning", "⚠ تم التبديل إلى التداول الحقيقي")
        await self.refresh_balances()

    async def _close_live_clients(self) -> None:
        for client in self.live_clients.values():
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass
        self.live_clients.clear()

    # ------------------------------------------------------------------ balances
    async def refresh_balances(self) -> None:
        async def one(name: str, broker: Any) -> None:
            try:
                self.balances[name] = {k: v for k, v in (await broker.balances()).items() if abs(v) > 1e-12}
                self.balance_errors.pop(name, None)
            except Exception as exc:  # noqa: BLE001
                self.balance_errors[name] = f"{type(exc).__name__}: {str(exc)[:120]}"
        for sym in self.settings.symbols:  # paper inventory appears once prices are known
            for b in self.paper_brokers.values():
                b.ensure_asset(sym)
        await asyncio.gather(*(one(n, b) for n, b in self.executor.brokers.items()))
        self.balances_at = time.time()

    async def _balance_loop(self) -> None:
        while True:
            try:
                await self.refresh_balances()
            except Exception:  # noqa: BLE001
                log.exception("balance refresh failed")
            # Account balances (not prices) come from REST: every 30 s live, 3 s for paper.
            await asyncio.sleep(30 if self.mode == "live" else 3)

    # ------------------------------------------------------------------ dashboard view
    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        quotes = []
        for (ex, sym), book in sorted(self.service.books.items()):
            quotes.append({
                "exchange": ex, "symbol": sym, "bid": book.bid, "ask": book.ask,
                "bid_size": book.bids[0][1] if book.bids else None,
                "ask_size": book.asks[0][1] if book.asks else None,
                "age_ms": book.age_ms(now), "fresh": book.age_ms(now) <= self.settings.max_quote_age_ms,
            })
        st = self.executor.state
        counts = self.storage.counts()
        return {
            "now": now, "mode": self.mode, "monitoring": self.monitoring, "uptime": now - self.started_at,
            "killed": st.killed, "kill_reason": st.kill_reason, "live_blockers": self.live_blockers(),
            "exchanges": {ex: {**s, "symbols": sorted(self.service.markets.get(ex, []))}
                          for ex, s in self.service.status.items()},
            "quotes": quotes,
            "suspended": [{"exchange": ex, "coin": coin, **st} for (ex, coin), st in sorted(self.service.transfers.items())
                          if False in st.values()],
            "spreads": self.detector.spreads(),
            "opportunities": self.storage.recent_opportunities(50),
            "executions": self.storage.recent_executions(50),
            "balances": self.balances, "balance_errors": self.balance_errors, "balances_at": self.balances_at,
            "in_flight": list(st.in_flight.values()), "exposures": st.exposures, "last_skip": st.last_skip,
            "stats": {**counts, "day_pnl": st.day_pnl, "total_pnl": self.storage.pnl_since(0),
                      "evaluations": self.detector.evaluations, "signals": self.detector.signals},
            "events": list(self.events),
            "settings": self.settings.public_dict(),
            "live_confirm_phrase": LIVE_CONFIRM_PHRASE,
        }
