"""Real-time order books from several exchanges over WebSocket (ccxt.pro).

One task per (exchange, symbol) keeps ``watch_order_book`` streaming; there is
no REST polling of prices. Each update is stored and handed to a callback
(the detector). Streams reconnect with exponential backoff on errors.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Callable

import ccxt.pro as ccxtpro

from .config import PUBLIC_DATA_OVERRIDES, Settings
from .models import OrderBook

log = logging.getLogger(__name__)


def make_client(name: str, settings: Settings, authenticated: bool = False) -> Any:
    """Create a ccxt.pro client. Public clients never receive API keys."""
    params: dict[str, Any] = {"enableRateLimit": True, "options": {}}
    if name in ("binance", "bybit"):
        params["options"]["fetchMarkets"] = {"types": ["spot"]}
    params["options"]["defaultType"] = "spot"
    if authenticated:
        creds = settings.credentials.get(name)
        if not creds or not creds.configured:
            raise ValueError(f"No API key configured for {name}")
        params.update(apiKey=creds.api_key, secret=creds.secret)
        if creds.password:
            params["password"] = creds.password
    client = getattr(ccxtpro, name)(params)
    # Honour HTTPS_PROXY and a custom CA bundle (corporate / inspecting proxies).
    client.aiohttp_trust_env = True
    ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if ca and os.path.isfile(ca):
        client.cafile = ca
    if not authenticated and settings.use_public_data_endpoints and name in PUBLIC_DATA_OVERRIDES:
        urls = PUBLIC_DATA_OVERRIDES[name]
        if "rest" in urls:
            client.urls["api"]["public"] = urls["rest"]
        if "ws" in urls:
            if isinstance(client.urls["api"]["ws"], dict):
                client.urls["api"]["ws"]["spot"] = urls["ws"]
            else:
                client.urls["api"]["ws"] = urls["ws"]
    return client


class ExchangeService:
    def __init__(self, settings: Settings, on_update: Callable[[str, str], None] | None = None,
                 client_factory: Callable[[str], Any] | None = None) -> None:
        self.settings = settings
        self.on_update = on_update
        self._factory = client_factory or (lambda name: make_client(name, settings))
        self.clients: dict[str, Any] = {}
        self.books: dict[tuple[str, str], OrderBook] = {}
        self.markets: dict[str, set[str]] = {}
        # (exchange, coin) -> {"deposit": bool | None, "withdraw": bool | None}; None = not published
        self.transfers: dict[tuple[str, str], dict[str, bool | None]] = {}
        self.status: dict[str, dict[str, Any]] = {
            ex: {"connected": False, "error": None, "updates": 0, "last_update": None} for ex in settings.exchanges}
        self._tasks: list[asyncio.Task] = []
        self.running = False

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        for ex in self.settings.exchanges:
            self._tasks.append(asyncio.create_task(self._run_exchange(ex), name=f"exchange:{ex}"))
        log.info("Market data started for %s on %s", self.settings.symbols, self.settings.exchanges)

    async def stop(self) -> None:
        self.running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        for name, client in list(self.clients.items()):
            try:
                await client.close()
            except Exception as exc:  # noqa: BLE001
                log.debug("close %s: %s", name, exc)
        self.clients.clear()
        for st in self.status.values():
            st["connected"] = False
        log.info("Market data stopped")

    # ------------------------------------------------------------------ streams
    async def _run_exchange(self, name: str) -> None:
        delay = 1.0
        while self.running:
            try:
                client = self._factory(name)
                self.clients[name] = client
                await client.load_markets()
                available = {s for s in self.settings.symbols if s in client.markets}
                self.markets[name] = available
                self._read_transfers(name, client)
                missing = set(self.settings.symbols) - available
                if missing:
                    log.warning("%s does not list %s", name, sorted(missing))
                await asyncio.gather(self._refresh_transfers(name, client),
                                     *(self._watch(name, client, sym) for sym in available))
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep retrying the connection
                self.status[name].update(connected=False, error=f"{type(exc).__name__}: {str(exc)[:200]}")
                log.warning("%s connection failed (%s), retry in %.0fs", name, exc, delay)
                await self._close(name)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    def _read_transfers(self, name: str, client: Any) -> None:
        coins = {s.split("/")[0] for s in self.settings.symbols} | {"USDT"}
        for coin in coins:
            cur = (client.currencies or {}).get(coin) or {}
            status = {"deposit": cur.get("deposit"), "withdraw": cur.get("withdraw")}
            old = self.transfers.get((name, coin))
            self.transfers[(name, coin)] = status
            if False in status.values() and old != status:
                log.warning("%s: %s transfers suspended %s; routes needing them are blocked", name, coin, status)

    async def _refresh_transfers(self, name: str, client: Any) -> None:
        """Re-read deposit/withdraw status periodically (REST; it is account metadata, not prices)."""
        while self.running:
            await asyncio.sleep(self.settings.transfer_refresh_minutes * 60)
            try:
                client.currencies = await client.fetch_currencies() or client.currencies
                self._read_transfers(name, client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - many exchanges publish this only with API keys
                log.debug("%s: transfer status not available: %s", name, exc)

    def transfer_status(self, exchange: str, coin: str) -> dict[str, bool | None]:
        return self.transfers.get((exchange, coin), {})

    async def _watch(self, name: str, client: Any, symbol: str) -> None:
        delay = 1.0
        depth = self.settings.order_book_depth
        while self.running:
            try:
                ob = await client.watch_order_book(symbol)
                book = OrderBook(
                    name, symbol,
                    [(float(p), float(a)) for p, a, *_ in ob["bids"][:depth]],
                    [(float(p), float(a)) for p, a, *_ in ob["asks"][:depth]],
                    time.time(), (ob.get("timestamp") or 0) / 1000 or None,
                )
                self.books[(name, symbol)] = book
                st = self.status[name]
                st.update(connected=True, error=None, last_update=book.received)
                st["updates"] += 1
                delay = 1.0
                if self.on_update:
                    self.on_update(name, symbol)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a single stream must not stop the others
                self.status[name].update(connected=False, error=f"{type(exc).__name__}: {str(exc)[:200]}")
                self.books.pop((name, symbol), None)  # never trade on a stale book
                log.warning("%s %s stream error (%s), retry in %.0fs", name, symbol, exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    async def _close(self, name: str) -> None:
        client = self.clients.pop(name, None)
        if client is not None:
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ queries
    def book(self, exchange: str, symbol: str) -> OrderBook | None:
        return self.books.get((exchange, symbol))

    def fresh_books(self, symbol: str, now: float | None = None) -> list[OrderBook]:
        now = now or time.time()
        return [b for (ex, sym), b in self.books.items()
                if sym == symbol and b.bids and b.asks and b.age_ms(now) <= self.settings.max_quote_age_ms]
