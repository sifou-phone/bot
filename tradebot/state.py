"""Persistent bot state so a restart never forgets an open position."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Position:
    qty: float
    entry: float
    stop: float
    take_profit: float | None
    opened_at: str
    entry_fee: float = 0.0
    order_id: str | None = None
    symbol: str = ""
    initial_stop: float = 0.0


@dataclass
class BotState:
    position: Position | None = None
    peak_equity: float = 0.0
    day: str = ""
    day_start_equity: float = 0.0
    last_candle: str = ""
    halted: str | None = None
    paper_quote: float | None = None
    paper_base: float | None = None
    trades: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path) -> "BotState":
        p = Path(path)
        if not p.exists():
            return cls()
        data = json.loads(p.read_text(encoding="utf-8"))
        pos = data.pop("position", None)
        return cls(position=Position(**pos) if pos else None, **data)

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: a crash mid-write must not corrupt the state file.
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".state-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2, default=str)
        os.replace(tmp, p)
