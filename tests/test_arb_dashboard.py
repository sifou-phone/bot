"""ArbBot: settings from env, secret handling, mode gates and dashboard protections."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from arbbot.bot import ArbBot, ModeError
from arbbot.config import Credentials, Settings
from arbbot.dashboard import create_app
from arbbot.storage import Storage

SECRET = "sEcReT-very-private-123"
H = {"X-ArbBot-Action": "1"}


def make_bot(**kw):
    s = Settings(exchanges=["binance", "okx"], symbols=["BTC/USDT"], **kw)
    s.credentials = {"binance": Credentials("key-abc", SECRET), "okx": Credentials("", "")}
    return ArbBot(s, storage=Storage(":memory:"))


@pytest.fixture
def client():
    bot = make_bot()
    with TestClient(create_app(bot, auto_start=False), base_url="http://127.0.0.1:8000") as c:
        c.bot = bot
        yield c


def test_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EXCHANGES", "binance,okx,kucoin")
    monkeypatch.setenv("SYMBOLS", "btc/usdt, eth/usdt")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("MIN_NET_SPREAD_PCT", "0.5")
    monkeypatch.setenv("OKX_API_KEY", "k")
    monkeypatch.setenv("OKX_API_SECRET", SECRET)
    s = Settings.from_env()
    assert s.symbols == ["BTC/USDT", "ETH/USDT"] and s.min_net_spread_pct == 0.5 and not s.paper_mode
    assert s.credentials["okx"].configured and not s.credentials["binance"].configured
    assert SECRET not in repr(s) and SECRET not in str(s.public_dict())
    monkeypatch.setenv("PAPER_MODE", "maybe")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_page_and_state_never_contain_secrets(client):
    page = client.get("/")
    assert page.status_code == 200 and "لوحة المراجحة" in page.text
    state = client.get("/api/state")
    assert state.status_code == 200
    assert SECRET not in page.text and SECRET not in state.text and "key-abc" not in state.text
    assert state.json()["settings"]["api_keys"] == {"binance": True, "okx": False}


def test_controls_need_action_header_and_local_host(client):
    assert client.post("/api/kill").status_code == 403  # no custom header: CSRF blocked
    assert client.post("/api/kill", headers={**H, "Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/state", headers={"Host": "evil.example"}).status_code == 403  # DNS rebinding
    r = client.post("/api/kill", headers={**H, "Origin": "http://127.0.0.1:8000"}, json={"reason": "test"})
    assert r.status_code == 200 and client.bot.executor.state.killed
    assert client.post("/api/kill/reset", headers=H).status_code == 200
    assert not client.bot.executor.state.killed


def test_live_mode_is_gated(client):
    r = client.post("/api/mode", headers=H, json={"mode": "live", "confirm": True, "phrase": "LIVE"})
    assert r.status_code == 400 and "PAPER_MODE" in r.json()["detail"]
    assert client.bot.mode == "paper"


def test_live_mode_needs_env_keys_and_double_confirmation():
    bot = make_bot(paper_mode=False)

    async def scenario():
        with pytest.raises(ModeError, match="missing API keys for: okx"):
            await bot.set_mode("live", True, "LIVE")
        bot.settings.credentials["okx"] = Credentials("k2", "s2", "p2")
        with pytest.raises(ModeError, match="double confirmation"):
            await bot.set_mode("live", True, "live please")
        with pytest.raises(ModeError, match="double confirmation"):
            await bot.set_mode("live", False, "LIVE")
        bot.kill("test")
        with pytest.raises(ModeError, match="kill switch"):
            await bot.set_mode("live", True, "LIVE")
    asyncio.run(scenario())
    assert bot.mode == "paper"


def test_websocket_pushes_state_and_rejects_foreign_origin(client):
    with client.websocket_connect("ws://127.0.0.1:8000/ws") as ws:
        assert ws.receive_json()["mode"] == "paper"
    with pytest.raises(Exception):
        with client.websocket_connect("ws://127.0.0.1:8000/ws", headers={"Origin": "https://evil.example"}) as ws:
            ws.receive_json()
