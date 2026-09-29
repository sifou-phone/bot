"""Hunter mode: scan the market every closed candle, trade the strongest breakout.

One position at a time. While flat, the scanner ranks the watch list and the best
BUY candidate is bought. While in a position, the regular engine manages it:
strict stop on the live price, break-even, trailing stop, and the strategy's
liquidity-based exit on each closed candle. Then the hunt resumes.
"""

from __future__ import annotations

import logging
import time

from .config import BotConfig
from .engine import TradingEngine
from .notifier import Notifier
from .scanner import Scanner, format_table
from .state import BotState
from .strategies import BUY, Strategy

log = logging.getLogger(__name__)


class HunterEngine(TradingEngine):
    def __init__(self, cfg: BotConfig, exchange, strategy: Strategy, scanner: Scanner,
                 notifier: Notifier | None = None, state: BotState | None = None) -> None:
        super().__init__(cfg, exchange, strategy, notifier, state)
        self.scanner = scanner
        self._last_scan_bar: int | None = None
        pos = self.state.position
        if pos is not None and pos.symbol:
            self._switch(pos.symbol)  # resume managing the open position after a restart

    def _switch(self, symbol: str) -> None:
        self.exchange.set_symbol(symbol)
        self.cfg.symbol = symbol

    def tick(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if self.state.position is not None:
            super().tick(now)
            if self.state.position is not None:
                return
        bar = int(now // self.tf_seconds)
        if bar != self._last_scan_bar:
            self._last_scan_bar = bar
            self._hunt(now)
        self.publish(None, now)

    def _hunt(self, now: float) -> None:
        quote, _ = self.exchange.balances()
        self._update_account(quote, now)
        if self._entry_blocked(quote):
            self._save()
            return
        cands = self.scanner.scan(now)
        self.last_candidates, self.last_scan_at = cands, now
        active = [c for c in cands if c.status in ("BUY", "WATCH")]
        if active:
            log.info("Scanner:\n%s", format_table(active, 10))
        for best in (c for c in cands if c.signal == BUY):
            self._switch(best.symbol)
            price = self.exchange.last_price()
            if price > best.price * (1 + self.cfg.scanner.max_chase_pct):
                log.info("Skip %s: price %.6g ran %.2f%% past the signal close", best.symbol, price,
                         (price / best.price - 1) * 100)
                continue
            note = (f"breakout of {best.resistance:.6g} | vol {best.rvol:.1f}x | flow {best.flow:+.2f} | "
                    f"1h {best.momentum * 100:+.2f}%")
            self.state.last_candle = best.last_candle  # this candle is already acted on
            if self.open_long(price, best.atr, now, best.stop, note):
                break
        self._save()
