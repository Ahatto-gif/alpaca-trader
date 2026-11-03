import numpy as np

from trader.backtest import run_backtest, run_sweep, vectorized_returns
from trader.backtest.metrics import performance
from trader.strategies import build_strategy


def test_backtrader_runs_and_reports(universe):
    strat = build_strategy("sma_crossover", {"fast": 20, "slow": 100})
    res = run_backtest(universe, strat, cash=100_000, max_position_pct=0.25,
                       benchmark=universe["SYM0"])
    assert len(res.equity) == len(universe["SYM0"])
    assert res.stats["trades"] > 0
    assert res.rejected_orders == 0
    assert np.isfinite(res.stats["sharpe"])
    assert res.benchmark is not None


def test_engines_roughly_agree(universe):
    """Vectorized sweep engine should track backtrader closely (it skips share rounding)."""
    strat = build_strategy("sma_crossover", {"fast": 20, "slow": 100})
    kw = dict(slippage_bps=5, max_position_pct=0.25, max_gross_exposure=1.0, cash_buffer=0.02)
    bt_res = run_backtest(universe, strat, cash=1_000_000, rebalance_band=0.0,
                          min_order_value=0, **kw)
    vec = (1 + vectorized_returns(universe, strat, **kw)).cumprod()
    bt_total = bt_res.equity.iloc[-1] / bt_res.equity.iloc[0] - 1
    vec_total = vec.iloc[-1] - 1
    assert abs(bt_total - vec_total) < 0.05, (bt_total, vec_total)


def test_sweep_ranks_and_splits(universe):
    table = run_sweep(universe, "sma_crossover", {"fast": [10, 20], "slow": [50, 100, 10]},
                      split=0.7)
    assert len(table) == 4  # fast=10/20 with slow=10 are invalid and skipped
    assert table["is_sharpe"].is_monotonic_decreasing
    assert "oos_sharpe" in table


def test_performance_basic():
    import pandas as pd
    idx = pd.bdate_range("2020-01-01", periods=253)
    eq = pd.Series(np.linspace(100, 110, 253), index=idx)
    p = performance(eq)
    assert abs(p["total_return"] - 0.10) < 1e-9
    assert p["max_drawdown"] == 0


def test_walk_forward_uses_only_past_for_params(universe):
    from trader.backtest import walk_forward

    wf = walk_forward(universe, "sma_crossover", {"fast": [10, 20], "slow": [50, 100]},
                      train_years=2, test_years=1)
    assert len(wf.windows) >= 2
    # every test window starts after its training window and windows don't overlap
    for _, w in wf.windows.iterrows():
        assert w.train_start < w.test_start <= w.test_end
    assert (wf.windows.test_start.iloc[1:].values > wf.windows.test_end.iloc[:-1].values).all()
    # stitched returns cover only test periods
    assert wf.oos_returns.index[0].date() >= wf.windows.test_start.iloc[0]
    assert wf.oos_returns.index.is_unique


def test_walk_forward_replays_in_backtrader(universe):
    from trader.backtest import walk_forward

    wf = walk_forward(universe, "sma_crossover", {"fast": [10, 20], "slow": [50, 100]},
                      train_years=2, test_years=1)
    res = run_backtest(universe, None, signals=wf.signals, max_position_pct=0.25)
    assert res.equity.index[0] == wf.oos_returns.index[0]
    assert res.stats["trades"] > 0
