"""SMA crossover on the ~S&P 100 of Jan 2016, including later-delisted names (no survivorship).
Execution as in backtest/vectorized.py: signal at close t -> held from open t+1, 5 bps/side.
Slots = 1/(names still listed); a delisted name's slot goes to cash at its last bar."""
import numpy as np, pandas as pd, sys
from trader.config import load_settings
from trader.data import load_bars
from trader.strategies import build_strategy
from trader.backtest.metrics import performance

SP = str(__import__("pathlib").Path(__file__).resolve().parent)
syms = [x for x in open(f"{SP}/sp100_2016.txt").read().split() if x != "DOW"]
TRUNC = {"EMC": "2016-09-06", "MON": "2018-06-06"}   # tickers later reused by other companies
s = load_settings(); d = s["data"]; BUF, SLIP, CAP = 0.02, 5, 0.20
load = lambda x: load_bars(x, "2016-01-01", feed=d["feed"], adjustment=d["adjustment"], cache_dir=d["cache_dir"])
bars = load(syms); spy = load(["SPY"])["SPY"]
for k, t in TRUNC.items(): bars[k] = bars[k].loc[:t]
idx = spy.index
opens = pd.DataFrame({k: v["open"] for k, v in bars.items()}).reindex(idx)
alive = opens.notna()
o2o = (opens.shift(-1) / opens - 1)
o2o = o2o.where(o2o.notna(), 0.0)  # last bar of a delisted name: exits flat at its final open

def run(w, start="2017-01-01"):
    held = w.shift(1).fillna(0.0)
    turn = held.diff().abs().fillna(held.abs()).sum(axis=1)
    r = (held * o2o).sum(axis=1) - turn * SLIP / 1e4
    return r[r.index >= start]

def weights(sig, spread=False):
    sig = sig.reindex(idx).fillna(0.0) * alive
    if spread:
        k = sig.sum(axis=1).replace(0, np.nan)
        return sig.mul((1 / k).clip(upper=CAP), axis=0).fillna(0.0) * (1 - BUF)
    return sig.div(alive.sum(axis=1), axis=0) * (1 - BUF)

def sigs(fast, slow):
    st = build_strategy("sma_crossover", {"fast": fast, "slow": slow})
    return pd.DataFrame({k: st.signals(v) for k, v in bars.items()})

def stats(r):
    p = performance((1 + r).cumprod()); return p["cagr"], p["sharpe"], p["max_drawdown"]

print(f"{len(bars)} stocks; delisted during test: " + ", ".join(f"{k} ({v.index[-1].date()})" for k, v in bars.items() if v.index[-1] < idx[-5]))
spy_r = (spy["open"].shift(-1) / spy["open"] - 1).fillna(0); spy_r = spy_r[spy_r.index >= "2017-01-01"]
s1020 = sigs(10, 200)
hold = weights(pd.DataFrame(1.0, index=idx, columns=list(bars)))
rows = [("SPY", *stats(spy_r), 1.0),
        ("Hold all ~100 equally", *stats(run(hold)), 0.98),
        ("SMA 10/200, fixed slots", *stats(run(weights(s1020))), weights(s1020).sum(axis=1)[idx >= "2017-01-01"].mean()),
        ("SMA 10/200, spread over active", *stats(run(weights(s1020, True))), weights(s1020, True).sum(axis=1)[idx >= "2017-01-01"].mean())]
t = pd.DataFrame(rows, columns=["portfolio", "cagr", "sharpe", "max_dd", "avg_invested"])
with pd.option_context("display.float_format", "{:,.3f}".format, "display.width", 200): print(t.to_string(index=False))

print("\nParameter grid (fixed slots), Sharpe / CAGR, 2017-2026:")
g = {}
for f in (10, 20, 50):
    for sl in (100, 150, 200):
        c, sh, dd = stats(run(weights(sigs(f, sl)))); g[(f, sl)] = f"{sh:.2f} / {c:.1%}"
print(pd.Series(g).unstack().rename_axis(index="fast", columns="slow").to_string())

print("\nYear by year (fixed slots 10/200 vs SPY vs hold-all):")
r = run(weights(s1020)); h = run(hold)
y = pd.DataFrame({"SMA_10_200": (1 + r).groupby(r.index.year).prod() - 1,
                  "SPY": (1 + spy_r).groupby(spy_r.index.year).prod() - 1,
                  "hold_all": (1 + h).groupby(h.index.year).prod() - 1})
y["SMA_minus_SPY"] = y.SMA_10_200 - y.SPY
print(y.map("{:+.1%}".format).T.to_string())
