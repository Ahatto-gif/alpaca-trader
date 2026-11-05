"""Strategy research harness. Same execution model as backtest/vectorized.py:
weights decided at close t are held from open t+1; 5 bps per side on turnover; 2% cash buffer.
Universe: ~S&P 100 of Jan 2016 incl. later-delisted names (EMC/MON truncated at takeover)."""
import itertools, sys
import numpy as np, pandas as pd
from trader.config import load_settings
from trader.data import load_bars
from trader.backtest.metrics import performance

SP = str(__import__("pathlib").Path(__file__).resolve().parent)
s = load_settings(); d = s["data"]; BUF, SLIP = 0.02, 5
def load(x): return load_bars(x, "2016-01-01", feed=d["feed"], adjustment=d["adjustment"], cache_dir=d["cache_dir"])
UNIV = [x for x in open(f"{SP}/sp100_2016.txt").read().split() if x != "DOW"]
TRUNC = {"EMC": "2016-09-06", "MON": "2018-06-06"}
ETFS = ["SPY", "QQQ", "EFA", "AGG", "BIL", "TLT", "IEF", "GLD", "IWM", "VTI"]
bars = load(UNIV + ETFS)
for k, t in TRUNC.items(): bars[k] = bars[k].loc[:t]
idx = bars["SPY"].index
O = pd.DataFrame({k: v["open"] for k, v in bars.items()}).reindex(idx)
C = pd.DataFrame({k: v["close"] for k, v in bars.items()}).reindex(idx)
O2O = (O.shift(-1) / O - 1)
O2O = O2O.where(O2O.notna(), 0.0)
O2O.loc["2020-04-02", "RTX"] = 0.0  # UTX spin-off artefact
C.loc[:"2020-04-02", "RTX"] *= C.loc["2020-04-03", "RTX"] / C.loc["2020-04-02", "RTX"]  # back-adjust
START = "2017-01-03"

def month_starts(index):
    """Signal dates: last trading day of each month (trade next open = first day of month)."""
    s = pd.Series(index, index=index)
    return set(s.groupby([index.year, index.month]).max())

REB = month_starts(idx)

def returns(w, start=START):
    w = w.reindex(columns=O.columns, fill_value=0.0).fillna(0.0)
    held = w.shift(1).fillna(0.0)
    turn = held.diff().abs().fillna(held.abs()).sum(axis=1)
    r = (held * O2O).sum(axis=1) - turn * SLIP / 1e4
    return r[r.index >= start]

def stats(r):
    p = performance((1 + r).cumprod())
    return dict(cagr=p["cagr"], sharpe=p["sharpe"], max_dd=p["max_drawdown"], calmar=p["calmar"])

def hold(sym):
    w = pd.DataFrame(0.0, index=idx, columns=O.columns); w[sym] = 1 - BUF; return w

def monthly(fn):
    """Build a weight frame by calling fn(t) -> {sym: weight} on each month-end, forward-filled."""
    w = pd.DataFrame(np.nan, index=idx, columns=O.columns)
    for t in idx:
        if t in REB:
            row = pd.Series(0.0, index=O.columns)
            for k, v in fn(t).items(): row[k] = v
            w.loc[t] = row
    w = w.ffill().fillna(0.0)
    assert (w.sum(axis=1) <= 1.0 + 1e-9).all()
    return w

def momentum_scores(t, lookback, skip, univ):
    i = idx.get_loc(t)
    if i < lookback: return pd.Series(dtype=float)
    now, past = C.iloc[i - skip][univ], C.iloc[i - lookback][univ]
    alive = C.iloc[i][univ].notna() & past.notna() & now.notna()
    return (now / past - 1)[alive]

def xs_mom(lookback=252, skip=21, top=10, univ=UNIV, filt=None, defensive=None):
    spy_ok = C["SPY"] > C["SPY"].rolling(200).mean()
    def fn(t):
        if filt == "spy200" and not spy_ok.loc[t]:
            return {defensive: 1 - BUF} if defensive else {}
        sc = momentum_scores(t, lookback, skip, univ).nlargest(top)
        return {k: (1 - BUF) / len(sc) for k in sc.index} if len(sc) else {}
    return monthly(fn)

def gem():
    """Dual momentum: SPY vs BIL on 12m; if risk-on hold the better of SPY/EFA, else AGG."""
    def fn(t):
        i = idx.get_loc(t)
        if i < 252: return {}
        r = C.iloc[i] / C.iloc[i - 252] - 1
        if r["SPY"] > r["BIL"]:
            return {("SPY" if r["SPY"] >= r["EFA"] else "EFA"): 1 - BUF}
        return {"AGG": 1 - BUF}
    return monthly(fn)

if __name__ == "__main__":
    res = {}
    for sym in ["SPY", "QQQ", "VTI"]: res[f"hold {sym}"] = returns(hold(sym))
    res["dual momentum (GEM)"] = returns(gem())
    for lb, sk in [(252, 21), (126, 21), (63, 0)]:
        for top in (5, 10, 20):
            res[f"mom {lb}/{sk} top{top}"] = returns(xs_mom(lb, sk, top))
    for top in (5, 10, 20):
        res[f"mom 252/21 top{top} +SPY200->cash"] = returns(xs_mom(252, 21, top, filt="spy200"))
        res[f"mom 252/21 top{top} +SPY200->IEF"] = returns(xs_mom(252, 21, top, filt="spy200", defensive="IEF"))
    t = pd.DataFrame({k: stats(v) for k, v in res.items()}).T
    with pd.option_context("display.float_format", "{:,.3f}".format, "display.width", 200):
        print(t.to_string())
