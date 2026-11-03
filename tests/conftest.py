import numpy as np
import pandas as pd
import pytest


def make_bars(n=1500, seed=0, drift=0.0004, vol=0.015, start="2015-01-02"):
    """Synthetic daily OHLCV random walk on business days."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    open_ = close * np.exp(rng.normal(0, vol / 3, n))
    high = np.maximum(open_, close) * (1 + abs(rng.normal(0, vol / 3, n)))
    low = np.minimum(open_, close) * (1 - abs(rng.normal(0, vol / 3, n)))
    vol_ = rng.integers(1e6, 5e6, n).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": vol_}, index=pd.DatetimeIndex(idx, name="date"))


@pytest.fixture
def universe():
    return {f"SYM{i}": make_bars(seed=i) for i in range(4)}


@pytest.fixture
def bars():
    return make_bars()
