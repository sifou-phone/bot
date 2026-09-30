"""Standalone HTML backtest report (Plotly loaded from a CDN)."""

from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

from .metrics import format_metrics


def _iso(ts) -> str:
    return pd.Timestamp(ts).isoformat()


def write_html_report(path: str | Path, df: pd.DataFrame, result, title: str = "Backtest") -> None:
    x = [_iso(t) for t in df.index]
    trades = result.trades
    price = {
        "type": "candlestick", "x": x, "open": df["open"].round(6).tolist(), "high": df["high"].round(6).tolist(),
        "low": df["low"].round(6).tolist(), "close": df["close"].round(6).tolist(), "name": "price",
        "xaxis": "x", "yaxis": "y",
    }
    entries = {
        "type": "scatter", "mode": "markers", "name": "entry", "xaxis": "x", "yaxis": "y",
        "x": [_iso(t["entry_time"]) for t in trades], "y": [t["entry"] for t in trades],
        "marker": {"symbol": "triangle-up", "size": 10, "color": "#16a34a"},
    }
    exits = {
        "type": "scatter", "mode": "markers", "name": "exit", "xaxis": "x", "yaxis": "y",
        "x": [_iso(t["exit_time"]) for t in trades], "y": [t["exit"] for t in trades],
        "text": [f"{t['reason']} {t['pnl']:+.2f}" for t in trades],
        "marker": {"symbol": "triangle-down", "size": 10, "color": "#dc2626"},
    }
    equity = {
        "type": "scatter", "mode": "lines", "name": "equity", "xaxis": "x", "yaxis": "y2",
        "x": x, "y": result.equity.round(2).tolist(), "line": {"color": "#2563eb"},
    }
    layout = {
        "title": title, "height": 800, "showlegend": True, "xaxis": {"rangeslider": {"visible": False}},
        "yaxis": {"domain": [0.35, 1], "title": "price"}, "yaxis2": {"domain": [0, 0.28], "title": "equity"},
    }
    body = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
<style>body{{font-family:system-ui,sans-serif;margin:16px}}pre{{background:#f4f4f5;padding:12px}}</style>
</head><body>
<h2>{html.escape(title)}</h2>
<pre>{html.escape(format_metrics(result.metrics))}</pre>
<div id="chart"></div>
<script>
Plotly.newPlot("chart", {json.dumps([price, entries, exits, equity])}, {json.dumps(layout)}, {{responsive: true}});
</script>
</body></html>"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(body, encoding="utf-8")
