"""Read-only web dashboard.

Serves one page plus ``/api/status``, built from the files the engine writes
(state file, ``live.json``, ``equity.jsonl``) and the log file. It never talks to
the exchange and has no controls, so it cannot place or change orders.

    python -m tradebot dashboard -c config.scalper.yaml       # http://127.0.0.1:8080
    python -m tradebot hunt -c config.scalper.yaml --dashboard 8080
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .snapshot import clean

log = logging.getLogger(__name__)
PAGE = Path(__file__).with_name("dashboard.html")
MAX_POINTS = 1500


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _equity_points(path: Path) -> list[dict[str, float]]:
    points: list[dict[str, float]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    points.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    if len(points) > MAX_POINTS:  # keep the shape, bound the payload
        step = len(points) / MAX_POINTS
        points = [points[int(i * step)] for i in range(MAX_POINTS - 1)] + [points[-1]]
    return points


def _tail(path: Path, lines: int = 80) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return [ln.rstrip("\n") for ln in deque(fh, maxlen=lines)]
    except OSError:
        return []


def trade_stats(trades: list[dict[str, Any]], equity: list[dict[str, float]], now: float) -> dict[str, Any]:
    pnls = [float(t.get("pnl") or 0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    today = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
    peak, mdd = 0.0, 0.0
    for p in equity:
        peak = max(peak, p["equity"])
        if peak > 0:
            mdd = max(mdd, 1 - p["equity"] / peak)
    return {
        "trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(pnls) * 100 if pnls else None,
        "realized_pnl": sum(pnls),
        "fees": sum(float(t.get("fees") or 0) for t in trades),
        "profit_factor": (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None,
        "avg_win": sum(wins) / len(wins) if wins else None,
        "avg_loss": sum(losses) / len(losses) if losses else None,
        "best": max(pnls) if pnls else None,
        "worst": min(pnls) if pnls else None,
        "today_pnl": sum(float(t.get("pnl") or 0) for t in trades if str(t.get("exit_time", "")).startswith(today)),
        "today_trades": sum(1 for t in trades if str(t.get("exit_time", "")).startswith(today)),
        "max_drawdown_pct": mdd * 100,
    }


class DashboardData:
    def __init__(self, state_file: str | Path, log_file: str | Path = "", start_balance: float | None = None) -> None:
        self.state_file = Path(state_file)
        self.dir = self.state_file.parent
        self.log_file = Path(log_file) if log_file else None
        self.start_balance = start_balance

    def status(self) -> dict[str, Any]:
        now = time.time()
        state = _read_json(self.state_file) or {}
        live = _read_json(self.dir / "live.json") or {}
        equity = _equity_points(self.dir / "equity.jsonl")
        trades = state.get("trades") or []
        updated = live.get("updated")
        return clean({
            "now": now,
            "live": live,
            "running": bool(updated and now - updated < max(30, 3 * (live.get("poll_seconds") or 5))),
            "state": {k: state.get(k) for k in ("position", "peak_equity", "day_start_equity", "halted",
                                                "paper_quote", "last_candle")},
            "trades": trades[-200:][::-1],
            "stats": trade_stats(trades, equity, now),
            "start_balance": self.start_balance if self.start_balance is not None else
            (equity[0]["equity"] if equity else None),
            "equity": equity,
            "log": _tail(self.log_file) if self.log_file else [],
        })


def make_handler(data: DashboardData) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/status":
                self._send(200, json.dumps(data.status()).encode(), "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def log_message(self, fmt: str, *args: Any) -> None:  # keep the bot log clean
            log.debug("dashboard: " + fmt, *args)

    return Handler


def serve(data: DashboardData, host: str = "127.0.0.1", port: int = 8080, background: bool = False):
    server = ThreadingHTTPServer((host, port), make_handler(data))
    log.info("Dashboard on http://%s:%d", host, port)
    if not background:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        return server
    thread = threading.Thread(target=server.serve_forever, name="dashboard", daemon=True)
    thread.start()
    return server
