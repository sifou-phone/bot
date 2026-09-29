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


def ohlcv_to_frame(rows: list[list[Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates("timestamp").set_index("timestamp").sort_index()
    return df.astype(float)


def fetch_history(exchange: Any, symbol: str, timeframe: str, since: str,
                  until: str = "", batch: int = 1000) -> pd.DataFrame:
    """Page through ``exchange.fetch_ohlcv`` (a ccxt exchange) from ``since`` to ``until``."""
    since_ms = int(pd.Timestamp(since, tz="UTC").timestamp() * 1000)
    until_ms = int(pd.Timestamp(until, tz="UTC").timestamp() * 1000) if until else None
    step = timeframe_seconds(timeframe) * 1000
    rows: list[list[Any]] = []
    while True:
        chunk = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=batch)
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
    return df[COLUMNS[1:]].astype(float)


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
