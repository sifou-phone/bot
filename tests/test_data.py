import pandas as pd

from tradebot.data import load_csv, save_csv, synthetic_ohlcv


def test_csv_round_trip(tmp_path):
    df = synthetic_ohlcv(50)
    path = tmp_path / "d.csv"
    save_csv(df, path)
    pd.testing.assert_frame_equal(load_csv(path), df, check_freq=False, check_names=False)


def test_ccxt_client_honors_proxy_env():
    from tradebot.config import ExchangeConfig
    from tradebot.exchange import create_ccxt

    ex = create_ccxt(ExchangeConfig(name="okx"), authenticated=False)
    assert ex.session.trust_env  # HTTPS_PROXY / REQUESTS_CA_BUNDLE are used


def test_download_ignores_backtest_data_file(tmp_path, monkeypatch):
    from tradebot import cli

    cfg_path = tmp_path / "c.yaml"
    cfg_path.write_text(f"backtest:\n  data_file: {tmp_path / 'missing.csv'}\n")
    fetched = synthetic_ohlcv(10)
    monkeypatch.setattr(cli, "download_history", lambda cfg: fetched)
    out = tmp_path / "out.csv"
    assert cli.main(["download", "-c", str(cfg_path), "--out", str(out)]) == 0
    assert len(load_csv(out)) == 10
