"""Event-driven backtest with backtrader.

Signals are computed up-front by the shared Strategy classes and fed to backtrader as an
extra data line. Orders placed at bar t's close fill at bar t+1's open (with slippage),
which matches how the live runner trades (shortly after the open, on yesterday's bar).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import backtrader as bt
import pandas as pd

from ..portfolio import plan_orders, target_weights
from ..strategies import Strategy
from .metrics import performance, trade_stats

log = logging.getLogger(__name__)


class SignalData(bt.feeds.PandasData):
    lines = ("signal",)
    params = (("signal", -1),)  # -1 = find a column named "signal"


class PortfolioStrategy(bt.Strategy):
    params = dict(max_position_pct=0.2, max_gross_exposure=1.0, cash_buffer=0.02,
                  rebalance_band=0.25, min_order_value=100.0)

    def __init__(self) -> None:
        self.equity: list[tuple] = []
        self.trades: list[dict] = []
        self.rejected = 0

    def notify_order(self, order: bt.Order) -> None:
        if order.status in (order.Margin, order.Rejected):
            self.rejected += 1
            log.debug("Order rejected %s %s", order.data._name, order.getstatusname())

    def notify_trade(self, trade: bt.Trade) -> None:
        if trade.isclosed:
            self.trades.append({
                "symbol": trade.data._name,
                "opened": bt.num2date(trade.dtopen).date(),
                "closed": bt.num2date(trade.dtclose).date(),
                "bars": trade.barlen,
                "pnl": trade.pnl,
                "pnl_net": trade.pnlcomm,
            })

    def next(self) -> None:
        dt = self.datas[0].datetime.date(0)
        value = self.broker.getvalue()
        self.equity.append((pd.Timestamp(dt), value))

        signals = {d._name: float(d.signal[0]) for d in self.datas}
        weights = target_weights(signals, max_position_pct=self.p.max_position_pct,
                                 max_gross_exposure=self.p.max_gross_exposure,
                                 cash_buffer=self.p.cash_buffer)
        orders = plan_orders(
            equity=value, weights=weights,
            prices={d._name: float(d.close[0]) for d in self.datas},
            current_shares={d._name: self.getposition(d).size for d in self.datas},
            rebalance_band=self.p.rebalance_band, min_order_value=self.p.min_order_value,
            cash=self.broker.getcash(), cash_reserve=value * self.p.cash_buffer,
        )
        by_name = {d._name: d for d in self.datas}
        for sym, delta in sorted(orders.items(), key=lambda kv: kv[1]):  # sells first
            if delta < 0:
                self.sell(data=by_name[sym], size=-delta)
            else:
                self.buy(data=by_name[sym], size=delta)


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: pd.DataFrame
    stats: dict
    benchmark: pd.Series | None = None
    benchmark_stats: dict | None = None
    signals: pd.DataFrame = field(default_factory=pd.DataFrame)
    rejected_orders: int = 0


def align(bars: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Restrict all symbols to their common trading dates."""
    common = None
    for df in bars.values():
        common = df.index if common is None else common.intersection(df.index)
    for sym, df in bars.items():
        dropped = len(df) - len(common)
        if dropped > 5:
            log.warning("%s: dropped %d bars to align with other symbols "
                        "(starts %s; common start %s)", sym, dropped, df.index[0].date(), common[0].date())
    return {s: df.loc[common] for s, df in bars.items()}


def run_backtest(bars: dict[str, pd.DataFrame], strategy: Strategy | None, *, cash: float = 100_000,
                 slippage_bps: float = 5.0, commission_per_share: float = 0.0,
                 cash_buffer: float = 0.02, rebalance_band: float = 0.25,
                 max_position_pct: float = 0.2, max_gross_exposure: float = 1.0,
                 min_order_value: float = 100.0,
                 benchmark: pd.DataFrame | None = None,
                 signals: dict[str, pd.Series] | None = None) -> BacktestResult:
    """Run a backtest. Pass `signals` to replay precomputed signals (e.g. walk-forward)
    instead of computing them from `strategy`; bars are then trimmed to the signal dates."""
    if not bars:
        raise ValueError("no data to backtest")
    bars = align(bars)
    if signals is not None:
        start = min(sig.index[0] for sig in signals.values())
        bars = {s: df.loc[start:] for s, df in bars.items()}

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(cash)
    cerebro.broker.set_slippage_perc(slippage_bps / 10_000, slip_open=True, slip_match=True)
    if commission_per_share:
        cerebro.broker.setcommission(commission=commission_per_share,
                                     commtype=bt.CommInfoBase.COMM_FIXED, stocklike=True)

    signal_frame = {}
    for sym, df in bars.items():
        feed_df = df.copy()
        feed_df["signal"] = (signals[sym].reindex(df.index).fillna(0.0) if signals is not None
                             else strategy.signals(df))
        signal_frame[sym] = feed_df["signal"]
        cerebro.adddata(SignalData(dataname=feed_df), name=sym)

    cerebro.addstrategy(PortfolioStrategy, max_position_pct=max_position_pct,
                        max_gross_exposure=max_gross_exposure, cash_buffer=cash_buffer,
                        rebalance_band=rebalance_band, min_order_value=min_order_value)
    strat = cerebro.run()[0]

    equity = pd.Series(dict(strat.equity), name="equity").sort_index()
    trades = pd.DataFrame(strat.trades,
                          columns=["symbol", "opened", "closed", "bars", "pnl", "pnl_net"])
    stats = {**performance(equity), **trade_stats(trades),
             "final_equity": float(equity.iloc[-1]),
             "exposure": float((pd.DataFrame(signal_frame).sum(axis=1) > 0).mean())}
    if strat.rejected:
        log.warning("%d orders were rejected for insufficient cash; "
                    "consider a larger cash_buffer", strat.rejected)

    bench = bench_stats = None
    if benchmark is not None and not benchmark.empty:
        b = benchmark["close"].reindex(equity.index).ffill().dropna()
        if not b.empty:
            bench = (b / b.iloc[0] * cash).rename("benchmark")
            bench_stats = performance(bench)

    return BacktestResult(equity, trades, stats, bench, bench_stats,
                          pd.DataFrame(signal_frame), strat.rejected)
