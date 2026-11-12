import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from trader.ledger import (Fill, JournalInfo, bench_lookup, build_ledger, journal_index,
                           match_fifo, summarize_ledger)


def t(day, hour=14, minute=36):
    return datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc)


def test_fifo_matches_partial_lots_and_keeps_the_rest_open():
    fills = [Fill("A", "buy", 10, 100.0, t(2), "b1"), Fill("A", "buy", 10, 110.0, t(3), "b2"),
             Fill("A", "sell", 15, 120.0, t(4), "s1")]
    closed, open_lots, warnings = match_fifo(fills)
    assert [(c["qty"], c["entry"], c["entry_order"]) for c in closed] == [(10, 100.0, "b1"), (5, 110.0, "b2")]
    assert open_lots["A"][0]["qty"] == 5 and not warnings


def test_sell_without_buy_is_warned_not_invented():
    closed, _, warnings = match_fifo([Fill("A", "sell", 5, 10.0, t(2), "s1")])
    assert closed == [] and "no matching buy" in warnings[0]


def test_attribution_and_execution_cost():
    fills = [Fill("A", "buy", 10, 101.0, t(2), "b1"), Fill("A", "sell", 10, 99.0, t(5), "s1")]
    journal = {"b1": JournalInfo(100.0, "entry/top-up"), "s1": JournalInfo(100.0, "signal exit")}
    bench = {t(2): 400.0, t(5): 404.0}                       # benchmark +1%
    df, _ = build_ledger(fills, journal, lambda x: bench.get(x))
    row = df.iloc[0]
    assert row.pnl == pytest.approx(-20.0)
    assert row.market_pnl == pytest.approx(10 * 101.0 * 0.01)  # same money in the benchmark
    assert row.selection_pnl == pytest.approx(-20.0 - 10.1)
    assert row.execution_cost == pytest.approx(10 * 1.0 + 10 * 1.0)  # paid up 1 on each leg
    assert row.close_reason == "signal exit"
    s = summarize_ledger(df)
    assert s["trades"] == 1 and s["win_rate"] == 0 and s["execution_known"] == 1


def test_journal_reasons(tmp_path):
    rec = {"time": "2026-11-05", "signals": {"SPY": 1.0, "QQQ": 0.0, "IWM": 1.0},
           "weights": {"SPY": 0.5, "QQQ": 0.0, "IWM": 0.4, "NVDA": 0.0},
           "submitted": [{"symbol": "SPY", "qty": 3, "id": "a"}, {"symbol": "QQQ", "qty": -2, "id": "b"},
                         {"symbol": "NVDA", "qty": -5, "id": "c"}, {"symbol": "IWM", "qty": -1, "id": "d"}],
           "ref_prices": {"SPY": 700.0}}
    p = tmp_path / "journal.jsonl"
    p.write_text(json.dumps(rec) + "\n")
    j = journal_index(p)
    assert j["a"] == JournalInfo(700.0, "entry/top-up")
    assert j["b"].reason == "signal exit"
    assert j["c"].reason == "left universe"
    assert j["d"].reason == "rebalance trim"


def test_bench_lookup_uses_the_open_then_live_price():
    bars = pd.DataFrame({"open": [500.0]}, index=pd.DatetimeIndex(["2026-11-04"]))
    f = bench_lookup(bars, live_price=510.0)
    assert f(t(4)) == 500.0          # 14:36 UTC on the 4th = 09:36 ET -> that day's open
    assert f(t(9)) == 510.0          # no bar yet -> live price
