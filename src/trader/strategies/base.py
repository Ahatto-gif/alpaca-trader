"""Strategy interface shared by the backtester, the parameter sweep and the live runner.

A strategy turns one symbol's OHLCV history into a *target exposure* series in [0, 1]:
    0   = flat
    1   = fully invested in this symbol's slot (slot size is set by the portfolio layer)
    0.5 = half-size, etc.

The value on bar t may only use data up to and including bar t. The engines act on it at
the NEXT bar's open, so there is no look-ahead as long as you don't use shift(-n).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class Strategy(ABC):
    name: str = "base"
    default_params: dict[str, Any] = {}

    def __init__(self, **params: Any) -> None:
        unknown = set(params) - set(self.default_params)
        if unknown:
            raise ValueError(f"{self.name}: unknown params {sorted(unknown)}")
        self.params = {**self.default_params, **params}
        self.validate()

    def validate(self) -> None:
        """Override to reject bad parameter combinations."""

    @property
    @abstractmethod
    def warmup(self) -> int:
        """Bars needed before the signal is meaningful."""

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.Series:
        """Return raw target exposure aligned to df.index."""

    def signals(self, df: pd.DataFrame) -> pd.Series:
        sig = self.compute(df).reindex(df.index)
        sig.iloc[: self.warmup] = 0.0
        return sig.fillna(0.0).clip(0.0, 1.0).astype(float)

    def __repr__(self) -> str:
        args = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.name}({args})"
