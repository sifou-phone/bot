"""Market scanner: watches the most liquid pairs and ranks the ones starting to explode.

Each closed candle it reads, for every watched pair:
  * liquidity of the candle (relative volume, who won the candle, volume-weighted flow);
  * momentum and activity over the last hour versus the day;
  * the nearest resistance / support from swing pivots;
and evaluates the strategy's signal on the last closed candle.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd

from . import indicators as ind
from .config import ScannerConfig
from .data import CandleCache
from .exchange import retry
from .levels import liquidity_flow, resistance_support
from .metrics import timeframe_seconds
from .strategies import BUY, SELL, Strategy

log = logging.getLogger(__name__)
_LEVERAGED = re.compile(r"\d+[LS]$|(UP|DOWN|BULL|BEAR)$")


@dataclass
class Candidate:
    symbol: str
    price: float
    signal: int
    status: str  # BUY | WATCH | EXIT | -
    rvol: float
    flow: float
    momentum: float
    activity: float
    resistance: float
    support: float
    stop: float
    atr: float
    score: float
    last_candle: str

    def row(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "status": self.status, "price": f"{self.price:.6g}",
            "1h %": f"{self.momentum * 100:+.2f}", "activity": f"{self.activity:.1f}x",
            "rvol": f"{self.rvol:.1f}x", "flow": f"{self.flow:+.2f}",
            "resistance": f"{self.resistance:.6g}", "support": f"{self.support:.6g}",
            "to res %": f"{(self.resistance / self.price - 1) * 100:+.2f}" if self.resistance == self.resistance else "-",
            "score": f"{self.score:.2f}",
        }


class Scanner:
    def __init__(self, market: Any, strategy: Strategy, cfg: ScannerConfig, timeframe: str = "1m",
                 history_bars: int = 1600) -> None:
        self.market = market
        self.strategy = strategy
        self.cfg = cfg
        self.timeframe = timeframe
        self.tf_seconds = timeframe_seconds(timeframe)
        self.history_bars = max(history_bars, strategy.warmup + 50)
        self.candles = CandleCache(market)
        self._universe: list[str] = []
        self._universe_at = 0.0

    # ------------------------------------------------------------------ universe
    def _eligible(self, symbol: str, ticker: dict[str, Any]) -> bool:
        base, _, quote = symbol.partition("/")
        if quote != self.cfg.quote or ":" in symbol:  # spot only
            return False
        if base in self.cfg.exclude or _LEVERAGED.search(base):
            return False
        return (ticker.get("quoteVolume") or 0) >= self.cfg.min_quote_volume_24h

    def universe(self, now: float | None = None) -> list[str]:
        if self.cfg.symbols:
            return list(self.cfg.symbols)
        now = time.time() if now is None else now
        if self._universe and now - self._universe_at < self.cfg.refresh_minutes * 60:
            return self._universe
        tickers = retry(self.market.fetch_tickers)
        ranked = sorted((s for s, t in tickers.items() if self._eligible(s, t)),
                        key=lambda s: -(tickers[s].get("quoteVolume") or 0))
        self._universe, self._universe_at = ranked[: self.cfg.universe_size], now
        log.info("Watch list (%d): %s", len(self._universe), ", ".join(self._universe))
        return self._universe

    # ------------------------------------------------------------------ analysis
    def closed_candles(self, symbol: str, now: float) -> pd.DataFrame:
        df = retry(lambda: self.candles.get(symbol, self.timeframe, self.history_bars + 1))
        return df[df.index <= pd.Timestamp(now - self.tf_seconds, unit="s", tz="UTC")]

    def evaluate(self, symbol: str, df: pd.DataFrame) -> Candidate | None:
        if len(df) <= self.strategy.warmup:
            return None
        p = self.strategy.params
        n, w = p.get("momentum_bars", 60), p.get("activity_window", 1440)
        liq = liquidity_flow(df, p.get("vol_period", 20), p.get("flow_period", 10)).iloc[-1]
        lv = resistance_support(df, p.get("pivot_left", 10), p.get("pivot_right", 3),
                                p.get("level_lookback", 120))
        quote_vol = df["volume"] * df["close"]
        close = float(df["close"].iloc[-1])
        momentum = close / float(df["close"].iloc[-1 - n]) - 1 if len(df) > n else 0.0
        activity = float(quote_vol.tail(n).sum() / (quote_vol.tail(w).sum() * n / min(w, len(df))))
        # For a breakout candle the relevant level is the one *before* it broke.
        resistance = float(lv["resistance"].iloc[-2])
        support = float(lv["support"].iloc[-1])
        signal = int(self.strategy.generate_signals(df).iloc[-1])
        hints = self.strategy.stop_levels(df)
        stop = float(hints.iloc[-1]) if hints is not None else float("nan")
        rvol, flow = float(liq["rvol"]), float(liq["flow"])

        if signal == BUY:
            status = "BUY"
        elif signal == SELL:
            status = "EXIT"
        elif (momentum > 0 and rvol >= 1.5 and resistance == resistance
              and 0 <= resistance / close - 1 <= self.cfg.watch_distance_pct):
            status = "WATCH"
        else:
            status = "-"
        # Ranking only: favour strong, active, buyer-driven moves.
        score = max(momentum, 0) * 100 * min(activity, 10) * max(flow, 0) * min(rvol, 10) ** 0.5
        return Candidate(symbol, close, signal, status, rvol, flow, momentum, activity, resistance,
                         support, stop, float(ind.atr(df, 14).iloc[-1]), score, df.index[-1].isoformat())

    def scan(self, now: float | None = None) -> list[Candidate]:
        now = time.time() if now is None else now
        out = []
        for symbol in self.universe(now):
            try:
                c = self.evaluate(symbol, self.closed_candles(symbol, now))
            except Exception as exc:  # noqa: BLE001 - one bad pair must not stop the scan
                log.warning("Scan %s failed: %s", symbol, exc)
                continue
            if c is not None:
                out.append(c)
        order = {"BUY": 0, "WATCH": 1, "-": 2, "EXIT": 3}
        out.sort(key=lambda c: (order[c.status], -c.score))
        return out


def format_table(cands: list[Candidate], limit: int = 15) -> str:
    if not cands:
        return "(no data)"
    return pd.DataFrame([c.row() for c in cands[:limit]]).to_string(index=False)
