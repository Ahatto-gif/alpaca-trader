# alpaca-trader

Automated US stock trading on [Alpaca](https://alpaca.markets). Backtests run on
[backtrader](https://www.backtrader.com/), and a fast vectorized engine handles parameter sweeps.
The backtester and live trading share **one** strategy and position-sizing codebase, so live trading
behaves the same way the backtest did.

```
config/settings.yaml        all knobs: universe, strategy, costs, risk limits
src/trader/
  strategies/               signal logic (add yours here + register in __init__.py)
  portfolio.py              position sizing + order planning (shared by backtest & live)
  data/loader.py            Alpaca historical bars, cached as parquet; CSV loader
  backtest/engine.py        backtrader event-driven backtest (fills at next open + slippage)
  backtest/vectorized.py    fast grid search with in-sample / out-of-sample split
  backtest/walkforward.py   rolling re-optimisation; stitched out-of-sample results
  backtest/report.py        console summary, equity/trades CSV, chart.png
  live/runner.py            daily paper/live rebalancing loop
  live/risk.py              pre-trade risk checks
  live/broker.py            alpaca-py wrapper
tests/                      no-look-ahead, sizing, risk and engine-agreement tests
```

## Memory and learning

`CLAUDE.md` and `memory/` hold what's live and why (`DECISIONS.md`), what has been learned
(`LESSONS.md`), and strategies tracked forward out of sample (`challengers.yaml`). `trader review`
measures them. `research/` holds the scripts behind each decision.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # then paste your PAPER API keys from app.alpaca.markets
pytest                        # should be all green
```

## Workflow

```bash
trader fetch                  # download + cache daily bars for the universe and SPY
trader backtest               # full backtest with the strategy in settings.yaml
trader sweep                  # grid search; look at the oos_* columns
trader walkforward            # re-optimise every year on the past 3, trade the next 1
trader backtest --strategy sma_crossover --param fast=30 --param slow=150
trader backtest --strategy rsi_mean_reversion --symbols SPY,QQQ,IWM --start 2010-01-01
```

### Walk-forward: the number to trust

`trader walkforward` splits history into rolling windows (default: train 3 years, test 1 year).
For each window it picks the best grid parameters on the train years, then trades the test year
with them. The printed table shows which parameters won each window and how they did out of
sample. The test years are then stitched together and replayed through backtrader for a full report.
If the chosen parameters jump around every window, or the walk-forward results are far worse than
the plain backtest, the strategy is probably curve-fit. Options: `--train-years`, `--test-years`,
`--anchored` (expanding window), `--metric`.

Each backtest writes `results/<timestamp>_<strategy>/` with `chart.png`, `equity.csv`,
`trades.csv`, `signals.csv` and `summary.json`.

No API keys yet? Put `<SYMBOL>.csv` files (date, open, high, low, close, volume) in a folder and
add `--csv-dir that/folder` to `backtest`, `sweep` or `fetch`.

### Paper trading

```bash
trader account                # check connection, equity, positions
trader report                 # account return vs SPY since the first funded day
trader review --out memory/reviews/$(date +%F).md   # account, fills, trade ledger, challengers
trader trades                 # every closed trade: P&L split into market vs selection, execution cost
trader live --dry-run         # show the orders it *would* place, sends nothing
trader live                   # one rebalance now (market must be open; --force to queue)
trader live --loop            # long-running: rebalances once per day, 5 min after the open
```

Or schedule the one-shot version with cron (times in US/Eastern, weekdays):
`35 9 * * 1-5  cd /path/to/alpaca-trader && .venv/bin/trader live >> logs/cron.log 2>&1`

Every run is appended to `logs/journal.jsonl`.

### Safety rails

- **Paper by default.** Real money needs `ALPACA_PAPER=false` in `.env` *and* `--live-money` on the CLI.
- **Kill switch.** `touch KILL_SWITCH`. The next run or loop tick cancels all orders, closes all positions and stops.
- **Daily loss limit.** If equity is down `daily_loss_limit_pct` vs. yesterday, buys are blocked and sells still go through.
- **Position / gross caps.** No symbol above `max_position_pct`, no leverage beyond `max_gross_exposure`, and buys never exceed available cash.
- **Max orders per run.** It also skips symbols that already have an open order and ignores positions outside the universe.

## How the backtest avoids lying to you

| Pitfall | What this project does |
|---|---|
| Look-ahead bias | Signal from bar *t*'s close executes at bar *t+1*'s open. `tests/test_strategies.py` checks signals don't change when future data is added. |
| Free trading | `slippage_bps` per side on every fill (default 5 bps). Add per-share fees via `commission_per_share`. |
| Splits/dividends | `adjustment: all` gives total-return prices. |
| Thin data | `feed: sip` uses the full consolidated tape. Switch to `iex` if your plan rejects SIP. |
| Overfitting | `sweep` ranks on in-sample data and shows out-of-sample results next to them. `walkforward` goes further: each year is traded with parameters picked only from the years before it, then replayed through backtrader. |
| Backtest ≠ live | Backtest and live share the same strategy, sizing (`portfolio.py`), rebalance band and cash rules. |
| Unrealistic fills | Whole shares only, cash constraints enforced, and orders rejected for cash are counted and reported. |

**Known limitations to address before real money:** survivorship bias (today's tickers looked great
in hindsight; use a point-in-time universe), daily bars only (no intraday logic), and market-on-open fills can be worse than the backtest's open price.

## Adding a strategy

```python
# src/trader/strategies/my_strategy.py
from .base import Strategy

class Breakout(Strategy):
    name = "breakout"
    default_params = {"lookback": 55}

    @property
    def warmup(self):
        return self.params["lookback"]

    def compute(self, df):
        high = df["high"].rolling(self.params["lookback"]).max()
        return (df["close"] >= high).astype(float)   # 0..1 target exposure, bar t data only
```

Register it in `strategies/__init__.py` (`REGISTRY`), then run `trader backtest --strategy breakout`.

*Educational software. Nothing here is financial advice; trading involves risk of loss.*
