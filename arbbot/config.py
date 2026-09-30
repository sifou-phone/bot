"""Settings, loaded from environment variables and an optional ``.env`` file.

Secrets (API keys) only ever come from the environment. ``Settings`` never
exposes them: ``public_dict()`` reports only whether a key is configured.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
SUPPORTED_EXCHANGES = ("binance", "okx", "bybit", "kucoin")

# Taker fees used until the exchange's own market data is loaded (fractions, e.g. 0.001 = 0.1%).
DEFAULT_TAKER_FEES = {"binance": 0.001, "okx": 0.001, "bybit": 0.001, "kucoin": 0.001}

# Typical withdrawal fees in units of the coin. Used to price re-balancing inventory between
# exchanges; check the exchanges' current fees and override with WITHDRAWAL_FEES.
DEFAULT_WITHDRAWAL_FEES = {
    "BTC": 0.0002, "ETH": 0.002, "SOL": 0.01, "XRP": 0.25, "DOGE": 4.0, "LTC": 0.001,
    "ADA": 1.0, "TRX": 1.0, "AVAX": 0.01, "LINK": 0.3, "BNB": 0.0005, "USDT": 1.0,
}

# Official alternative public endpoints that work in more networks (market data only, no keys).
PUBLIC_DATA_OVERRIDES = {
    "binance": {"rest": "https://data-api.binance.vision/api/v3", "ws": "wss://data-stream.binance.vision/ws"},
    "okx": {"ws": "wss://ws.okx.com:443/ws/v5"},
}


def load_dotenv(*paths: Path) -> None:
    """Minimal .env reader; real environment variables always win."""
    for path in paths:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be true or false, got {raw!r}")


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def _list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "").strip()
    return [x.strip() for x in raw.split(",") if x.strip()] if raw else list(default)


def _json(name: str, default: dict[str, Any]) -> dict[str, Any]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return dict(default)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return {**default, **value}


@dataclass
class Credentials:
    api_key: str = ""
    secret: str = ""
    password: str = ""  # passphrase (OKX, KuCoin)

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.secret)

    def __repr__(self) -> str:  # never print secrets, even by accident
        return f"Credentials(configured={self.configured})"


@dataclass
class Settings:
    exchanges: list[str] = field(default_factory=lambda: ["binance", "okx", "kucoin"])
    symbols: list[str] = field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT"])
    paper_mode: bool = True
    min_net_spread_pct: float = 0.3
    trade_size_usdt: float = 100.0
    slippage_buffer_pct: float = 0.05
    include_withdrawal_fee: bool = True
    rebalance_batch_usdt: float = 2_000.0  # traded volume between two inventory re-balances
    max_quote_age_ms: float = 3000.0
    order_book_depth: int = 20
    price_tolerance_pct: float = 0.2  # IOC limit price allowance beyond the quoted price
    cooldown_seconds: float = 10.0
    record_interval_seconds: float = 5.0
    max_daily_loss_usdt: float = 50.0
    paper_quote_balance: float = 10_000.0
    paper_base_value_usdt: float = 5_000.0
    paper_fail_rate: float = 0.0  # simulate a failing leg, to exercise recovery logic
    use_public_data_endpoints: bool = True
    host: str = "127.0.0.1"
    port: int = 8000
    db_path: Path = Path("data/arbbot.sqlite3")
    log_file: Path = Path("logs/arbbot.log")
    log_level: str = "INFO"
    taker_fees: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_TAKER_FEES))
    withdrawal_fees: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WITHDRAWAL_FEES))
    credentials: dict[str, Credentials] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(Path.cwd() / ".env", PACKAGE_DIR / ".env")
        exchanges = [e.lower() for e in _list("EXCHANGES", ["binance", "okx", "kucoin"])]
        creds = {
            ex: Credentials(
                os.environ.get(f"{ex.upper()}_API_KEY", ""),
                os.environ.get(f"{ex.upper()}_API_SECRET", ""),
                os.environ.get(f"{ex.upper()}_API_PASSWORD", ""),
            )
            for ex in exchanges
        }
        s = cls(
            exchanges=exchanges,
            symbols=[x.upper() for x in _list("SYMBOLS", cls().symbols)],
            paper_mode=_bool("PAPER_MODE", True),
            min_net_spread_pct=_float("MIN_NET_SPREAD_PCT", 0.3),
            trade_size_usdt=_float("TRADE_SIZE_USDT", 100.0),
            slippage_buffer_pct=_float("SLIPPAGE_BUFFER_PCT", 0.05),
            include_withdrawal_fee=_bool("INCLUDE_WITHDRAWAL_FEE", True),
            rebalance_batch_usdt=_float("REBALANCE_BATCH_USDT", 2_000),
            max_quote_age_ms=_float("MAX_QUOTE_AGE_MS", 3000),
            order_book_depth=int(_float("ORDER_BOOK_DEPTH", 20)),
            price_tolerance_pct=_float("PRICE_TOLERANCE_PCT", 0.2),
            cooldown_seconds=_float("COOLDOWN_SECONDS", 10),
            record_interval_seconds=_float("RECORD_INTERVAL_SECONDS", 5),
            max_daily_loss_usdt=_float("MAX_DAILY_LOSS_USDT", 50),
            paper_quote_balance=_float("PAPER_QUOTE_BALANCE", 10_000),
            paper_base_value_usdt=_float("PAPER_BASE_VALUE_USDT", 5_000),
            paper_fail_rate=_float("PAPER_FAIL_RATE", 0.0),
            use_public_data_endpoints=_bool("USE_PUBLIC_DATA_ENDPOINTS", True),
            host=os.environ.get("DASHBOARD_HOST", "127.0.0.1"),
            port=int(_float("DASHBOARD_PORT", 8000)),
            db_path=Path(os.environ.get("DB_PATH", "data/arbbot.sqlite3")),
            log_file=Path(os.environ.get("LOG_FILE", "logs/arbbot.log")),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            taker_fees=_json("TAKER_FEES", DEFAULT_TAKER_FEES),
            withdrawal_fees=_json("WITHDRAWAL_FEES", DEFAULT_WITHDRAWAL_FEES),
            credentials=creds,
        )
        s.validate()
        return s

    def validate(self) -> None:
        errors = []
        unknown = [e for e in self.exchanges if e not in SUPPORTED_EXCHANGES]
        if unknown:
            errors.append(f"unsupported exchanges {unknown}; choose from {list(SUPPORTED_EXCHANGES)}")
        if len(self.exchanges) < 2:
            errors.append("EXCHANGES needs at least two exchanges")
        if not self.symbols:
            errors.append("SYMBOLS is empty")
        if self.min_net_spread_pct < 0:
            errors.append("MIN_NET_SPREAD_PCT must be >= 0")
        if self.trade_size_usdt <= 0:
            errors.append("TRADE_SIZE_USDT must be > 0")
        if self.rebalance_batch_usdt <= 0:
            errors.append("REBALANCE_BATCH_USDT must be > 0")
        if not 0 <= self.paper_fail_rate <= 1:
            errors.append("PAPER_FAIL_RATE must be between 0 and 1")
        if errors:
            raise ValueError("Invalid configuration:\n  - " + "\n  - ".join(errors))

    def taker_fee(self, exchange: str) -> float:
        return float(self.taker_fees.get(exchange, 0.001))

    def withdrawal_fee(self, asset: str) -> float:
        return float(self.withdrawal_fees.get(asset, 0.0))

    def public_dict(self) -> dict[str, Any]:
        """Settings safe to show on the dashboard: no secrets, only whether keys exist."""
        return {
            "exchanges": self.exchanges, "symbols": self.symbols, "paper_mode_env": self.paper_mode,
            "min_net_spread_pct": self.min_net_spread_pct, "trade_size_usdt": self.trade_size_usdt,
            "slippage_buffer_pct": self.slippage_buffer_pct, "include_withdrawal_fee": self.include_withdrawal_fee,
            "rebalance_batch_usdt": self.rebalance_batch_usdt,
            "max_quote_age_ms": self.max_quote_age_ms, "cooldown_seconds": self.cooldown_seconds,
            "max_daily_loss_usdt": self.max_daily_loss_usdt, "taker_fees": self.taker_fees,
            "withdrawal_fees": self.withdrawal_fees,
            "api_keys": {ex: c.configured for ex, c in self.credentials.items()},
        }


def setup_logging(settings: Settings) -> None:
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.handlers.clear()
    file_handler = RotatingFileHandler(settings.log_file, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(file_handler)
    root.addHandler(console)
    for noisy in ("ccxt", "urllib3", "asyncio", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
