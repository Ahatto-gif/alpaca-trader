import pandas as pd

from .base import Strategy


class SmaCrossover(Strategy):
    """Trend following: long while the fast SMA is above the slow SMA."""

    name = "sma_crossover"
    default_params = {"fast": 20, "slow": 100}

    def validate(self) -> None:
        if self.params["fast"] >= self.params["slow"]:
            raise ValueError("fast must be < slow")

    @property
    def warmup(self) -> int:
        return self.params["slow"]

    def compute(self, df: pd.DataFrame) -> pd.Series:
        fast = df["close"].rolling(self.params["fast"]).mean()
        slow = df["close"].rolling(self.params["slow"]).mean()
        return (fast > slow).astype(float)
