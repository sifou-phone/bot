"""Run the bot and its dashboard:  python -m arbbot   ->  http://127.0.0.1:8000"""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from .bot import ArbBot
from .config import Settings, setup_logging
from .dashboard import create_app

log = logging.getLogger("arbbot")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arbbot", description="Cross-exchange arbitrage bot with dashboard")
    parser.add_argument("--host", help="dashboard address (default 127.0.0.1, local only)")
    parser.add_argument("--port", type=int, help="dashboard port (default 8000)")
    parser.add_argument("--no-autostart", action="store_true", help="wait for the Start button before monitoring")
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    settings.host = args.host or settings.host
    settings.port = args.port or settings.port
    setup_logging(settings)
    log.info("ArbBot starting: exchanges=%s symbols=%s threshold=%.3f%% size=%.2f USDT paper_only=%s",
             settings.exchanges, settings.symbols, settings.min_net_spread_pct, settings.trade_size_usdt,
             settings.paper_mode)
    if not settings.paper_mode:
        log.warning("PAPER_MODE=false: live trading can be enabled from the dashboard (double confirmation).")
    if settings.host not in ("127.0.0.1", "localhost", "::1"):
        log.warning("Dashboard bound to %s: it has no login, keep it on a trusted network.", settings.host)

    bot = ArbBot(settings)
    app = create_app(bot, auto_start=not args.no_autostart)
    print(f"\n  Dashboard: http://{settings.host}:{settings.port}\n")
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning", log_config=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
