import pandas as pd

from tradebot.data import load_csv, save_csv, synthetic_ohlcv


def test_csv_round_trip(tmp_path):
    df = synthetic_ohlcv(50)
    path = tmp_path / "d.csv"
    save_csv(df, path)
    pd.testing.assert_frame_equal(load_csv(path), df, check_freq=False, check_names=False)
