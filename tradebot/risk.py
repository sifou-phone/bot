"""Position sizing, stops and account-level circuit breakers."""

from __future__ import annotations

from dataclasses import dataclass

from .config import CostsConfig, RiskConfig


@dataclass
class TradePlan:
    qty: float
    entry: float
    stop: float
    take_profit: float | None


class RiskManager:
    def __init__(self, risk: RiskConfig, costs: CostsConfig) -> None:
        self.cfg = risk
        self.costs = costs

    def plan_entry(self, equity: float, cash: float, price: float, atr: float) -> TradePlan | None:
        """Size a long entry so that hitting the stop loses ``risk_per_trade`` of equity."""
        if price <= 0 or atr != atr or atr <= 0 or equity <= 0:  # atr != atr -> NaN
            return None
        stop_distance = atr * self.cfg.stop_atr_mult
        stop = price - stop_distance
        if stop <= 0:
            return None
        # Loss per unit if stopped: price move plus fees on both sides.
        loss_per_unit = stop_distance + price * self.costs.fee_rate * 2
        qty = equity * self.cfg.risk_per_trade / loss_per_unit
        max_notional = min(equity * self.cfg.max_position_pct, cash / (1 + self.costs.fee_rate))
        qty = min(qty, max_notional / price)
        if qty * price < self.cfg.min_notional:
            return None
        tp = price + stop_distance * self.cfg.take_profit_rr if self.cfg.take_profit_rr > 0 else None
        return TradePlan(qty=qty, entry=price, stop=stop, take_profit=tp)

    def trail_stop(self, current_stop: float, close: float, atr: float) -> float:
        """Ratchet the stop upward only; never loosen it."""
        if self.cfg.trailing_atr_mult <= 0 or atr != atr:
            return current_stop
        return max(current_stop, close - atr * self.cfg.trailing_atr_mult)

    def halt_reason(self, equity: float, day_start_equity: float, peak_equity: float) -> str | None:
        """Return why new entries are blocked, or None when trading is allowed."""
        if peak_equity > 0 and 1 - equity / peak_equity >= self.cfg.max_drawdown:
            return f"max drawdown {self.cfg.max_drawdown:.0%} reached"
        if day_start_equity > 0 and 1 - equity / day_start_equity >= self.cfg.daily_loss_limit:
            return f"daily loss limit {self.cfg.daily_loss_limit:.0%} reached"
        return None
