import pytest

from tradebot.config import CostsConfig, RiskConfig
from tradebot.risk import RiskManager


def rm(**kw):
    return RiskManager(RiskConfig(**kw), CostsConfig(fee_rate=0.0, slippage=0.0))


def test_position_size_risks_fixed_fraction():
    plan = rm(risk_per_trade=0.01, stop_atr_mult=2, max_position_pct=1).plan_entry(10_000, 10_000, 100, 2)
    assert plan.stop == 96
    assert plan.qty * (plan.entry - plan.stop) == pytest.approx(100)  # 1% of equity
    assert plan.take_profit == 108  # 2R


def test_position_capped_by_max_pct_and_cash():
    plan = rm(risk_per_trade=0.05, max_position_pct=0.25).plan_entry(10_000, 10_000, 100, 0.1)
    assert plan.qty * 100 == pytest.approx(2_500)
    plan = rm(risk_per_trade=0.05, max_position_pct=1).plan_entry(10_000, 1_000, 100, 0.1)
    assert plan.qty * 100 == pytest.approx(1_000)


def test_rejects_tiny_or_invalid():
    r = rm(min_notional=10)
    assert r.plan_entry(100, 5, 100, 1) is None
    assert r.plan_entry(10_000, 10_000, 100, float("nan")) is None


def test_trailing_stop_only_moves_up():
    r = rm(trailing_atr_mult=2)
    assert r.trail_stop(90, 100, 2) == 96
    assert r.trail_stop(98, 100, 2) == 98
    assert rm(trailing_atr_mult=0).trail_stop(90, 100, 2) == 90


def test_circuit_breakers():
    r = rm(max_drawdown=0.2, daily_loss_limit=0.03)
    assert r.halt_reason(10_000, 10_000, 10_000) is None
    assert "daily" in r.halt_reason(9_600, 10_000, 10_000)
    assert "drawdown" in r.halt_reason(7_900, 7_900, 10_000)
