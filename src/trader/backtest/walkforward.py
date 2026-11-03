"""Walk-forward optimisation.

Roll a window through history: pick the best parameters on the *train* years, trade the
next *test* year with them, then roll forward. Stitching the test years together gives
an equity curve where every trade was made with parameters chosen only from the past.
That is the closest a backtest gets to how you'd actually run a strategy.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import pandas as pd

from ..strategies import REGISTRY
from .metrics import performance
from .vectorized import vectorized_returns


@dataclass
class WalkForwardResult:
    windows: pd.DataFrame            # one row per test window
    oos_returns: pd.Series           # stitched daily out-of-sample returns (fast engine)
    signals: dict[str, pd.Series]    # stitched signals per symbol, for the backtrader run
    stats: dict


def _windows(dates: pd.DatetimeIndex, train_years: float, test_years: float, anchored: bool):
    first, last = dates[0], dates[-1]
    test_start = first + pd.DateOffset(months=int(train_years * 12))
    while test_start < last:
        test_end = min(test_start + pd.DateOffset(months=int(test_years * 12)), last + pd.Timedelta(days=1))
        train_start = first if anchored else test_start - pd.DateOffset(months=int(train_years * 12))
        yield train_start, test_start, test_end
        test_start = test_end


def walk_forward(bars: dict[str, pd.DataFrame], strategy_name: str, grid: dict[str, list], *,
                 train_years: float = 3, test_years: float = 1, anchored: bool = False,
                 metric: str = "sharpe", **engine_kwargs) -> WalkForwardResult:
    cls = REGISTRY[strategy_name]
    dates = pd.DataFrame({s: df["close"] for s, df in bars.items()}).dropna().index
    keys = list(grid)

    # Evaluate every parameter set once over the full history. Signals only use past data
    # (see tests/test_strategies.py::test_no_lookahead) so slicing afterwards is safe.
    candidates = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        params = dict(zip(keys, combo))
        try:
            strat = cls(**params)
        except ValueError:
            continue
        rets = vectorized_returns(bars, strat, **engine_kwargs)
        valid_from = rets.index[min(strat.warmup, len(rets) - 1)]
        candidates.append((params, strat, rets, valid_from))
    if not candidates:
        raise SystemExit("No valid parameter combinations in the grid.")

    rows, oos_parts = [], []
    stitched = {s: pd.Series(0.0, index=dates) for s in bars}
    for train_start, test_start, test_end in _windows(dates, train_years, test_years, anchored):
        best = None
        for params, strat, rets, valid_from in candidates:
            train = rets[(rets.index >= max(train_start, valid_from)) & (rets.index < test_start)]
            if len(train) < 60:
                continue  # not enough warmed-up history in this window
            score = performance((1 + train).cumprod())[metric]
            if best is None or score > best[0]:
                best = (score, params, strat, rets)
        if best is None:
            continue
        score, params, strat, rets = best
        test = rets[(rets.index >= test_start) & (rets.index < test_end)]
        if test.empty:
            continue
        oos_parts.append(test)
        test_perf = performance((1 + test).cumprod()) if len(test) > 1 else {}
        rows.append({"train_start": train_start.date(), "test_start": test_start.date(),
                     "test_end": (test.index[-1]).date(), **params,
                     f"train_{metric}": score,
                     "test_return": float((1 + test).prod() - 1),
                     "test_sharpe": test_perf.get("sharpe", float("nan")),
                     "test_max_dd": test_perf.get("max_drawdown", float("nan"))})
        mask = (dates >= test_start) & (dates < test_end)
        for sym, df in bars.items():
            stitched[sym].loc[mask] = strat.signals(df).reindex(dates).loc[mask].values

    if not oos_parts:
        raise SystemExit("History too short for the chosen train/test window sizes.")
    oos = pd.concat(oos_parts)
    first_test = oos.index[0]
    signals = {s: sig.loc[first_test:] for s, sig in stitched.items()}
    windows = pd.DataFrame(rows)
    stats = performance((1 + oos).cumprod())
    stats["windows"] = len(windows)
    stats["param_changes"] = int((windows[keys].ne(windows[keys].shift()).any(axis=1).sum() - 1))
    return WalkForwardResult(windows, oos, signals, stats)
