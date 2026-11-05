"""SMA 10/200 portfolio variants, same execution model as backtest/vectorized.py
(signal at close t -> held from open t+1, 5 bps per side on turnover, 2% cash buffer)."""
import numpy as np
import pandas as pd
from trader.config import load_settings
from trader.data import load_bars
from trader.strategies import build_strategy
from trader.backtest.metrics import performance

U = {
    "original 8": "AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,XOM",
    "9 sectors": "XLB,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY",
    "30 of 2016": "AAPL,GOOGL,MSFT,XOM,BRK.B,AMZN,META,JNJ,GE,WFC,JPM,T,PG,WMT,VZ,PFE,CVX,KO,ORCL,DIS,MRK,PEP,INTC,CSCO,HD,IBM,V,BAC,C,GILD",
}
s = load_settings(); d = s["data"]
CAP, BUF, SLIP = 0.20, 0.02, 5
strat = build_strategy("sma_crossover", {"fast": 10, "slow": 200})
load = lambda syms: load_bars(syms, "2016-01-01", feed=d["feed"], adjustment=d["adjustment"], cache_dir=d["cache_dir"])
spy = load(["SPY"])["SPY"]
spy_on = (spy["close"] > spy["close"].rolling(200).mean()).astype(float)

def run(weights, opens):
    o2o = (opens.shift(-1) / opens - 1).fillna(0.0)
    held = weights.shift(1).fillna(0.0)
    turn = held.diff().abs().fillna(held.abs()).sum(axis=1)
    r = (held * o2o).sum(axis=1) - turn * SLIP / 1e4
    r = r[r.index >= "2017-01-01"]
    p = performance((1 + r).cumprod())
    return p["cagr"], p["sharpe"], p["max_drawdown"], held[held.index >= "2017-01-01"].sum(axis=1).mean(), turn[turn.index >= "2017-01-01"].sum() / 9.8

def trailing(sig, close, stop):
    out = sig.copy() * 0.0
    for c in sig.columns:
        sv, cv = sig[c].to_numpy(), close[c].to_numpy()
        holding, peak, armed = False, 0.0, True
        res = np.zeros(len(sv))
        for i in range(len(sv)):
            if sv[i] == 0:
                holding, armed = False, True
            elif not holding and armed:
                holding, peak = True, cv[i]
            if holding:
                peak = max(peak, cv[i])
                if cv[i] < peak * (1 - stop):
                    holding, armed = False, False   # stopped: wait for a fresh signal
            res[i] = 1.0 if holding else 0.0
        out[c] = res
    return out

rows = []
for name, syms in U.items():
    bars = load(syms.split(","))
    sig = pd.DataFrame({k: strat.signals(v) for k, v in bars.items()}).dropna()
    opens = pd.DataFrame({k: v["open"] for k, v in bars.items()}).loc[sig.index]
    close = pd.DataFrame({k: v["close"] for k, v in bars.items()}).loc[sig.index]
    n = sig.shape[1]
    fixed = lambda g: g * min(1 / n, CAP) * (1 - BUF)
    def spread(g):
        k = g.sum(axis=1).replace(0, np.nan)
        return g.mul((1 / k).clip(upper=CAP), axis=0).fillna(0.0) * (1 - BUF)
    filt = sig.mul(spy_on.reindex(sig.index).fillna(0), axis=0)
    hold = pd.DataFrame(1.0, index=sig.index, columns=sig.columns) / n * (1 - BUF)
    variants = {
        "hold same stocks": hold,
        "A fixed 1/N slots (current)": fixed(sig),
        "B spread over active (<=20%)": spread(sig),
        "C fixed + SPY>200d filter": fixed(filt),
        "D fixed + 15% trailing stop": fixed(trailing(sig, close, 0.15)),
        "E spread + SPY filter": spread(filt),
    }
    for v, w in variants.items():
        rows.append((name, v, *run(w, opens)))
df = pd.DataFrame(rows, columns=["universe", "variant", "cagr", "sharpe", "max_dd", "avg_invested", "turnover/yr"])
with pd.option_context("display.float_format", "{:,.3f}".format, "display.width", 200):
    print(df.to_string(index=False))
