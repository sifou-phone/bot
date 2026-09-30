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

    def plan_entry(self, equity: float, cash: float, price: float, atr: float,
                   stop_hint: float | None = None) -> TradePlan | None:
        """Size a long entry so that hitting the stop loses ``risk_per_trade`` of equity.

        ``stop_hint`` is a strategy's structural stop (e.g. under a broken level); without
        one the stop is ``stop_atr_mult`` x ATR below the price. The distance is then
        clamped to ``[min_stop_pct, max_stop_pct]`` of the price.
        """
        if price <= 0 or equity <= 0:
            return None
        cfg = self.cfg
        if stop_hint is not None and stop_hint == stop_hint:  # a structural stop (not NaN)
            if not 0 < stop_hint < price:
                return None  # price already fell through the level: the setup is void
            stop_distance = price - stop_hint
        elif atr == atr and atr > 0:
            stop_distance = atr * cfg.stop_atr_mult
        else:
            return None
        if cfg.max_stop_pct > 0:
            stop_distance = min(stop_distance, price * cfg.max_stop_pct)
        if cfg.min_stop_pct > 0:
            stop_distance = max(stop_distance, price * cfg.min_stop_pct)
        stop = price - stop_distance
        if stop <= 0:
            return None
        # Loss per unit if stopped: price move plus fees on both sides.
        loss_per_unit = stop_distance + price * self.costs.fee_rate * 2
        qty = equity * cfg.risk_per_trade / loss_per_unit
        max_notional = min(equity * cfg.max_position_pct, cash / (1 + self.costs.fee_rate))
        qty = min(qty, max_notional / price)
        if qty * price < cfg.min_notional:
            return None
        tp = price + stop_distance * cfg.take_profit_rr if cfg.take_profit_rr > 0 else None
        return TradePlan(qty=qty, entry=price, stop=stop, take_profit=tp)

    def breakeven_stop(self, current_stop: float, entry: float, initial_stop: float, price: float) -> float:
        """Once price is ``breakeven_rr`` R in profit, lock the stop at entry plus round-trip costs."""
        risk = entry - initial_stop
        if self.cfg.breakeven_rr <= 0 or risk <= 0 or price < entry + risk * self.cfg.breakeven_rr:
            return current_stop
        costs = entry * (self.costs.fee_rate + self.costs.slippage) * 2
        return max(current_stop, entry + costs)

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
