"""`trader dashboard-export`: the CSVs behind the visual dashboard.

Files (one per dataset on the dashboard):
  equity.csv       daily account equity vs the benchmark, rebased to the first day
  account.csv      one row: today's equity, cash, invested share and returns
  positions.csv    current holdings with weights and unrealised P&L
  challengers.csv  forward record (and 2017+ backtest) of every tracked strategy
  trades.csv       closed-trade ledger with P&L attribution
  fills.csv        fill price vs decision price for each order
No account numbers or credentials are written.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yaml


def export_dashboard(settings: dict, broker, *, out_dir: Path, memory_dir: Path, log_dir: Path,
                     load_bars, start: str = "2026-11-03", ledger_since: str = "2026-11-01") -> dict:
    from ..challengers import leaderboard, load_challengers
    from ..ledger import account_ledger
    from .report import account_equity_history, compare_to_benchmark
    from .review import slippage_table

    out_dir.mkdir(parents=True, exist_ok=True)
    d = settings["data"]
    bench = settings["backtest"].get("benchmark", "SPY")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    written = {}

    # Equity vs benchmark --------------------------------------------------
    acct = broker.account()
    equity = account_equity_history(broker.trading, float(acct.equity))
    equity = equity[(equity > 0) & (equity.index >= pd.Timestamp(start))]
    b = load_bars([bench], (equity.index[0] - timedelta(days=10)).date().isoformat(), feed=d["feed"],
                  adjustment=d["adjustment"], cache_dir=d["cache_dir"])[bench]
    close = b["close"].copy()
    live = broker.latest_prices([bench]).get(bench)
    if live:
        close.loc[equity.index[-1]] = live
    t = compare_to_benchmark(equity, close).rename(columns={"benchmark": "benchmark_price"})
    t.index.name = "date"
    t = t.reset_index()
    t["date"] = t["date"].dt.strftime("%Y-%m-%d")
    t.round(6).to_csv(out_dir / "equity.csv", index=False)
    written["equity"] = len(t)

    # Account snapshot -----------------------------------------------------
    eq, cash = float(acct.equity), float(acct.cash)
    last = t.iloc[-1]
    pd.DataFrame([{
        "as_of": now, "equity": round(eq, 2), "cash": round(cash, 2),
        "invested_share": round((eq - cash) / eq, 6) if eq else 0.0,
        "start_date": t.iloc[0]["date"], "start_equity": round(float(t.iloc[0]["equity"]), 2),
        "account_return": round(float(last["account_return"]), 6),
        "benchmark": bench, "benchmark_return": round(float(last["benchmark_return"]), 6),
        "difference": round(float(last["difference"]), 6),
        "difference_abs": round(abs(float(last["difference"])), 6),
        "strategy": ", ".join(settings["symbols"]),
    }]).to_csv(out_dir / "account.csv", index=False)
    written["account"] = 1

    # Positions --------------------------------------------------------------
    rows = []
    for p in broker.trading.get_all_positions():
        mv = float(p.market_value)
        rows.append({"symbol": p.symbol, "qty": float(p.qty), "market_value": round(mv, 2),
                     "weight": round(mv / eq, 6) if eq else 0.0,
                     "avg_entry": round(float(p.avg_entry_price), 4),
                     "price": round(float(p.current_price), 4),
                     "unrealized_pl": round(float(p.unrealized_pl), 2),
                     "unrealized_return": round(float(p.unrealized_plpc), 6)})
    rows.append({"symbol": "Cash", "qty": None, "market_value": round(cash, 2),
                 "weight": round(cash / eq, 6) if eq else 0.0, "avg_entry": None, "price": None,
                 "unrealized_pl": None, "unrealized_return": None})
    pd.DataFrame(rows).to_csv(out_dir / "positions.csv", index=False)
    written["positions"] = len(rows)

    # Challengers -------------------------------------------------------------
    raw = yaml.safe_load((memory_dir / "challengers.yaml").read_text()) or {}
    champion = raw.get("champion")
    chs = load_challengers(memory_dir / "challengers.yaml")
    syms = sorted({s for c in chs for s in c.symbols()} | {"BIL", bench})
    model = settings["backtest"]["slippage_bps"]
    buf = settings.get("portfolio", {}).get("cash_buffer", 0.02)
    first = min(pd.Timestamp(c.since) for c in chs)
    fwd = leaderboard(chs, load_bars(syms, (first - timedelta(days=420)).date().isoformat(),
                                     feed=d["feed"], adjustment=d["adjustment"],
                                     cache_dir=d["cache_dir"]),
                      slippage_bps=model, cash_buffer=buf)
    hist = leaderboard(chs, load_bars(syms, "2016-01-01", feed=d["feed"], adjustment=d["adjustment"],
                                      cache_dir=d["cache_dir"]),
                       slippage_bps=model, since="2017-01-03", cash_buffer=buf)
    ch = pd.DataFrame({
        "strategy": fwd.index, "since": [str(x) for x in fwd["since"]], "days": fwd["days"].values,
        "forward_return": fwd["total_return"].round(6).values,
        "forward_max_drawdown": fwd["max_drawdown"].round(6).values,
        "backtest_cagr": hist["cagr"].round(6).values, "backtest_sharpe": hist["sharpe"].round(3).values,
        "backtest_max_drawdown": hist["max_drawdown"].round(6).values,
        "is_live": [n == champion for n in fwd.index],
        "note": [c.note for c in chs],
    })
    ch.to_csv(out_dir / "challengers.csv", index=False)
    written["challengers"] = len(ch)

    # Trades and fills ---------------------------------------------------------
    led, _ = account_ledger(broker, journal_path=log_dir / "journal.jsonl", load_bars=load_bars,
                            data_cfg=d, bench=bench, since=ledger_since)
    cols = ["symbol", "opened", "closed", "days", "qty", "entry", "exit", "pnl", "return",
            "market_pnl", "selection_pnl", "execution_cost", "close_reason"]
    led = led[cols] if not led.empty else pd.DataFrame(columns=cols)
    led.round(4).to_csv(out_dir / "trades.csv", index=False)
    written["trades"] = len(led)
    slip = slippage_table(log_dir / "journal.jsonl", broker.trading.get_order_by_id)
    if slip.empty:
        slip = pd.DataFrame(columns=["date", "symbol", "qty", "ref", "fill", "slippage_bps"])
    slip.round(4).to_csv(out_dir / "fills.csv", index=False)
    written["fills"] = len(slip)
    return written
