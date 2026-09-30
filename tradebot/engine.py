"""Live / paper trading loop.

Every ``poll_seconds``:
  1. check the open position's stop-loss / take-profit against the last price;
  2. when a new candle has *closed*, recompute signals, trail the stop and act
     on the latest signal with a market order;
  3. update equity, circuit breakers and persist state to disk.
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from . import indicators as ind
from .config import BotConfig
from .metrics import timeframe_seconds
from .notifier import Notifier
from .risk import RiskManager
from .snapshot import SnapshotWriter
from .state import BotState, Position
from .strategies import BUY, SELL, Strategy

log = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self, cfg: BotConfig, exchange: Any, strategy: Strategy,
                 notifier: Notifier | None = None, state: BotState | None = None) -> None:
        self.cfg = cfg
        self.exchange = exchange
        self.strategy = strategy
        self.risk = RiskManager(cfg.risk, cfg.costs)
        self.notifier = notifier or Notifier(cfg.telegram)
        self.state = state if state is not None else BotState.load(cfg.state_file)
        self.tf_seconds = timeframe_seconds(cfg.timeframe)
        self._running = False
        self.snapshot = SnapshotWriter(Path(cfg.state_file).parent)
        self.last_candidates: list[Any] = []  # latest scanner results (hunter mode)
        self.last_scan_at: float | None = None

    # ------------------------------------------------------------------ helpers
    def equity(self, price: float) -> float:
        quote, _ = self.exchange.balances()
        pos = self.state.position
        return quote + (pos.qty * price if pos else 0.0)

    def closed_candles(self, now: float) -> pd.DataFrame:
        limit = max(self.cfg.history_bars, self.strategy.warmup + 50)
        df = self.exchange.fetch_candles(self.cfg.timeframe, limit + 1)
        # Keep only candles whose period has fully elapsed.
        cutoff = pd.Timestamp(now - self.tf_seconds, unit="s", tz="UTC")
        return df[df.index <= cutoff]

    def _save(self) -> None:
        if hasattr(self.exchange, "quote_balance"):  # persist simulated paper balances
            self.state.paper_quote = self.exchange.quote_balance
            self.state.paper_base = self.exchange.base_balance
        self.state.save(self.cfg.state_file)

    # ------------------------------------------------------------------ actions
    def open_long(self, price: float, atr: float, now: float, stop_hint: float | None = None,
                  note: str = "") -> bool:
        quote, _ = self.exchange.balances()
        plan = self.risk.plan_entry(self.equity(price), quote, price, atr, stop_hint)
        if plan is None:
            log.info("Entry skipped: stop invalid, position too small or ATR unavailable")
            return False
        fill = self.exchange.market_buy(plan.qty)
        if fill["qty"] <= 0:
            log.warning("Buy order returned no fill: %s", fill)
            return False
        # Re-anchor stop/TP on the actual fill price.
        shift = fill["price"] - plan.entry
        self.state.position = Position(
            qty=fill["qty"], entry=fill["price"], stop=plan.stop + shift,
            take_profit=plan.take_profit + shift if plan.take_profit else None,
            opened_at=datetime.fromtimestamp(now, timezone.utc).isoformat(),
            entry_fee=fill["fee"], order_id=fill["id"], symbol=self.cfg.symbol,
            initial_stop=plan.stop + shift,
        )
        self._save()
        p = self.state.position
        tp = f"{p.take_profit:.6g}" if p.take_profit else "follow liquidity"
        self.notifier.send(f"🟢 BUY {self.cfg.symbol}\nqty {p.qty:.6f} @ {p.entry:.6g}\n"
                           f"stop {p.stop:.6g} ({(p.stop / p.entry - 1) * 100:.2f}%) | tp {tp}"
                           + (f"\n{note}" if note else ""))
        return True

    def close_long(self, reason: str, now: float) -> None:
        pos = self.state.position
        if pos is None:
            return
        _, base = self.exchange.balances()
        qty = min(pos.qty, base) if base > 0 else pos.qty
        fill = self.exchange.market_sell(qty)
        proceeds = fill["qty"] * fill["price"] - fill["fee"]
        cost = pos.qty * pos.entry + pos.entry_fee
        pnl = proceeds - cost
        trade = {
            "entry_time": pos.opened_at, "exit_time": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "entry": pos.entry, "exit": fill["price"], "qty": fill["qty"], "pnl": pnl,
            "return_pct": pnl / cost * 100 if cost else 0.0, "fees": pos.entry_fee + fill["fee"],
            "reason": reason, "symbol": self.cfg.symbol,
        }
        self.state.trades.append(trade)
        self.state.position = None
        self._save()
        icon = "✅" if pnl > 0 else "🔴"
        self.notifier.send(f"{icon} SELL {self.cfg.symbol} ({reason})\n"
                           f"@ {fill['price']:.4f} | PnL {pnl:+.2f} ({trade['return_pct']:+.2f}%)")

    # ------------------------------------------------------------------ loop
    def tick(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        price = self.exchange.last_price()
        pos = self.state.position

        # 1) protective exits on the live price
        if pos is not None:
            if price <= pos.stop:
                self.close_long("stop_loss", now)
            elif pos.take_profit is not None and price >= pos.take_profit:
                self.close_long("take_profit", now)

        # 2) account bookkeeping and circuit breakers
        equity = self.equity(price)
        self._update_account(equity, now)

        # 3) strategy decisions on newly closed candles
        df = self.closed_candles(now)
        if len(df) <= self.strategy.warmup:
            log.warning("Only %d closed candles, need > %d for warmup", len(df), self.strategy.warmup)
            self._save()
            return
        last_ts = df.index[-1].isoformat()
        if last_ts != self.state.last_candle:
            self.state.last_candle = last_ts
            self.on_candle(df, price, equity, now)
        self._save()
        self.publish(price, now)

    def publish(self, price: float | None, now: float) -> None:
        """Write the live snapshot read by the dashboard. Never breaks trading."""
        try:
            quote, _ = self.exchange.balances()
            pos = self.state.position
            position = None
            if pos is not None and price:
                value = pos.qty * price
                cost = pos.qty * pos.entry + pos.entry_fee
                exit_fee = value * self.cfg.costs.fee_rate
                risk = pos.entry - (pos.initial_stop or pos.stop)
                position = {
                    **pos.__dict__, "price": price, "value": value,
                    "unrealized_pnl": value - exit_fee - cost,
                    "unrealized_pct": (value - exit_fee - cost) / cost * 100 if cost else 0.0,
                    "r_multiple": (price - pos.entry) / risk if risk > 0 else None,
                    "stop_distance_pct": (pos.stop / price - 1) * 100,
                }
            equity = quote + (position["value"] if position else 0.0)
            self.snapshot.write({
                "updated": now, "mode": self.cfg.mode, "exchange": self.cfg.exchange.name,
                "strategy": self.strategy.name, "timeframe": self.cfg.timeframe, "symbol": self.cfg.symbol,
                "equity": equity, "quote": quote, "peak_equity": self.state.peak_equity,
                "day_start_equity": self.state.day_start_equity, "halted": self.state.halted,
                "position": position,
                "scanner": {"at": self.last_scan_at, "candidates": self.last_candidates},
                "risk": self.cfg.risk, "poll_seconds": self.cfg.poll_seconds,
            }, equity, now)
        except Exception as exc:  # noqa: BLE001 - the dashboard is best effort
            log.warning("Could not write dashboard snapshot: %s", exc)

    def _update_account(self, equity: float, now: float) -> None:
        today = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        if self.state.day != today:
            self.state.day, self.state.day_start_equity = today, equity
        self.state.peak_equity = max(self.state.peak_equity, equity)

    def _entry_blocked(self, equity: float) -> bool:
        if self.state.halted:
            log.warning("Entry blocked, bot halted: %s", self.state.halted)
            return True
        reason = self.risk.halt_reason(equity, self.state.day_start_equity, self.state.peak_equity)
        if reason:
            if "drawdown" in reason:
                self.state.halted = reason
                self.notifier.send(f"⛔ Trading halted: {reason}. Reset the state file to resume.")
            log.warning("Entry blocked: %s", reason)
            return True
        return False

    def on_candle(self, df: pd.DataFrame, price: float, equity: float, now: float) -> None:
        sig = int(self.strategy.generate_signals(df).iloc[-1])
        atr = float(ind.atr(df, self.cfg.risk.atr_period).iloc[-1])
        pos = self.state.position
        log.info("Candle %s close=%.4f signal=%d equity=%.2f position=%s",
                 df.index[-1], df["close"].iloc[-1], sig, equity, "yes" if pos else "no")

        if pos is not None:
            if sig == SELL:
                self.close_long("signal", now)
                return
            close = float(df["close"].iloc[-1])
            new_stop = self.risk.breakeven_stop(pos.stop, pos.entry, pos.initial_stop or pos.stop, close)
            new_stop = self.risk.trail_stop(new_stop, close, atr)
            if new_stop > pos.stop:
                log.info("Stop raised %.6g -> %.6g", pos.stop, new_stop)
                pos.stop = new_stop
            return

        if sig != BUY or self._entry_blocked(equity):
            return
        hints = self.strategy.stop_levels(df)
        self.open_long(price, atr, now, None if hints is None else float(hints.iloc[-1]))

    def run(self) -> None:
        self._running = True

        def stop(signum: int, _frame: Any) -> None:
            log.info("Signal %s received, shutting down after this tick", signum)
            self._running = False

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        pos = self.state.position
        self.notifier.send(
            f"🤖 TradeBot started ({self.cfg.mode}) {self.cfg.symbol} {self.cfg.timeframe} "
            f"strategy={self.strategy.name}" + (f"\nresuming open position qty {pos.qty:.6f}" if pos else "")
        )
        errors = 0
        while self._running:
            try:
                self.tick()
                errors = 0
            except Exception as exc:  # noqa: BLE001 - the loop must survive any single failure
                errors += 1
                log.exception("Tick failed (%d in a row)", errors)
                if errors in (1, 5) or errors % 20 == 0:
                    self.notifier.send(f"⚠️ Error ({errors} in a row): {exc}")
            self._sleep(self.cfg.poll_seconds * min(2 ** max(errors - 1, 0), 10))
        self._save()
        self.notifier.send("🛑 TradeBot stopped")

    def _sleep(self, seconds: float) -> None:
        end = time.time() + seconds
        while self._running and time.time() < end:
            time.sleep(min(1.0, end - time.time()))
