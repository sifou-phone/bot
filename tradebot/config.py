"""Configuration loading (YAML file + environment variables for secrets)."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ExchangeConfig:
    name: str = "binance"
    sandbox: bool = True  # use the exchange testnet when available
    api_key: str = ""
    api_secret: str = ""
    password: str = ""  # some exchanges (OKX, KuCoin) need a passphrase
    options: dict[str, Any] = field(default_factory=dict)
    # Public market data endpoint for unauthenticated use (scan, backtest, paper).
    # "auto": Binance uses data-api.binance.vision (market data only, served in more regions).
    market_data_url: str = "auto"


@dataclass
class StrategyConfig:
    name: str = "ema_cross"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskConfig:
    risk_per_trade: float = 0.01  # fraction of equity lost if the stop is hit
    atr_period: int = 14
    stop_atr_mult: float = 2.0
    take_profit_rr: float = 2.0  # reward:risk ratio; 0 disables the take-profit
    trailing_atr_mult: float = 0.0  # 0 disables the trailing stop
    max_stop_pct: float = 0.0  # hard cap on stop distance from entry, e.g. 0.015 = 1.5% (0 = off)
    min_stop_pct: float = 0.0  # floor on stop distance so fees/noise don't dominate (0 = off)
    breakeven_rr: float = 0.0  # move the stop to break-even (+fees) after this many R (0 = off)
    max_position_pct: float = 0.5  # max notional as a fraction of equity
    daily_loss_limit: float = 0.03  # stop opening trades after this daily loss
    max_drawdown: float = 0.20  # kill switch: stop trading after this drawdown
    min_notional: float = 10.0  # exchange minimum order size in quote currency


@dataclass
class CostsConfig:
    fee_rate: float = 0.001  # 0.1% taker fee
    slippage: float = 0.0005  # 0.05% adverse slippage on market orders


@dataclass
class BacktestConfig:
    initial_capital: float = 10_000.0
    since: str = "2024-01-01"
    until: str = ""
    data_file: str = ""  # optional CSV instead of downloading


@dataclass
class TelegramConfig:
    enabled: bool = False
    token: str = ""
    chat_id: str = ""


@dataclass
class ScannerConfig:
    """Market scanner used by ``scan`` and ``hunt`` to find coins that are breaking out."""

    quote: str = "USDT"
    universe_size: int = 30  # most traded pairs to watch
    min_quote_volume_24h: float = 5_000_000.0  # liquidity floor for a pair to be considered
    refresh_minutes: int = 15  # how often the watch list is rebuilt from 24h tickers
    symbols: list[str] = field(default_factory=list)  # fixed watch list (skips the ranking)
    exclude: list[str] = field(default_factory=lambda: [
        "USDC", "DAI", "FDUSD", "TUSD", "USDE", "PYUSD", "USDG", "RLUSD", "EUR", "USD1", "BUSD"])
    max_chase_pct: float = 0.005  # skip if price ran this far above the signal close
    watch_distance_pct: float = 0.005  # "WATCH" when this close under resistance with rising volume


@dataclass
class BotConfig:
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    mode: str = "paper"  # paper | live
    paper_balance: float = 10_000.0
    history_bars: int = 500
    poll_seconds: int = 30
    state_file: str = "data/state.json"
    log_file: str = "logs/tradebot.log"
    log_level: str = "INFO"
    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    costs: CostsConfig = field(default_factory=CostsConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)

    def to_dict(self, redact: bool = True) -> dict[str, Any]:
        data = asdict(self)
        if redact:
            for section, key in (("exchange", "api_key"), ("exchange", "api_secret"),
                                 ("exchange", "password"), ("telegram", "token")):
                if data[section][key]:
                    data[section][key] = "***"
        return data


def _build(cls: type, data: dict[str, Any]) -> Any:
    unknown = set(data) - {f.name for f in fields(cls)}
    if unknown:
        raise ValueError(f"Unknown config keys for {cls.__name__}: {sorted(unknown)}")
    kwargs = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        default = f.default_factory() if callable(f.default_factory) else None  # type: ignore[misc]
        if is_dataclass(default) and isinstance(value, dict):
            value = _build(type(default), value)
        kwargs[f.name] = value
    return cls(**kwargs)


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def load_config(path: str | Path | None = None) -> BotConfig:
    """Load config from YAML, then fill secrets from env vars / a ``.env`` file."""
    _load_dotenv(Path(".env"))
    data: dict[str, Any] = {}
    if path:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    cfg: BotConfig = _build(BotConfig, data)

    env = os.environ
    cfg.exchange.api_key = env.get("EXCHANGE_API_KEY", cfg.exchange.api_key)
    cfg.exchange.api_secret = env.get("EXCHANGE_API_SECRET", cfg.exchange.api_secret)
    cfg.exchange.password = env.get("EXCHANGE_PASSWORD", cfg.exchange.password)
    cfg.telegram.token = env.get("TELEGRAM_TOKEN", cfg.telegram.token)
    cfg.telegram.chat_id = env.get("TELEGRAM_CHAT_ID", cfg.telegram.chat_id)
    validate(cfg)
    return cfg


def validate(cfg: BotConfig) -> None:
    errors = []
    if cfg.mode not in ("paper", "live"):
        errors.append("mode must be 'paper' or 'live'")
    r = cfg.risk
    if not 0 < r.risk_per_trade <= 0.1:
        errors.append("risk.risk_per_trade must be in (0, 0.1]")
    if not 0 <= r.min_stop_pct < 0.5 or not 0 <= r.max_stop_pct < 0.5:
        errors.append("risk.min_stop_pct and risk.max_stop_pct must be in [0, 0.5)")
    if r.max_stop_pct and r.min_stop_pct > r.max_stop_pct:
        errors.append("risk.min_stop_pct cannot exceed risk.max_stop_pct")
    if r.stop_atr_mult <= 0:
        errors.append("risk.stop_atr_mult must be > 0")
    if not 0 < r.max_position_pct <= 1:
        errors.append("risk.max_position_pct must be in (0, 1] (spot, no leverage)")
    if not 0 < r.max_drawdown < 1 or not 0 < r.daily_loss_limit < 1:
        errors.append("risk.max_drawdown and risk.daily_loss_limit must be in (0, 1)")
    if errors:
        raise ValueError("Invalid configuration:\n  - " + "\n  - ".join(errors))
