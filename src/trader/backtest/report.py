"""Console summary + files (equity.csv, trades.csv, summary.json, chart.png)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .engine import BacktestResult  # noqa: E402
from .metrics import drawdown  # noqa: E402

PCT = {"total_return", "cagr", "volatility", "max_drawdown", "win_rate", "exposure"}
ORDER = ["total_return", "cagr", "volatility", "sharpe", "sortino", "max_drawdown", "calmar",
         "trades", "win_rate", "profit_factor", "avg_trade_pnl", "avg_bars_held", "exposure",
         "final_equity"]


def _fmt(key: str, value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float) and value != value:  # NaN
        return "n/a"
    if key in PCT:
        return f"{value:8.2%}"
    if key in ("final_equity", "avg_trade_pnl"):
        return f"{value:>12,.2f}"
    if isinstance(value, int):
        return f"{value:8d}"
    return f"{value:8.2f}"


def print_summary(result: BacktestResult, title: str) -> None:
    eq = result.equity
    print(f"\n{title}\n{eq.index[0].date()} -> {eq.index[-1].date()}  ({len(eq)} bars)")
    has_bench = result.benchmark_stats is not None
    print(f"{'':16}{'Strategy':>14}" + (f"{'Benchmark':>14}" if has_bench else ""))
    for key in ORDER:
        if key not in result.stats:
            continue
        line = f"{key:16}{_fmt(key, result.stats[key]):>14}"
        if has_bench:
            line += f"{_fmt(key, result.benchmark_stats.get(key)):>14}"
        print(line)
    if result.rejected_orders:
        print(f"\n! {result.rejected_orders} orders rejected for insufficient cash")


def save_report(result: BacktestResult, results_dir: str, label: str) -> Path:
    out = Path(results_dir) / f"{datetime.now():%Y%m%d_%H%M%S}_{label}"
    out.mkdir(parents=True, exist_ok=True)

    frame = result.equity.to_frame()
    if result.benchmark is not None:
        frame = frame.join(result.benchmark)
    frame.to_csv(out / "equity.csv")
    result.trades.to_csv(out / "trades.csv", index=False)
    result.signals.to_csv(out / "signals.csv")
    with open(out / "summary.json", "w") as f:
        json.dump({"strategy": label, "stats": result.stats,
                   "benchmark": result.benchmark_stats}, f, indent=2, default=str)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(result.equity.index, result.equity, label="Strategy", lw=1.4, color="tab:blue")
    if result.benchmark is not None:
        ax1.plot(result.benchmark.index, result.benchmark, label="Benchmark", lw=1.0, alpha=0.7,
                 color="tab:orange")
    ax1.set_yscale("log")
    ax1.set_title(label)
    ax1.set_ylabel("Equity (log)")
    ax1.legend()
    ax1.grid(alpha=0.3)
    dd = drawdown(result.equity)
    ax2.fill_between(dd.index, dd, 0, alpha=0.4, color="tab:blue")
    if result.benchmark is not None:
        ax2.plot(result.benchmark.index, drawdown(result.benchmark), lw=0.8, alpha=0.6,
                 color="tab:orange")
    ax2.set_ylabel("Drawdown")
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "chart.png", dpi=120)
    plt.close(fig)
    return out
