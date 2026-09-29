"""Command line interface.

    python -m tradebot backtest  --config config.yaml [--synthetic] [--plot out.html]
    python -m tradebot optimize  --config config.yaml --grid fast=8,12 slow=21,26
    python -m tradebot download  --config config.yaml --out data/btc_1h.csv
    python -m tradebot paper     --config config.yaml
    python -m tradebot live      --config config.yaml
    python -m tradebot status    --config config.yaml
    python -m tradebot scan      --config config.scalper.yaml [--watch]
    python -m tradebot hunt      --config config.scalper.yaml [--live]
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pandas as pd

from .backtest import Backtester
from .config import BotConfig, load_config
from .data import fetch_history, load_csv, save_csv, synthetic_ohlcv
from .metrics import format_metrics
from .strategies import STRATEGIES, create_strategy

log = logging.getLogger("tradebot")


def setup_logging(cfg: BotConfig) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(cfg.log_level.upper())
    root.handlers.clear()
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)
    if cfg.log_file:
        Path(cfg.log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(cfg.log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)


def load_data(cfg: BotConfig, synthetic: bool) -> pd.DataFrame:
    if synthetic:
        return synthetic_ohlcv(timeframe=cfg.timeframe)
    if cfg.backtest.data_file:
        return load_csv(cfg.backtest.data_file)
    return download_history(cfg)


def download_history(cfg: BotConfig) -> pd.DataFrame:
    from .exchange import create_ccxt

    ex = create_ccxt(cfg.exchange, authenticated=False)
    return fetch_history(ex, cfg.symbol, cfg.timeframe, cfg.backtest.since, cfg.backtest.until)


def run_backtest(cfg: BotConfig, df: pd.DataFrame, params: dict | None = None):
    strategy = create_strategy(cfg.strategy.name, params if params is not None else cfg.strategy.params)
    bt = Backtester(strategy, cfg.risk, cfg.costs, cfg.backtest.initial_capital, cfg.timeframe)
    return bt.run(df)


def cmd_backtest(cfg: BotConfig, args: argparse.Namespace) -> int:
    df = load_data(cfg, args.synthetic)
    print(f"Backtesting {cfg.strategy.name} on {cfg.symbol} {cfg.timeframe}: "
          f"{len(df)} candles {df.index[0]} -> {df.index[-1]}")
    result = run_backtest(cfg, df)
    print(format_metrics(result.metrics))
    if result.halted:
        print(f"  ⛔ halted: {result.halted}")
    if args.trades:
        result.trades_frame().to_csv(args.trades, index=False)
        print(f"Trades written to {args.trades}")
    if args.plot:
        from .report import write_html_report

        write_html_report(args.plot, df, result, title=f"{cfg.symbol} {cfg.timeframe} {cfg.strategy.name}")
        print(f"Report written to {args.plot}")
    return 0


def parse_grid(items: list[str]) -> dict[str, list]:
    grid: dict[str, list] = {}
    for item in items:
        key, _, values = item.partition("=")
        if not values:
            raise SystemExit(f"Bad --grid entry '{item}', expected key=v1,v2")
        grid[key] = [json.loads(v) for v in values.split(",")]
    return grid


def cmd_optimize(cfg: BotConfig, args: argparse.Namespace) -> int:
    df = load_data(cfg, args.synthetic)
    grid = parse_grid(args.grid)
    split = int(len(df) * (1 - args.test_ratio))
    train, test = df.iloc[:split], df.iloc[split:]
    runs = []
    for combo in itertools.product(*grid.values()):
        params = {**cfg.strategy.params, **dict(zip(grid, combo))}
        m = run_backtest(cfg, train, params).metrics
        runs.append((params, {**params, "sharpe": m["sharpe"], "return_pct": m["total_return_pct"],
                              "max_dd_pct": m["max_drawdown_pct"], "trades": m["trades"]}))
    runs.sort(key=lambda r: r[1][args.metric], reverse=True)
    table = pd.DataFrame([row for _, row in runs])
    print(f"In-sample ({len(train)} candles), top 10 by {args.metric}:")
    print(table.head(10).to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    best = runs[0][0]
    if len(test) > 0:
        m = run_backtest(cfg, test, best).metrics
        print(f"\nOut-of-sample ({len(test)} candles) with best params {best}:")
        print(format_metrics(m))
    return 0


def cmd_download(cfg: BotConfig, args: argparse.Namespace) -> int:
    df = download_history(cfg)  # always fetch, even when backtest.data_file is set
    save_csv(df, args.out)
    print(f"Saved {len(df)} candles to {args.out}")
    return 0


def _confirm_live(cfg: BotConfig, args: argparse.Namespace) -> bool:
    if not (cfg.exchange.api_key and cfg.exchange.api_secret):
        raise SystemExit("Live mode requires EXCHANGE_API_KEY / EXCHANGE_API_SECRET")
    if cfg.exchange.sandbox or args.yes:
        return True
    answer = input(f"⚠️  REAL-MONEY trading on {cfg.exchange.name}. Type 'yes' to continue: ")
    return answer.strip().lower() == "yes"


def _make_exchange(cfg: BotConfig, state):
    from .exchange import LiveExchange, PaperExchange

    if cfg.mode == "live":
        return LiveExchange(cfg.exchange, cfg.symbol)
    quote = state.paper_quote if state.paper_quote is not None else cfg.paper_balance
    return PaperExchange(cfg.exchange, cfg.symbol, cfg.costs, quote, state.paper_base or 0.0)


def cmd_trade(cfg: BotConfig, args: argparse.Namespace) -> int:
    from .engine import TradingEngine
    from .notifier import Notifier
    from .state import BotState

    cfg.mode = args.command
    if cfg.mode == "live" and not _confirm_live(cfg, args):
        return 1
    setup_logging(cfg)
    state = BotState.load(cfg.state_file)
    exchange = _make_exchange(cfg, state)
    strategy = create_strategy(cfg.strategy.name, cfg.strategy.params)
    log.info("Starting %s trading with config: %s", cfg.mode, json.dumps(cfg.to_dict()))
    TradingEngine(cfg, exchange, strategy, Notifier(cfg.telegram), state).run()
    return 0


def _make_scanner(cfg: BotConfig, market):
    from .scanner import Scanner

    strategy = create_strategy(cfg.strategy.name, cfg.strategy.params)
    return Scanner(market, strategy, cfg.scanner, cfg.timeframe, cfg.history_bars), strategy


def cmd_scan(cfg: BotConfig, args: argparse.Namespace) -> int:
    import time

    from .exchange import create_ccxt
    from .scanner import format_table

    scanner, _ = _make_scanner(cfg, create_ccxt(cfg.exchange, authenticated=False))
    while True:
        cands = scanner.scan()
        print(f"\n{pd.Timestamp.now(tz='UTC'):%Y-%m-%d %H:%M:%S} UTC  {cfg.exchange.name}  "
              f"{len(cands)} pairs  strategy={cfg.strategy.name}")
        print(format_table(cands, args.top))
        if not args.watch:
            return 0
        step = scanner.tf_seconds
        time.sleep(step - time.time() % step + 3)  # just after the next candle closes


def cmd_hunt(cfg: BotConfig, args: argparse.Namespace) -> int:
    from .hunter import HunterEngine
    from .notifier import Notifier
    from .state import BotState

    cfg.mode = "live" if args.live else "paper"
    if cfg.mode == "live" and not _confirm_live(cfg, args):
        return 1
    setup_logging(cfg)
    state = BotState.load(cfg.state_file)
    if state.position is not None and state.position.symbol:
        cfg.symbol = state.position.symbol
    exchange = _make_exchange(cfg, state)
    from .exchange import create_ccxt

    # Signals always come from real public market data, even when orders go to a testnet.
    market = exchange.ex if cfg.mode == "paper" else create_ccxt(cfg.exchange, authenticated=False)
    scanner, strategy = _make_scanner(cfg, market)
    log.info("Starting %s hunt with config: %s", cfg.mode, json.dumps(cfg.to_dict()))
    HunterEngine(cfg, exchange, strategy, scanner, Notifier(cfg.telegram), state).run()
    return 0


def cmd_status(cfg: BotConfig, args: argparse.Namespace) -> int:
    from .state import BotState

    state = BotState.load(cfg.state_file)
    pnl = sum(t["pnl"] for t in state.trades)
    wins = sum(1 for t in state.trades if t["pnl"] > 0)
    print(f"State file: {cfg.state_file}")
    print(f"Open position: {state.position or 'none'}")
    print(f"Closed trades: {len(state.trades)} (wins {wins}), realized PnL {pnl:+.2f}")
    print(f"Peak equity: {state.peak_equity:.2f} | halted: {state.halted or 'no'}")
    if state.paper_quote is not None:
        print(f"Paper balances: quote {state.paper_quote:.2f}, base {state.paper_base or 0:.8f}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tradebot", description="Crypto trading bot")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help_: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_)
        p.add_argument("-c", "--config", default="config.yaml", help="YAML config file")
        p.add_argument("--strategy", choices=sorted(STRATEGIES), help="override strategy.name")
        p.add_argument("--symbol", help="override symbol, e.g. ETH/USDT")
        p.add_argument("--timeframe", help="override timeframe, e.g. 15m, 4h")
        return p

    bt = add("backtest", "run a historical backtest")
    bt.add_argument("--synthetic", action="store_true", help="use generated data (offline demo)")
    bt.add_argument("--trades", help="write the trade list to this CSV")
    bt.add_argument("--plot", help="write an interactive HTML report")

    opt = add("optimize", "grid-search strategy parameters with an out-of-sample check")
    opt.add_argument("--grid", nargs="+", required=True, help="param=v1,v2,... entries")
    opt.add_argument("--metric", default="sharpe", choices=["sharpe", "return_pct"])
    opt.add_argument("--test-ratio", type=float, default=0.3)
    opt.add_argument("--synthetic", action="store_true")

    dl = add("download", "download historical candles to CSV")
    dl.add_argument("--out", required=True)

    add("paper", "trade with simulated money on live market data")
    live = add("live", "trade with real orders on the exchange")
    live.add_argument("--yes", action="store_true", help="skip the real-money confirmation prompt")
    add("status", "show saved bot state")
    sc = add("scan", "rank the market's pairs by breakout / liquidity (read only)")
    sc.add_argument("--watch", action="store_true", help="refresh after every closed candle")
    sc.add_argument("--top", type=int, default=15)
    hunt = add("hunt", "scan the market and trade the strongest breakout (paper by default)")
    hunt.add_argument("--live", action="store_true", help="real orders instead of paper trading")
    hunt.add_argument("--yes", action="store_true", help="skip the real-money confirmation prompt")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg_path = args.config if Path(args.config).exists() else None
    if cfg_path is None and args.config != "config.yaml":
        raise SystemExit(f"Config file not found: {args.config}")
    cfg = load_config(cfg_path)
    if args.strategy and args.strategy != cfg.strategy.name:
        cfg.strategy.name, cfg.strategy.params = args.strategy, {}
    cfg.symbol = args.symbol or cfg.symbol
    cfg.timeframe = args.timeframe or cfg.timeframe
    if args.command not in ("paper", "live", "hunt"):
        logging.basicConfig(level=cfg.log_level.upper(), format="%(levelname)s %(name)s: %(message)s")
    handlers = {"backtest": cmd_backtest, "optimize": cmd_optimize, "download": cmd_download,
                "paper": cmd_trade, "live": cmd_trade, "status": cmd_status,
                "scan": cmd_scan, "hunt": cmd_hunt}
    return handlers[args.command](cfg, args)
