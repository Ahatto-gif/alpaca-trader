"""Compare SMA 10/200 vs equal-weight buy-and-hold vs SPY on several universes (vectorized engine)."""
import sys
import pandas as pd
from trader.config import load_settings
from trader.data import load_bars
from trader.strategies import build_strategy
from trader.backtest.vectorized import vectorized_returns
from trader.backtest.metrics import performance

U = {
    "original 8 (hindsight)": "AAPL,MSFT,NVDA,AMZN,GOOGL,META,JPM,XOM",
    "9 sector ETFs": "XLB,XLE,XLF,XLI,XLK,XLP,XLU,XLV,XLY",
    "30 largest of Jan 2016": "AAPL,GOOGL,MSFT,XOM,BRK.B,AMZN,META,JNJ,GE,WFC,JPM,T,PG,WMT,VZ,PFE,CVX,KO,ORCL,DIS,MRK,PEP,INTC,CSCO,HD,IBM,V,BAC,C,GILD",
}
s = load_settings(); d = s["data"]; r = s["risk"]
kw = dict(slippage_bps=5, max_position_pct=r["max_position_pct"], max_gross_exposure=1.0, cash_buffer=0.02)

class Hold:
    warmup = 0
    def signals(self, df): return pd.Series(1.0, index=df.index)

spy = load_bars(["SPY"], "2016-01-01", feed=d["feed"], adjustment=d["adjustment"], cache_dir=d["cache_dir"])["SPY"]
rows = []
for name, syms in U.items():
    bars = load_bars(syms.split(","), "2016-01-01", feed=d["feed"], adjustment=d["adjustment"], cache_dir=d["cache_dir"])
    sma = vectorized_returns(bars, build_strategy("sma_crossover", {"fast": 10, "slow": 200}), **kw)
    # Equal-weight hold uses no slot cap so it is fully invested (1/N each).
    hold = vectorized_returns(bars, Hold(), **{**kw, "max_position_pct": 1.0})
    for label, rets in (("SMA 10/200", sma), ("Equal-weight hold", hold)):
        rets = rets[rets.index >= "2017-01-01"]  # after the 200-day warmup
        p = performance((1 + rets).cumprod())
        rows.append((name, label, p["cagr"], p["sharpe"], p["max_drawdown"]))
spy_r = spy["open"].shift(-1) / spy["open"] - 1
spy_r = spy_r[spy_r.index >= "2017-01-01"].fillna(0)
p = performance((1 + spy_r).cumprod())
rows.append(("SPY", "buy and hold", p["cagr"], p["sharpe"], p["max_drawdown"]))
df = pd.DataFrame(rows, columns=["universe", "strategy", "cagr", "sharpe", "max_dd"])
with pd.option_context("display.float_format", "{:,.3f}".format, "display.width", 200):
    print(df.to_string(index=False))
