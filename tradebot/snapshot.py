"""Live snapshot of the bot for the dashboard.

The engine writes ``live.json`` (overwritten every tick) and appends one equity
point per minute to ``equity.jsonl``, next to the state file. The dashboard only
reads these files, so it can run in the bot process or separately.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def clean(value: Any) -> Any:
    """JSON-safe copy: NaN/inf -> None, dataclasses -> dicts."""
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(clean(data), fh, default=str)
    os.replace(tmp, path)


class SnapshotWriter:
    def __init__(self, data_dir: str | Path) -> None:
        self.dir = Path(data_dir)
        self.live_path = self.dir / "live.json"
        self.equity_path = self.dir / "equity.jsonl"
        self._last_minute: int | None = None

    def write(self, snapshot: dict[str, Any], equity: float, now: float) -> None:
        write_json_atomic(self.live_path, snapshot)
        minute = int(now // 60)
        if minute != self._last_minute and equity == equity:
            self._last_minute = minute
            with open(self.equity_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": minute * 60_000, "equity": round(equity, 4)}) + "\n")
