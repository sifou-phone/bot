import json
import time
import urllib.request

import pytest

from tradebot.dashboard import DashboardData, serve, trade_stats
from tradebot.snapshot import SnapshotWriter, clean
from tradebot.state import BotState


def test_trade_stats():
    trades = [{"pnl": 10, "fees": 1, "exit_time": "2000-01-01T00:00:00"},
              {"pnl": -4, "fees": 1, "exit_time": "2000-01-01T00:00:00"}]
    equity = [{"t": 0, "equity": 100}, {"t": 1, "equity": 110}, {"t": 2, "equity": 99}]
    s = trade_stats(trades, equity, time.time())
    assert s["trades"] == 2 and s["wins"] == 1 and s["win_rate"] == 50
    assert s["realized_pnl"] == 6 and s["profit_factor"] == 2.5 and s["fees"] == 2
    assert s["max_drawdown_pct"] == pytest.approx(10)
    assert s["today_pnl"] == 0  # old trades do not count for today


def test_clean_makes_json_safe():
    assert clean({"a": float("nan"), "b": [float("inf"), 1.0]}) == {"a": None, "b": [None, 1.0]}


def test_status_and_http(tmp_path):
    state = BotState(trades=[{"pnl": 3.0, "fees": 0.2, "exit_time": "2000-01-01", "symbol": "SOL/USDT"}])
    state.save(tmp_path / "state.json")
    writer = SnapshotWriter(tmp_path)
    now = time.time()
    snap = {"updated": now, "equity": 1003.0, "poll_seconds": 5, "position": None,
            "scanner": {"at": now, "candidates": [{"symbol": "SOL/USDT", "rvol": float("nan")}]}}
    writer.write(snap, 1003.0, now // 60 * 60)
    writer.write(snap, 1004.0, now // 60 * 60 + 1)  # same minute: no second equity point
    (tmp_path / "bot.log").write_text("line 1\nline 2\n")

    data = DashboardData(tmp_path / "state.json", tmp_path / "bot.log", 1000.0)
    st = data.status()
    assert st["running"] and st["start_balance"] == 1000.0
    assert len(st["equity"]) == 1 and st["stats"]["trades"] == 1
    assert st["log"] == ["line 1", "line 2"]

    server = serve(data, "127.0.0.1", 0, background=True)
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        page = urllib.request.urlopen(base + "/").read().decode()
        assert "لوحة TradeBot" in page
        api = json.loads(urllib.request.urlopen(base + "/api/status").read())
        assert api["live"]["scanner"]["candidates"][0]["rvol"] is None  # NaN became null
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/../state.json")
    finally:
        server.shutdown()
