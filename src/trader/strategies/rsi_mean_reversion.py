import numpy as np
import pandas as pd

from .base import Strategy


def rsi(close: pd.Series, period: int) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100.0)


class RsiMeanReversion(Strategy):
    """Buy short-term oversold dips inside a long-term uptrend; exit when RSI recovers.

    Enter when RSI < entry and close > trend SMA. Exit when RSI > exit or close < trend SMA.
    """

    name = "rsi_mean_reversion"
    default_params = {"period": 2, "entry": 10, "exit": 70, "trend": 200}

    def validate(self) -> None:
        if not 0 < self.params["entry"] < self.params["exit"] < 100:
            raise ValueError("need 0 < entry < exit < 100")

    @property
    def warmup(self) -> int:
        return max(self.params["trend"], self.params["period"] * 5)

    def compute(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        r = rsi(close, self.params["period"]).to_numpy()
        uptrend = (close > close.rolling(self.params["trend"]).mean()).to_numpy()
        pos = np.zeros(len(df))
        holding = False
        for i in range(len(df)):  # stateful entry/exit: loop is clearest
            if holding and (r[i] > self.params["exit"] or not uptrend[i]):
                holding = False
            elif not holding and r[i] < self.params["entry"] and uptrend[i]:
                holding = True
            pos[i] = 1.0 if holding else 0.0
        return pd.Series(pos, index=df.index)
