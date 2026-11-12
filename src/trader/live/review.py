"""`trader review`: the evidence a review session needs, as Markdown.

1. Account vs benchmark since trading began.
2. Execution quality: real fill prices vs the price the runner decided on (journal ref_prices).
3. Challenger leaderboard: forward (out-of-sample) record since each one was registered,
   plus the 2017+ backtest for context.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pandas as pd

from ..challengers import leaderboard, load_challengers


def _pct(x) -> str:
    return "n/a" if pd.isna(x) else f"{x:+.2%}"


def slippage_table(journal_path: Path, get_order) -> pd.DataFrame:
    """One row per filled order that has a decision price in the journal.

    slippage_bps > 0 means we paid more than the decision price on a buy (or got less on a sell).
    """
    rows = []
    if not journal_path.exists():
        return pd.DataFrame()
    for line in journal_path.read_text().splitlines():
        rec = json.loads(line)
        refs = rec.get("ref_prices") or {}
        for sub in rec.get("submitted") or []:
            ref = refs.get(sub["symbol"])
            if not ref:
                continue
            try:
                o = get_order(sub["id"])
            except Exception:  # order no longer retrievable
                continue
            if not o.filled_avg_price:
                continue
            fill = float(o.filled_avg_price)
            side = 1 if sub["qty"] > 0 else -1
            rows.append({"date": str(rec["time"])[:10], "symbol": sub["symbol"], "qty": sub["qty"],
                         "ref": ref, "fill": fill,
                         "slippage_bps": side * (fill - ref) / ref * 1e4})
    return pd.DataFrame(rows)


def build_review(settings: dict, broker, *, memory_dir: Path, log_dir: Path,
                 load_bars, account_since: str | None = None) -> str:
    from .report import account_equity_history, compare_to_benchmark

    out: list[str] = [f"# Review {pd.Timestamp.now(tz='America/New_York').date()}", ""]

    # 1. Account vs benchmark -------------------------------------------------
    bench = settings["backtest"].get("benchmark", "SPY")
    d = settings["data"]
    eq = account_equity_history(broker.trading, float(broker.account().equity))
    eq = eq[eq > 0]
    if account_since:
        eq = eq[eq.index >= pd.Timestamp(account_since)]
    out.append("## Account vs benchmark")
    if len(eq):
        b = load_bars([bench], (eq.index[0] - timedelta(days=10)).date().isoformat(),
                      feed=d["feed"], adjustment=d["adjustment"], cache_dir=d["cache_dir"])[bench]
        close = b["close"].copy()
        live = broker.latest_prices([bench]).get(bench)
        if live:
            close.loc[eq.index[-1]] = live
        t = compare_to_benchmark(eq, close).iloc[-1]
        out.append(f"Since {eq.index[0].date()}: account {_pct(t['account_return'])}, "
                   f"{bench} {_pct(t['benchmark_return'])}, difference {_pct(t['difference'])} "
                   f"({len(eq)} days, equity {eq.iloc[-1]:,.2f}).")
    else:
        out.append("No equity history yet.")
    out.append("")

    # 2. Execution quality ----------------------------------------------------
    out.append("## Execution (fill vs decision price)")
    slip = slippage_table(log_dir / "journal.jsonl", broker.trading.get_order_by_id)
    model = settings["backtest"]["slippage_bps"]
    if slip.empty:
        out.append("No fills with recorded decision prices yet.")
    else:
        out.append(f"{len(slip)} fills; mean slippage {slip.slippage_bps.mean():+.1f} bps, "
                   f"median {slip.slippage_bps.median():+.1f} bps, worst {slip.slippage_bps.max():+.1f} bps "
                   f"(backtests assume {model} bps per side).")
        out.append("")
        out.append(slip.tail(20).to_markdown(index=False, floatfmt=".2f"))
    out.append("")

    # 3. Challengers ----------------------------------------------------------
    chs = load_challengers(memory_dir / "challengers.yaml")
    champion = (__import__("yaml").safe_load((memory_dir / "challengers.yaml").read_text())
                or {}).get("champion")
    syms = sorted({s for c in chs for s in c.symbols()} | {"BIL", bench})
    first = min(pd.Timestamp(c.since) for c in chs)
    bars = load_bars(syms, (first - timedelta(days=420)).date().isoformat(), feed=d["feed"],
                     adjustment=d["adjustment"], cache_dir=d["cache_dir"])
    buf = settings.get("portfolio", {}).get("cash_buffer", 0.02)
    fwd = leaderboard(chs, bars, slippage_bps=model, cash_buffer=buf)
    out.append(f"## Challengers: forward record (champion: {champion})")
    out.append("Out-of-sample: each strategy is judged only on days after it was registered.")
    out.append("")
    out.append(_fmt(fwd).to_markdown())
    out.append("")
    hist_bars = load_bars(syms, "2016-01-01", feed=d["feed"], adjustment=d["adjustment"],
                          cache_dir=d["cache_dir"])
    hist = leaderboard(chs, hist_bars, slippage_bps=model, since="2017-01-03", cash_buffer=buf)
    out.append("## Challengers: backtest 2017 to now (context only; in-sample for anything tuned on it)")
    out.append("")
    out.append(_fmt(hist).to_markdown())
    return "\n".join(out) + "\n"


def _fmt(df: pd.DataFrame) -> pd.DataFrame:
    f = df.copy()
    for c in ("total_return", "cagr", "max_drawdown"):
        f[c] = f[c].map(_pct)
    f["sharpe"] = f["sharpe"].map(lambda x: "n/a" if pd.isna(x) else f"{x:.2f}")
    return f
