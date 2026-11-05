"""Forward-tracked strategies ("challengers") from memory/challengers.yaml.

Each entry is simulated from its `since` date with the same execution model as
backtest/vectorized.py: weights decided at close t are held from open t+1, `slippage_bps`
per side on turnover. Because every challenger is registered *before* the period it is
judged on, its tracked record is genuinely out-of-sample.

Spec kinds:
  fixed:    {weights: {SPY: 0.5, QQQ: 0.5}, leverage: 1.0}
  slots:    {strategy: sma_crossover, params: {...}, symbols: [...]}  (same sizing as live)
  momentum: {lookback: 252, skip: 21, top: 10, symbols: [...]}       (monthly, equal weight)
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .backtest.metrics import performance
from .strategies import build_strategy

BORROW_SPREAD = 0.025  # margin cost above T-bills (BIL) for any leverage, per year


@dataclass
class Challenger:
    name: str
    kind: str
    since: str
    spec: dict
    note: str = ""

    def symbols(self) -> list[str]:
        if self.kind == "fixed":
            return list(self.spec["weights"])
        return list(self.spec["symbols"])


def load_challengers(path: str | Path) -> list[Challenger]:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    out = []
    for name, c in (raw.get("challengers") or {}).items():
        spec = {k: v for k, v in c.items() if k not in ("kind", "since", "note")}
        out.append(Challenger(name, c["kind"], str(c["since"]), spec, c.get("note", "")))
    return out


def _month_end_mask(index: pd.DatetimeIndex) -> np.ndarray:
    s = pd.Series(np.arange(len(index)), index=index)
    last = s.groupby([index.year, index.month]).max().to_numpy()
    mask = np.zeros(len(index), dtype=bool)
    mask[last] = True
    return mask


def target_weight_frame(ch: Challenger, closes: pd.DataFrame, *, cash_buffer: float = 0.02,
                        max_position_pct: float = 1.0) -> pd.DataFrame:
    """Daily target weights (decided at each close) for a challenger."""
    idx = closes.index
    syms = [s for s in ch.symbols() if s in closes]
    w = pd.DataFrame(0.0, index=idx, columns=syms)
    if ch.kind == "fixed":
        lev = float(ch.spec.get("leverage", 1.0))
        for s, x in ch.spec["weights"].items():
            if s in w:
                w[s] = x * lev * (1 - cash_buffer)
        return w
    if ch.kind == "slots":
        strat = build_strategy(ch.spec["strategy"], ch.spec.get("params"))
        n = len(ch.spec["symbols"])
        slot = min(1.0 / n, float(ch.spec.get("max_position_pct", max_position_pct)))
        for s in syms:
            df = closes[[s]].rename(columns={s: "close"}).dropna()
            sig = strat.signals(df.assign(open=df.close, high=df.close, low=df.close, volume=0.0))
            w[s] = sig.reindex(idx).fillna(0.0) * slot * (1 - cash_buffer)
        return w
    if ch.kind == "momentum":
        lb, skip, top = int(ch.spec["lookback"]), int(ch.spec.get("skip", 21)), int(ch.spec["top"])
        c = closes[syms]
        score = c.shift(skip) / c.shift(lb) - 1
        score = score.where(c.notna())
        w[:] = np.nan
        for i in np.flatnonzero(_month_end_mask(idx)):
            row = pd.Series(0.0, index=syms)
            best = score.iloc[i].dropna().nlargest(top)
            if len(best):
                row[best.index] = (1 - cash_buffer) / len(best)
            w.iloc[i] = row
        return w.ffill().fillna(0.0)
    raise ValueError(f"{ch.name}: unknown kind {ch.kind!r}")


def simulate(weights: pd.DataFrame, opens: pd.DataFrame, *, slippage_bps: float = 5.0,
             tbill: pd.Series | None = None) -> pd.Series:
    """Daily returns: weights at close t held over [open t+1, open t+2)."""
    opens = opens.reindex(columns=weights.columns)
    o2o = (opens.shift(-1) / opens - 1)
    o2o = o2o.where(o2o.notna(), 0.0)
    held = weights.shift(1).fillna(0.0)
    turnover = held.diff().abs().fillna(held.abs()).sum(axis=1)
    rets = (held * o2o).sum(axis=1) - turnover * slippage_bps / 10_000
    borrowed = (held.sum(axis=1) - 1.0).clip(lower=0.0)
    if borrowed.any():
        rate = (tbill.reindex(rets.index).fillna(0.0) if tbill is not None else 0.0)
        rets = rets - borrowed * (rate + BORROW_SPREAD / 252)
    return rets


def summarize(rets: pd.Series) -> dict:
    if len(rets) < 2:
        return {"days": len(rets), "total_return": 0.0, "cagr": float("nan"),
                "sharpe": float("nan"), "max_drawdown": 0.0}
    eq = (1 + rets).cumprod()
    p = performance(eq)
    return {"days": len(rets), "total_return": float(eq.iloc[-1] - 1), "cagr": p["cagr"],
            "sharpe": p["sharpe"], "max_drawdown": p["max_drawdown"]}


def leaderboard(challengers: list[Challenger], bars: dict[str, pd.DataFrame], *,
                slippage_bps: float = 5.0, since: str | None = None) -> pd.DataFrame:
    """Forward record of every challenger from its own `since` (or a common `since`)."""
    closes = pd.DataFrame({s: df["close"] for s, df in bars.items()}).sort_index()
    opens = pd.DataFrame({s: df["open"] for s, df in bars.items()}).sort_index()
    tbill = None
    if "BIL" in opens:
        tbill = (opens["BIL"].shift(-1) / opens["BIL"] - 1).fillna(0.0)
    rows = []
    for ch in challengers:
        w = target_weight_frame(ch, closes)
        r = simulate(w, opens, slippage_bps=slippage_bps, tbill=tbill)
        start = pd.Timestamp(since or ch.since)
        # Drop the final row: its open-to-open return needs tomorrow's open.
        r = r[(r.index > start)].iloc[:-1]
        rows.append({"challenger": ch.name, "since": start.date(), **summarize(r)})
    return pd.DataFrame(rows).set_index("challenger")
