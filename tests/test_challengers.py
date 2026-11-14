import numpy as np
import pandas as pd
import pytest

from trader.challengers import Challenger, leaderboard, simulate, target_weight_frame


def _frame(values: dict[str, list[float]]) -> pd.DataFrame:
    idx = pd.bdate_range("2026-01-01", periods=len(next(iter(values.values()))))
    return pd.DataFrame(values, index=idx)


def test_fixed_weights_and_simulation():
    opens = _frame({"A": [100, 110, 121, 121], "B": [50, 50, 50, 50]})
    ch = Challenger("x", "fixed", "2026-01-01", {"weights": {"A": 0.5, "B": 0.5}})
    w = target_weight_frame(ch, opens, cash_buffer=0.0)
    r = simulate(w, opens, slippage_bps=0.0)
    # Day 0 decides, day 1 holds A over open1->open2 (+10%): portfolio +5%.
    assert r.iloc[1] == pytest.approx(0.05)
    assert r.iloc[0] == 0.0


def test_leverage_pays_borrow_cost():
    opens = _frame({"A": [100.0] * 5, "BIL": [100.0] * 5})
    ch = Challenger("x", "fixed", "2026-01-01", {"weights": {"A": 1.0}, "leverage": 1.5})
    w = target_weight_frame(ch, opens, cash_buffer=0.0)
    r = simulate(w, opens, slippage_bps=0.0, tbill=pd.Series(0.0, index=opens.index))
    assert r.iloc[2] == pytest.approx(-0.5 * 0.025 / 252)  # flat prices: only the margin cost


def test_momentum_picks_strongest_at_month_end():
    idx = pd.bdate_range("2025-01-01", "2026-03-31")
    n = len(idx)
    closes = pd.DataFrame({"UP": np.linspace(100, 200, n), "FLAT": np.full(n, 100.0),
                           "DOWN": np.linspace(100, 50, n)}, index=idx)
    ch = Challenger("m", "momentum", "2025-01-01",
                    {"lookback": 60, "skip": 5, "top": 1, "symbols": ["UP", "FLAT", "DOWN"]})
    w = target_weight_frame(ch, closes, cash_buffer=0.0)
    assert w.loc["2026-03-31", "UP"] == 1.0 and w.loc["2026-03-31"].sum() == 1.0


def test_leaderboard_counts_only_days_after_since():
    opens = _frame({"A": [100, 101, 102, 103, 104, 105]})
    bars = {"A": pd.DataFrame({"open": opens.A, "close": opens.A})}
    ch = Challenger("x", "fixed", str(opens.index[2].date()), {"weights": {"A": 1.0}})
    lb = leaderboard([ch], bars, slippage_bps=0.0)
    assert lb.loc["x", "days"] == 2  # days 3 and 4; day 5 needs tomorrow's open


def test_leaderboard_starts_when_every_fund_exists():
    idx = pd.bdate_range("2026-01-01", periods=8)
    a = pd.Series([100, 101, 102, 103, 104, 105, 106, 107.0], index=idx)
    b = pd.Series([None, None, None, 50, 51, 52, 53, 54.0], index=idx)   # launches on day 3
    bars = {"A": pd.DataFrame({"open": a, "close": a}), "B": pd.DataFrame({"open": b, "close": b})}
    ch = Challenger("x", "fixed", "2026-01-01", {"weights": {"A": 0.5, "B": 0.5}})
    lb = leaderboard([ch], bars, slippage_bps=0.0, cash_buffer=0.0)
    assert str(lb.loc["x", "since"]) == str(idx[3].date())
    assert lb.loc["x", "days"] == 3   # days 4-6; day 7 needs tomorrow's open


def test_summarize_short_records_are_not_zeroed():
    from trader.challengers import summarize
    r = pd.Series([-0.037], index=pd.to_datetime(["2026-11-05"]))
    s = summarize(r)
    assert s["days"] == 1
    assert s["total_return"] == pytest.approx(-0.037)
    assert s["max_drawdown"] == pytest.approx(-0.037)   # a first-day loss is a drawdown
    assert np.isnan(s["cagr"]) and np.isnan(s["sharpe"])  # too few days to annualise


def test_trend_leverage_switches_with_the_trend():
    idx = pd.bdate_range("2025-01-01", periods=30)
    up = np.r_[np.linspace(100, 120, 20), np.linspace(119, 90, 10)]
    closes = pd.DataFrame({"SPY": up, "QQQ": up}, index=idx)
    ch = Challenger("t", "fixed", "2025-01-01",
                    {"weights": {"SPY": 0.5, "QQQ": 0.5},
                     "trend_leverage": {"symbol": "SPY", "window": 5, "above": 1.3, "below": 1.0}})
    w = target_weight_frame(ch, closes, cash_buffer=0.0)
    assert w.iloc[3].sum() == pytest.approx(1.0)    # warm-up: no average yet -> off
    assert w.iloc[15].sum() == pytest.approx(1.3)   # rising: above the average -> on
    assert w.iloc[-1].sum() == pytest.approx(1.0)   # falling: below the average -> off
