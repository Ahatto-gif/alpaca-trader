import pandas as pd
import pytest

from trader.live.report import compare_to_benchmark


def test_compare_rebases_and_skips_unfunded_days():
    idx = pd.to_datetime(["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"])
    equity = pd.Series([0.0, 100_000, 101_000, 99_000], index=idx)
    # Benchmark has no bar on the 4th (holiday) -> uses the last known close.
    bench = pd.Series([400.0, 410.0, 420.0], index=idx[:3])
    t = compare_to_benchmark(equity, bench)
    assert list(t.index) == list(idx[1:])          # unfunded day dropped
    assert t["account_return"].tolist() == pytest.approx([0.0, 0.01, -0.01])
    assert t["benchmark_return"].tolist() == pytest.approx([0.0, 420 / 410 - 1, 420 / 410 - 1])
    assert t["difference"].iloc[-1] == pytest.approx(-0.01 - (420 / 410 - 1))


def test_compare_needs_history():
    with pytest.raises(ValueError):
        compare_to_benchmark(pd.Series([0.0], index=pd.to_datetime(["2026-11-01"])),
                             pd.Series([1.0], index=pd.to_datetime(["2026-11-01"])))
