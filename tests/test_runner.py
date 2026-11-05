"""LiveRunner against a fake broker: no network, no real orders."""
from types import SimpleNamespace

import pytest

from conftest import make_bars
from trader.config import Credentials


class FakeBroker:
    def __init__(self, positions, prices):
        self.paper = True
        self._positions = positions
        self._prices = prices
        self.submitted = []

    def clock(self):
        return SimpleNamespace(is_open=True, next_open=None)

    def account(self):
        return SimpleNamespace(trading_blocked=False, account_blocked=False,
                               equity="100000", last_equity="100000", cash="72000")  # + 28k in AAPL/NVDA

    def positions(self):
        return dict(self._positions)

    def open_order_symbols(self):
        return set()

    def latest_prices(self, symbols):
        return {s: self._prices[s] for s in symbols if s in self._prices}

    def submit_market(self, symbol, delta):
        self.submitted.append((symbol, delta))
        return SimpleNamespace(id=f"id-{symbol}")


def _settings(tmp_path, liquidate):
    return {
        "symbols": ["SPY", "QQQ"],
        "data": {"feed": "iex", "adjustment": "all", "cache_dir": str(tmp_path / "c")},
        "strategy": {"name": "buy_and_hold", "params": {}},
        "portfolio": {"cash_buffer": 0.02, "rebalance_band": 0.10},
        "risk": {"max_position_pct": 0.5, "max_gross_exposure": 1.0,
                 "daily_loss_limit_pct": 0.03, "max_orders_per_run": 20, "min_order_value": 100,
                 "kill_switch_file": str(tmp_path / "KILL"),
                 "liquidate_outside_universe": liquidate},
        "live": {"run_minutes_after_open": 5, "lookback_days": 30, "log_dir": str(tmp_path / "logs")},
    }


@pytest.fixture
def runner_factory(monkeypatch, tmp_path):
    import trader.live.runner as R

    def make(liquidate):
        broker = FakeBroker(positions={"AAPL": 100, "NVDA": 50},
                            prices={"SPY": 500.0, "QQQ": 400.0, "AAPL": 200.0, "NVDA": 160.0})
        monkeypatch.setattr(R, "load_credentials", lambda: Credentials("k", "s", True))
        monkeypatch.setattr(R, "AlpacaBroker", lambda creds: broker)
        bars = {s: make_bars(n=60, start="2026-08-01", seed=i) for i, s in enumerate(["SPY", "QQQ"])}
        monkeypatch.setattr(R, "load_bars", lambda symbols, start, **kw: bars)
        return R.LiveRunner(_settings(tmp_path, liquidate)), broker

    return make


def test_liquidates_positions_outside_universe(runner_factory):
    runner, broker = runner_factory(liquidate=True)
    runner.run_once()
    orders = dict(broker.submitted)
    assert orders["AAPL"] == -100 and orders["NVDA"] == -50       # strays closed in full
    assert orders["SPY"] == int(100_000 * 0.49 / 500)               # 49% each after the 2% buffer
    assert orders["QQQ"] == int(100_000 * 0.49 / 400)
    assert [s for s, d in broker.submitted if d < 0] == ["AAPL", "NVDA"]  # sells go first


def test_ignores_strays_by_default(runner_factory):
    runner, broker = runner_factory(liquidate=False)
    runner.run_once()
    assert set(dict(broker.submitted)) == {"SPY", "QQQ"}


def test_dry_run_sends_nothing(runner_factory):
    runner, broker = runner_factory(liquidate=True)
    runner.dry_run = True
    runner.run_once()
    assert broker.submitted == []
