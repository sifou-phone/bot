"""Market data: download OHLCV from an exchange, CSV cache, synthetic data."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .metrics import timeframe_seconds

log = logging.getLogger(__name__)
COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
#: Optional 7th column: base volume bought by market (taker) buy orders. Binance reports it,
#: which gives a real buy/sell delta per candle instead of one estimated from the candle shape.
TAKER_BUY = "taker_buy"


def ohlcv_to_frame(rows: list[list[Any]]) -> pd.DataFrame:
    cols = COLUMNS + [TAKER_BUY] if rows and len(rows[0]) > len(COLUMNS) else COLUMNS
    df = pd.DataFrame(rows, columns=cols)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()
    return df.astype(float)


def _binance_spot(exchange: Any, symbol: str) -> dict[str, Any] | None:
    if getattr(exchange, "id", "") != "binance" or not hasattr(exchange, "publicGetKlines"):
        return None
    exchange.load_markets()
    market = exchange.market(symbol)
    return market if market.get("spot") else None


def max_batch(exchange: Any, symbol: str = "") -> int:
    """Candles per request: Binance serves 1000, most exchanges 300 or fewer."""
    return 1000 if getattr(exchange, "id", "") == "binance" else 300


def fetch_candles_raw(exchange: Any, symbol: str, timeframe: str, since: int | None = None,
                      limit: int | None = None) -> list[list[Any]]:
    """OHLCV rows from a ccxt exchange, plus taker-buy volume when available (Binance spot)."""
    market = _binance_spot(exchange, symbol)
    if market is None:
        return exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
    req: dict[str, Any] = {"symbol": market["id"], "interval": exchange.timeframes[timeframe]}
    if since is not None:
        req["startTime"] = int(since)
    if limit:
        req["limit"] = min(int(limit), 1000)
    # kline: [open time, open, high, low, close, volume, close time, quote vol, trades, taker buy base, ...]
    return [[int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[9])]
            for k in exchange.publicGetKlines(req)]


def fetch_history(exchange: Any, symbol: str, timeframe: str, since: str,
                  until: str = "", batch: int | None = None) -> pd.DataFrame:
    """Page through the exchange's candles from ``since`` to ``until``."""
    batch = batch or max_batch(exchange)
    since_ms = int(pd.Timestamp(since, tz="UTC").timestamp() * 1000)
    until_ms = int(pd.Timestamp(until, tz="UTC").timestamp() * 1000) if until else None
    step = timeframe_seconds(timeframe) * 1000
    rows: list[list[Any]] = []
    while True:
        chunk = fetch_candles_raw(exchange, symbol, timeframe, since=since_ms, limit=batch)
        if not chunk:
            break
        rows.extend(chunk)
        last = chunk[-1][0]
        log.info("Downloaded %d candles up to %s", len(rows), pd.Timestamp(last, unit="ms", tz="UTC"))
        if (until_ms and last >= until_ms) or last + step > time.time() * 1000:
            break
        since_ms = last + step
        time.sleep(getattr(exchange, "rateLimit", 200) / 1000)
    df = ohlcv_to_frame(rows)
    if until_ms:
        df = df[df.index < pd.Timestamp(until_ms, unit="ms", tz="UTC")]
    return df


def save_csv(df: pd.DataFrame, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path)


def load_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    ts = df.columns[0]
    df[ts] = pd.to_datetime(df[ts], utc=True)
    df = df.rename(columns={ts: "timestamp"}).set_index("timestamp").sort_index()
    df.columns = [c.lower() for c in df.columns]
    missing = {"open", "high", "low", "close"} - set(df.columns)
    if missing:
        raise ValueError(f"CSV {path} is missing columns: {sorted(missing)}")
    if "volume" not in df:
        df["volume"] = 0.0
    cols = COLUMNS[1:] + ([TAKER_BUY] if TAKER_BUY in df else [])
    return df[cols].astype(float)


def synthetic_ohlcv(bars: int = 3000, timeframe: str = "1h", start_price: float = 30_000.0,
                    seed: int = 42, start: str = "2024-01-01") -> pd.DataFrame:
    """Random-walk candles with trending regimes; handy for demos and tests."""
    rng = np.random.default_rng(seed)
    regime = np.repeat(rng.normal(0, 0.0015, bars // 200 + 1), 200)[:bars]
    rets = regime + rng.normal(0, 0.008, bars)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start_price], close[:-1]])
    spread = np.abs(rng.normal(0, 0.004, bars))
    high = np.maximum(open_, close) * (1 + spread)
    low = np.minimum(open_, close) * (1 - spread)
    index = pd.date_range(start, periods=bars, freq=pd.Timedelta(seconds=timeframe_seconds(timeframe)), tz="UTC")
    volume = rng.lognormal(3, 0.5, bars)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume},
                        index=index.rename("timestamp"))


def fetch_recent(exchange: Any, symbol: str, timeframe: str, limit: int,
                 batch: int | None = None) -> pd.DataFrame:
    """The latest ``limit`` candles, paging forward because exchanges cap each request."""
    batch = batch or max_batch(exchange)
    step = timeframe_seconds(timeframe) * 1000
    now_ms = time.time() * 1000
    since = int(now_ms - (limit + 1) * step)
    rows: list[list[Any]] = []
    last_seen = None
    while True:
        chunk = fetch_candles_raw(exchange, symbol, timeframe, since=since, limit=batch)
        if not chunk:
            break
        rows.extend(chunk)
        last = chunk[-1][0]
        if (last_seen is not None and last <= last_seen) or last + step > now_ms:
            break
        last_seen, since = last, last + step
    if not rows:
        return pd.DataFrame(columns=COLUMNS[1:], index=pd.DatetimeIndex([], tz="UTC", name="timestamp"))
    return ohlcv_to_frame(rows).tail(limit)


class CandleCache:
    """Keeps recent candles per symbol and only downloads the newest ones on each call.

    The last cached candles are always re-fetched because the newest one may still
    have been forming when it was stored.
    """

    def __init__(self, exchange: Any, batch: int | None = None) -> None:
        self.exchange = exchange
        self.batch = batch or max_batch(exchange)
        self._frames: dict[tuple[str, str], pd.DataFrame] = {}

    def get(self, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
        key = (symbol, timeframe)
        cached = self._frames.get(key)
        step = timeframe_seconds(timeframe)
        stale = (cached is None or len(cached) < limit
                 or time.time() - cached.index[-1].timestamp() > step * (self.batch - 5))
        if stale:
            df = fetch_recent(self.exchange, symbol, timeframe, limit, self.batch)
        else:
            since = int(cached.index[-2].timestamp() * 1000)
            new = ohlcv_to_frame(fetch_candles_raw(self.exchange, symbol, timeframe, since, self.batch))
            df = cached if new.empty else pd.concat([cached[cached.index < new.index[0]], new]).tail(limit)
        self._frames[key] = df
        return df
