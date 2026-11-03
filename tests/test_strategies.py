import pandas as pd
import pytest

from trader.strategies import REGISTRY, build_strategy


@pytest.mark.parametrize("name", list(REGISTRY))
def test_signals_are_bounded_and_aligned(name, bars):
    sig = build_strategy(name).signals(bars)
    assert sig.index.equals(bars.index)
    assert sig.between(0, 1).all()
    assert (sig.iloc[: build_strategy(name).warmup] == 0).all()


@pytest.mark.parametrize("name", list(REGISTRY))
def test_no_lookahead(name, bars):
    """Signal at bar t must not change when future bars are appended."""
    strat = build_strategy(name)
    full = strat.signals(bars)
    cut = 1000
    partial = strat.signals(bars.iloc[:cut])
    pd.testing.assert_series_equal(full.iloc[:cut], partial, check_names=False)


def test_invalid_params_rejected():
    with pytest.raises(ValueError):
        build_strategy("sma_crossover", {"fast": 50, "slow": 20})
    with pytest.raises(ValueError):
        build_strategy("sma_crossover", {"typo": 1})
