"""SQLite storage for opportunities and executions.

sqlite3 calls run in a worker thread (``asyncio.to_thread``) so the event loop
never blocks on disk I/O.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .models import Opportunity

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    symbol TEXT NOT NULL,
    buy_exchange TEXT NOT NULL,
    sell_exchange TEXT NOT NULL,
    buy_price REAL, sell_price REAL, buy_vwap REAL, sell_vwap REAL,
    base_amount REAL, notional REAL,
    gross_pct REAL, fees_pct REAL, withdrawal_pct REAL, slippage_pct REAL,
    net_pct REAL, net_profit_usdt REAL,
    actionable INTEGER NOT NULL DEFAULT 0,
    executed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_opp_ts ON opportunities(ts);
CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    opportunity_id INTEGER,
    mode TEXT NOT NULL,
    symbol TEXT NOT NULL,
    buy_exchange TEXT NOT NULL,
    sell_exchange TEXT NOT NULL,
    status TEXT NOT NULL,
    buy_filled REAL, buy_avg REAL, sell_filled REAL, sell_avg REAL,
    fees_usdt REAL, pnl_usdt REAL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_exec_ts ON executions(ts);
"""


class Storage:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ sync core
    def _execute(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return int(cur.lastrowid or 0)

    def _query(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    # ------------------------------------------------------------------ opportunities
    def insert_opportunity(self, o: Opportunity) -> int:
        return self._execute(
            "INSERT INTO opportunities (ts, symbol, buy_exchange, sell_exchange, buy_price, sell_price, buy_vwap,"
            " sell_vwap, base_amount, notional, gross_pct, fees_pct, withdrawal_pct, slippage_pct, net_pct,"
            " net_profit_usdt, actionable) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (o.detected_at, o.symbol, o.buy_exchange, o.sell_exchange, o.buy_price, o.sell_price, o.buy_vwap,
             o.sell_vwap, o.base_amount, o.notional, o.gross_pct, o.fees_pct, o.withdrawal_pct, o.slippage_pct,
             o.net_pct, o.net_profit_usdt, int(o.actionable)))

    def mark_executed(self, opportunity_id: int) -> None:
        self._execute("UPDATE opportunities SET executed = 1 WHERE id = ?", (opportunity_id,))

    def recent_opportunities(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._query("SELECT * FROM opportunities ORDER BY ts DESC LIMIT ?", (limit,))

    # ------------------------------------------------------------------ executions
    def insert_execution(self, row: dict[str, Any]) -> int:
        detail = json.dumps(row.get("detail") or {}, default=str)
        return self._execute(
            "INSERT INTO executions (ts, opportunity_id, mode, symbol, buy_exchange, sell_exchange, status,"
            " buy_filled, buy_avg, sell_filled, sell_avg, fees_usdt, pnl_usdt, detail)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row.get("ts", time.time()), row.get("opportunity_id"), row["mode"], row["symbol"],
             row["buy_exchange"], row["sell_exchange"], row["status"], row.get("buy_filled"), row.get("buy_avg"),
             row.get("sell_filled"), row.get("sell_avg"), row.get("fees_usdt"), row.get("pnl_usdt"), detail))

    def recent_executions(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._query("SELECT * FROM executions ORDER BY ts DESC LIMIT ?", (limit,))
        for r in rows:
            try:
                r["detail"] = json.loads(r["detail"] or "{}")
            except ValueError:
                r["detail"] = {}
        return rows

    def pnl_since(self, since_ts: float) -> float:
        rows = self._query("SELECT COALESCE(SUM(pnl_usdt), 0) AS p FROM executions WHERE ts >= ?", (since_ts,))
        return float(rows[0]["p"])

    def counts(self) -> dict[str, int]:
        a = self._query("SELECT COUNT(*) AS n, COALESCE(SUM(actionable),0) AS a FROM opportunities")[0]
        e = self._query("SELECT COUNT(*) AS n FROM executions")[0]
        return {"opportunities": int(a["n"]), "actionable": int(a["a"]), "executions": int(e["n"])}

    # ------------------------------------------------------------------ async wrappers
    async def a_insert_opportunity(self, o: Opportunity) -> int:
        return await asyncio.to_thread(self.insert_opportunity, o)

    async def a_insert_execution(self, row: dict[str, Any]) -> int:
        return await asyncio.to_thread(self.insert_execution, row)

    async def a_mark_executed(self, opportunity_id: int) -> None:
        await asyncio.to_thread(self.mark_executed, opportunity_id)
