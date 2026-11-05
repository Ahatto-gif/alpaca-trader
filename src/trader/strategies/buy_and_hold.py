import pandas as pd

from .base import Strategy


class BuyAndHold(Strategy):
    """Always fully invested in every symbol's slot. Use with a small index universe
    (e.g. SPY + QQQ) and a rebalance band: the portfolio layer keeps the weights on target."""

    name = "buy_and_hold"
    default_params: dict = {}

    @property
    def warmup(self) -> int:
        return 0

    def compute(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(1.0, index=df.index)
