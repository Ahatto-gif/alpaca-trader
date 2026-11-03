"""Fast vectorized backtest for parameter sweeps.

This approximates the backtrader engine (fractional shares, no rebalance band) so you can
evaluate hundreds of parameter sets in seconds. Always re-check the winner with the
full backtrader backtest before trusting it.
"""
from __future__ import annotations

import itertools

import pandas as pd

from ..portfolio import target_weights
from ..strategies import REGISTRY
from .metrics import performance


def vectorized_returns(bars: dict[str, pd.DataFrame], strategy, *, slippage_bps: float = 5.0,
                       max_position_pct: float = 0.2, max_gross_exposure: float = 1.0,
                       cash_buffer: float = 0.02) -> pd.Series:
    """Daily portfolio returns. Signal at close t -> position from open t+1 (no look-ahead)."""
    signals = pd.DataFrame({s: strategy.signals(df) for s, df in bars.items()}).dropna()
    opens = pd.DataFrame({s: df["open"] for s, df in bars.items()}).loc[signals.index]

    n = signals.shape[1]
    slot = min(1.0 / n, max_position_pct)
    weights = signals * slot
    gross = weights.sum(axis=1)
    cap = max_gross_exposure * (1 - cash_buffer)
    scale = (cap / gross).where(gross > cap, 1.0)
    weights = weights.mul(scale, axis=0)

    # Return of the interval [open_t, open_{t+1}), attributed to the row of date t.
    open_to_open = (opens.shift(-1) / opens - 1).fillna(0.0)
    held = weights.shift(1).fillna(0.0)          # weight decided at close t-1, held from open t
    turnover = held.diff().abs().fillna(held.abs())
    rets = (held * open_to_open).sum(axis=1) - turnover.sum(axis=1) * slippage_bps / 10_000
    return rets


def run_sweep(bars: dict[str, pd.DataFrame], strategy_name: str, grid: dict[str, list], *,
              split: float = 0.7, metric: str = "sharpe", **kwargs) -> pd.DataFrame:
    """Grid search ranked on in-sample `metric`, reporting out-of-sample results alongside."""
    cls = REGISTRY[strategy_name]
    keys = list(grid)
    # One fixed split date for every combination, so all are judged on the same OOS window.
    dates = pd.DataFrame({s: df["close"] for s, df in bars.items()}).dropna().index
    split_date = dates[int(len(dates) * split)]
    rows = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        params = dict(zip(keys, combo))
        try:
            strategy = cls(**params)
        except ValueError:
            continue  # invalid combination, e.g. fast >= slow
        rets = vectorized_returns(bars, strategy, **kwargs)
        rets = rets.iloc[strategy.warmup:]
        ins, oos = rets[rets.index < split_date], rets[rets.index >= split_date]
        row = dict(params)
        for label, r in (("is", ins), ("oos", oos)):
            perf = performance((1 + r).cumprod())
            for k in ("cagr", "sharpe", "max_drawdown", "calmar", "sortino"):
                row[f"{label}_{k}"] = perf[k]
        rows.append(row)
    if not rows:
        raise SystemExit("No valid parameter combinations in the sweep grid.")
    df = pd.DataFrame(rows).sort_values(f"is_{metric}", ascending=False).reset_index(drop=True)
    df.attrs["split_date"] = split_date
    return df
