"""Exchange access: a thin ccxt wrapper for live trading and a simulated paper broker.

Both expose the same small interface used by the trading engine:
    fetch_candles, last_price, balances, market_buy, market_sell, amount_to_precision, set_symbol
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Callable, TypeVar

import pandas as pd

from .config import CostsConfig, ExchangeConfig
from .data import CandleCache

log = logging.getLogger(__name__)
T = TypeVar("T")
BINANCE_DATA_API = "https://data-api.binance.vision/api/v3"


def create_ccxt(cfg: ExchangeConfig, authenticated: bool = True) -> Any:
    import ccxt  # imported lazily so backtests on CSV data don't require network setup

    if not hasattr(ccxt, cfg.name):
        raise ValueError(f"Unknown exchange '{cfg.name}'")
    params: dict[str, Any] = {"enableRateLimit": True, "options": dict(cfg.options)}
    if cfg.name == "binance":
        # The bot trades spot only; skip loading futures markets (other hosts, more requests).
        params["options"].setdefault("fetchMarkets", {"types": ["spot"]})
    if authenticated:
        params.update(apiKey=cfg.api_key, secret=cfg.api_secret)
        if cfg.password:
            params["password"] = cfg.password
    ex = getattr(ccxt, cfg.name)(params)
    # ccxt disables requests' ``trust_env``; re-enable it so HTTPS_PROXY / NO_PROXY and
    # REQUESTS_CA_BUNDLE are honored (corporate or TLS-inspecting proxies).
    ex.session.trust_env = True
    if not authenticated:
        url = BINANCE_DATA_API if cfg.market_data_url == "auto" and cfg.name == "binance" else cfg.market_data_url
        if url and url != "auto":
            ex.urls["api"]["public"] = url
    if cfg.sandbox and authenticated:
        ex.set_sandbox_mode(True)
    return ex


def retry(fn: Callable[[], T], attempts: int = 5, base_delay: float = 1.0) -> T:
    """Retry transient network/exchange errors with exponential backoff."""
    import ccxt

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as exc:
            if attempt == attempts:
                raise
            delay = base_delay * 2 ** (attempt - 1)
            log.warning("Transient error (%s), retry %d/%d in %.0fs", exc, attempt, attempts, delay)
            time.sleep(delay)
    raise RuntimeError("unreachable")


class LiveExchange:
    def __init__(self, cfg: ExchangeConfig, symbol: str) -> None:
        self.ex = create_ccxt(cfg)
        self.symbol = symbol
        self.candles = CandleCache(self.ex)
        retry(self.ex.load_markets)
        self.set_symbol(symbol)

    def set_symbol(self, symbol: str) -> None:
        if symbol not in self.ex.markets:
            raise ValueError(f"Symbol {symbol} is not listed on {self.ex.id}")
        self.symbol = symbol
        self.market = self.ex.market(symbol)
        self.base, self.quote = self.market["base"], self.market["quote"]

    def fetch_candles(self, timeframe: str, limit: int) -> pd.DataFrame:
        return retry(lambda: self.candles.get(self.symbol, timeframe, limit))

    def last_price(self) -> float:
        return float(retry(lambda: self.ex.fetch_ticker(self.symbol))["last"])

    def balances(self) -> tuple[float, float]:
        bal = retry(self.ex.fetch_balance)
        free = bal.get("free", {})
        return float(free.get(self.quote) or 0.0), float(free.get(self.base) or 0.0)

    def amount_to_precision(self, qty: float) -> float:
        return float(self.ex.amount_to_precision(self.symbol, qty))

    def _fill(self, order: dict[str, Any]) -> dict[str, Any]:
        # Some exchanges return a sparse order on creation; fetch it for fill details.
        if not order.get("average") and order.get("id"):
            try:
                order = retry(lambda: self.ex.fetch_order(order["id"], self.symbol))
            except Exception as exc:  # noqa: BLE001 - best effort enrichment
                log.warning("Could not fetch order %s: %s", order.get("id"), exc)
        fee = order.get("fee") or {}
        return {
            "id": order.get("id"),
            "qty": float(order.get("filled") or order.get("amount") or 0.0),
            "price": float(order.get("average") or order.get("price") or self.last_price()),
            "fee": float(fee.get("cost") or 0.0) if fee.get("currency") == self.quote else 0.0,
        }

    def market_buy(self, qty: float) -> dict[str, Any]:
        qty = self.amount_to_precision(qty)
        log.info("LIVE market BUY %s %s", qty, self.symbol)
        # Not retried: a timeout might still have placed the order, never risk a double buy.
        return self._fill(self.ex.create_market_buy_order(self.symbol, qty))

    def market_sell(self, qty: float) -> dict[str, Any]:
        qty = self.amount_to_precision(qty)
        log.info("LIVE market SELL %s %s", qty, self.symbol)
        return self._fill(self.ex.create_market_sell_order(self.symbol, qty))


class PaperExchange:
    """Uses real public market data but simulates fills, fees and slippage locally."""

    def __init__(self, cfg: ExchangeConfig, symbol: str, costs: CostsConfig,
                 quote_balance: float, base_balance: float = 0.0, market_data: Any = None) -> None:
        self.ex = market_data if market_data is not None else create_ccxt(cfg, authenticated=False)
        self.symbol = symbol
        self.costs = costs
        self.quote_balance = quote_balance
        self.base_balance = base_balance
        self._order_id = 0
        self.candles = CandleCache(self.ex)

    def set_symbol(self, symbol: str) -> None:
        if symbol == self.symbol:
            return
        if self.base_balance > 0:
            value = self.base_balance * self.last_price()
            if value > 1.0:
                raise RuntimeError(f"Cannot switch symbol while holding {self.base_balance} {self.symbol}")
            log.info("Dropping %.8f %s dust (%.4f quote)", self.base_balance, self.symbol, value)
            self.base_balance = 0.0
        self.symbol = symbol

    def fetch_candles(self, timeframe: str, limit: int) -> pd.DataFrame:
        return retry(lambda: self.candles.get(self.symbol, timeframe, limit))

    def last_price(self) -> float:
        return float(retry(lambda: self.ex.fetch_ticker(self.symbol))["last"])

    def balances(self) -> tuple[float, float]:
        return self.quote_balance, self.base_balance

    def amount_to_precision(self, qty: float) -> float:
        return math.floor(qty * 1e8 + 1e-6) / 1e8  # round down, never exceed the balance

    def _next_id(self) -> str:
        self._order_id += 1
        return f"paper-{self._order_id}"

    def market_buy(self, qty: float) -> dict[str, Any]:
        price = self.last_price() * (1 + self.costs.slippage)
        qty = self.amount_to_precision(min(qty, self.quote_balance / (price * (1 + self.costs.fee_rate))))
        fee = qty * price * self.costs.fee_rate
        self.quote_balance -= qty * price + fee
        self.base_balance += qty
        log.info("PAPER BUY %.8f %s @ %.4f (fee %.4f)", qty, self.symbol, price, fee)
        return {"id": self._next_id(), "qty": qty, "price": price, "fee": fee}

    def market_sell(self, qty: float) -> dict[str, Any]:
        price = self.last_price() * (1 - self.costs.slippage)
        qty = self.amount_to_precision(min(qty, self.base_balance))
        fee = qty * price * self.costs.fee_rate
        self.base_balance -= qty
        self.quote_balance += qty * price - fee
        log.info("PAPER SELL %.8f %s @ %.4f (fee %.4f)", qty, self.symbol, price, fee)
        return {"id": self._next_id(), "qty": qty, "price": price, "fee": fee}
