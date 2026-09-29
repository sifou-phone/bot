"""Strategy interface.

A strategy turns OHLCV candles into a signal column:
    1  -> enter long
   -1  -> exit long
    0  -> do nothing
Signals are evaluated on *closed* candles only; the engine executes them on the
next bar, so strategies must never look at future data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

BUY = 1
SELL = -1
HOLD = 0


class Strategy(ABC):
    name: str = "base"
    #: Default parameters; overridden by the ``params`` passed to ``__init__``.
    defaults: dict[str, Any] = {}

    def __init__(self, **params: Any) -> None:
        unknown = set(params) - set(self.defaults)
        if unknown:
            raise ValueError(f"Unknown parameters for {self.name}: {sorted(unknown)}")
        self.params = {**self.defaults, **params}

    @property
    def warmup(self) -> int:
        """Number of candles needed before signals are meaningful."""
        numeric = [v for v in self.params.values() if isinstance(v, int)]
        return max(numeric, default=0) * 3

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Return a Series (same index as ``df``) of BUY / SELL / HOLD."""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.params})"
