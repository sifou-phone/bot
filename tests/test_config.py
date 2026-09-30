import pytest

from tradebot.config import load_config


def test_load_yaml_and_env(tmp_path, monkeypatch):
    path = tmp_path / "c.yaml"
    path.write_text("symbol: ETH/USDT\nrisk:\n  risk_per_trade: 0.02\nstrategy:\n  name: macd_trend\n")
    monkeypatch.setenv("EXCHANGE_API_KEY", "k")
    monkeypatch.setenv("EXCHANGE_API_SECRET", "s")
    cfg = load_config(path)
    assert cfg.symbol == "ETH/USDT" and cfg.risk.risk_per_trade == 0.02
    assert cfg.risk.stop_atr_mult == 2.0  # default kept
    assert cfg.exchange.api_key == "k"
    assert cfg.to_dict()["exchange"]["api_secret"] == "***"


def test_invalid_values_rejected(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("risk:\n  risk_per_trade: 0.5\n")
    with pytest.raises(ValueError, match="risk_per_trade"):
        load_config(path)
    path.write_text("riks: {}\n")
    with pytest.raises(ValueError, match="Unknown config keys"):
        load_config(path)
