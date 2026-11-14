"""Trade ledger: every closed trade, its P&L, and why it made or lost money.

Fills come from Alpaca's order history (the source of truth). They are matched first-in,
first-out into closed trades. Each one is enriched from the runner's journal (decision price
and close reason) and attributed:

    pnl = market_pnl + selection_pnl
      market_pnl:     what the benchmark did over the same holding period, on the same money
      selection_pnl:  the rest (this symbol vs the benchmark), execution costs included
    execution_cost:   fills vs decision prices on both legs (positive = cost), shown separately

Lessons should come from patterns across many trades, not from single trades (see CLAUDE.md).
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

LEDGER_COLUMNS = ["symbol", "opened", "closed", "days", "qty", "entry", "exit", "pnl", "return",
                  "market_pnl", "selection_pnl", "execution_cost", "close_reason",
                  "entry_order", "exit_order"]


@dataclass(frozen=True)
class Fill:
    symbol: str
    side: str          # "buy" or "sell"
    qty: float         # always positive
    price: float
    time: datetime
    order_id: str


@dataclass
class JournalInfo:
    """What the runner recorded about an order when it decided to place it."""
    ref_price: float | None
    reason: str


def journal_index(journal_path: Path) -> dict[str, JournalInfo]:
    """order id -> decision price and the reason for the order (from logs/journal.jsonl)."""
    out: dict[str, JournalInfo] = {}
    if not journal_path.exists():
        return out
    for line in journal_path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        signals = rec.get("signals") or {}
        weights = rec.get("weights") or {}
        refs = rec.get("ref_prices") or {}
        for sub in rec.get("submitted") or []:
            sym = sub["symbol"]
            if sub["qty"] > 0:
                reason = "entry/top-up"
            elif sym not in signals:
                reason = "left universe"            # e.g. a strategy switch
            elif weights.get(sym, 0.0) == 0.0:
                reason = "signal exit"
            else:
                reason = "rebalance trim"
            out[sub["id"]] = JournalInfo(refs.get(sym), reason)
    return out


def match_fifo(fills: Iterable[Fill]) -> tuple[list[dict], dict[str, list[dict]], list[str]]:
    """FIFO-match fills into closed lots. Returns (closed trades, open lots by symbol, warnings)."""
    lots: dict[str, deque] = defaultdict(deque)
    closed: list[dict] = []
    warnings: list[str] = []
    for f in sorted(fills, key=lambda f: f.time):
        if f.side == "buy":
            lots[f.symbol].append({"qty": f.qty, "price": f.price, "time": f.time, "order": f.order_id})
            continue
        remaining = f.qty
        while remaining > 1e-9 and lots[f.symbol]:
            lot = lots[f.symbol][0]
            q = min(lot["qty"], remaining)
            closed.append({"symbol": f.symbol, "qty": q, "entry": lot["price"], "opened": lot["time"],
                           "entry_order": lot["order"], "exit": f.price, "closed": f.time,
                           "exit_order": f.order_id})
            lot["qty"] -= q
            remaining -= q
            if lot["qty"] <= 1e-9:
                lots[f.symbol].popleft()
        if remaining > 1e-9:
            warnings.append(f"{f.symbol}: sold {remaining:g} shares with no matching buy in the "
                            f"ledger window (bought before it started?)")
    open_lots = {s: list(q) for s, q in lots.items() if q}
    return closed, open_lots, warnings


def build_ledger(fills: Iterable[Fill], journal: dict[str, JournalInfo],
                 bench_price: Callable[[datetime], float | None]) -> tuple[pd.DataFrame, list[str]]:
    """Closed-trade table with P&L attribution. `bench_price(t)` gives the benchmark near time t."""
    closed, _, warnings = match_fifo(fills)
    rows = []
    for t in closed:
        q, entry, exit_ = t["qty"], t["entry"], t["exit"]
        pnl = q * (exit_ - entry)
        b0, b1 = bench_price(t["opened"]), bench_price(t["closed"])
        market = q * entry * (b1 / b0 - 1) if b0 and b1 else float("nan")
        ji_in, ji_out = journal.get(t["entry_order"]), journal.get(t["exit_order"])
        cost = float("nan")
        if ji_in and ji_out and ji_in.ref_price and ji_out.ref_price:
            cost = q * (entry - ji_in.ref_price) + q * (ji_out.ref_price - exit_)
        rows.append({
            "symbol": t["symbol"], "opened": t["opened"].date(), "closed": t["closed"].date(),
            "days": (t["closed"].date() - t["opened"].date()).days, "qty": q,
            "entry": entry, "exit": exit_, "pnl": pnl, "return": exit_ / entry - 1,
            "market_pnl": market, "selection_pnl": pnl - market if market == market else float("nan"),
            "execution_cost": cost,
            "close_reason": ji_out.reason if ji_out else "unknown (not in journal)",
            "entry_order": t["entry_order"], "exit_order": t["exit_order"],
        })
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS), warnings


def summarize_ledger(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"trades": 0}
    wins = df[df.pnl > 0]
    losses = df[df.pnl <= 0]
    return {
        "trades": len(df),
        "win_rate": len(wins) / len(df),
        "total_pnl": df.pnl.sum(),
        "market_pnl": df.market_pnl.sum(skipna=True),
        "selection_pnl": df.selection_pnl.sum(skipna=True),
        "execution_cost": df.execution_cost.sum() if df.execution_cost.notna().any() else float("nan"),
        "execution_known": int(df.execution_cost.notna().sum()),
        "avg_win": wins.pnl.mean() if len(wins) else 0.0,
        "avg_loss": losses.pnl.mean() if len(losses) else 0.0,
        "by_reason": df.groupby("close_reason").pnl.agg(["count", "sum"]).to_dict("index"),
    }


def fills_from_alpaca(trading_client, since: datetime) -> list[Fill]:
    """All filled (or partially filled) orders since `since`, oldest first, paginated."""
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest

    out: list[Fill] = []
    after = since
    seen: set[str] = set()
    while True:
        batch = trading_client.get_orders(GetOrdersRequest(
            status=QueryOrderStatus.CLOSED, after=after, limit=500, direction="asc"))
        new = [o for o in batch if str(o.id) not in seen]
        for o in new:
            seen.add(str(o.id))
            if o.filled_at and o.filled_qty and float(o.filled_qty) > 0:
                out.append(Fill(o.symbol, o.side.value, float(o.filled_qty),
                                float(o.filled_avg_price), o.filled_at, str(o.id)))
        if len(batch) < 500 or not new:
            break
        after = max(o.submitted_at for o in batch)
    return out


def bench_lookup(bench_bars: pd.DataFrame, live_price: float | None = None,
                 intraday: Callable[[datetime], float | None] | None = None
                 ) -> Callable[[datetime], float | None]:
    """Benchmark price at a fill time. `intraday(t)` (the minute bar of the fill) is used first:
    fills land minutes after the open, and on a fast day the open alone can be 1% off, which
    then shows up as fake selection P&L. Fallbacks: that day's open, then `live_price` (today)."""
    opens = bench_bars["open"] if bench_bars is not None and len(bench_bars) else pd.Series(dtype=float)

    def price(t: datetime) -> float | None:
        if intraday is not None:
            try:
                p = intraday(t)
            except Exception:  # no minute data (too recent, feed refused): fall back
                p = None
            if p:
                return float(p)
        day = pd.Timestamp(pd.Timestamp(t).tz_convert("America/New_York").date()) \
            if pd.Timestamp(t).tzinfo else pd.Timestamp(pd.Timestamp(t).date())
        if day in opens.index:
            return float(opens.loc[day])
        return live_price
    return price


def account_ledger(broker, *, journal_path: Path, load_bars, data_cfg: dict, bench: str,
                   since: str) -> tuple[pd.DataFrame, list[str]]:
    """Ledger for the live account: Alpaca fills + journal + benchmark attribution."""
    from datetime import timezone
    start = datetime.fromisoformat(since).replace(tzinfo=timezone.utc)
    fills = fills_from_alpaca(broker.trading, start)
    bars = load_bars([bench], since, feed=data_cfg["feed"], adjustment=data_cfg["adjustment"],
                     cache_dir=data_cfg["cache_dir"]).get(bench)
    live = broker.latest_prices([bench]).get(bench)
    return build_ledger(fills, journal_index(journal_path),
                        bench_lookup(bars, live, minute_price(broker.data, bench, data_cfg["feed"])))


def minute_price(data_client, symbol: str, feed: str) -> Callable[[datetime], float | None]:
    """Close of the 1-minute bar containing time t (cached per minute)."""
    from alpaca.data.enums import DataFeed
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    cache: dict[pd.Timestamp, float | None] = {}

    def price(t: datetime) -> float | None:
        minute = pd.Timestamp(t).floor("min")
        if minute not in cache:
            req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Minute,
                                   start=minute.to_pydatetime(),
                                   end=(minute + pd.Timedelta(minutes=1)).to_pydatetime(),
                                   adjustment="raw", feed=DataFeed(feed))
            df = data_client.get_stock_bars(req).df
            cache[minute] = float(df["close"].iloc[0]) if len(df) else None
        return cache[minute]
    return price
