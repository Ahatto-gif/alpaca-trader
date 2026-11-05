import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import numpy as np, pandas as pd
import research as R
idx, C, O2O = R.idx, R.C, R.O2O
SPREAD = 0.025 / 252          # margin rate = T-bill (BIL) + 2.5%/yr on borrowed money
bil = O2O["BIL"]

def lev_returns(w):
    """Like R.returns, but gross exposure may exceed 1; borrowed part pays T-bill + spread."""
    w = w.reindex(columns=O2O.columns, fill_value=0.0).fillna(0.0)
    held = w.shift(1).fillna(0.0)
    turn = held.diff().abs().fillna(held.abs()).sum(axis=1)
    gross = held.sum(axis=1)
    cash = 1 - gross   # negative = borrowed
    fin = np.where(cash < 0, cash * (bil + SPREAD), 0.0)   # idle cash earns nothing (conservative)
    r = (held * O2O).sum(axis=1) + fin - turn * R.SLIP / 1e4
    return r[r.index >= R.START]

def trend_on(sym="SPY", n=200, band=0.0, daily=True):
    c = C[sym]; ma = c.rolling(n).mean()
    on = pd.Series(np.nan, index=idx)
    on[c > ma * (1 + band)] = 1.0; on[c < ma * (1 - band)] = 0.0
    on = on.ffill().fillna(0.0)
    if not daily:  # only act on month-ends
        m = pd.Series(np.nan, index=idx); mask = idx.isin(list(R.REB)); m[mask] = on[mask]
        on = m.ffill().fillna(0.0)
    return on

def mix(alloc, lev, on=None, off=None):
    w = pd.DataFrame(0.0, index=idx, columns=O2O.columns)
    for k, v in alloc.items(): w[k] = v * lev * (1 - R.BUF)
    if on is not None:
        w = w.mul(on, axis=0)
        if off:
            w[off] = w[off] + (1 - on) * (1 - R.BUF)
    return w

rows = {}
for name, alloc in {"SPY": {"SPY": 1}, "QQQ": {"QQQ": 1}, "50/50": {"SPY": .5, "QQQ": .5}}.items():
    for lev in (1.0, 1.5, 2.0):
        rows[f"{name} x{lev} always"] = lev_returns(mix(alloc, lev))
        rows[f"{name} x{lev} SPY>200d daily->cash"] = lev_returns(mix(alloc, lev, trend_on()))
        rows[f"{name} x{lev} SPY>200d 2%band->cash"] = lev_returns(mix(alloc, lev, trend_on(band=0.02)))
        rows[f"{name} x{lev} SPY>200d monthly->cash"] = lev_returns(mix(alloc, lev, trend_on(daily=False)))
        rows[f"{name} x{lev} SPY>200d 2%band->IEF"] = lev_returns(mix(alloc, lev, trend_on(band=0.02), off="IEF"))
t = pd.DataFrame({k: R.stats(v) for k, v in rows.items()}).T
t["worst_year"] = [((1 + v).groupby(v.index.year).prod() - 1).min() for v in rows.values()]
with pd.option_context("display.float_format", "{:,.3f}".format, "display.width", 200):
    print(t.to_string())
