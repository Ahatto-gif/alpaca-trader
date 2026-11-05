# Decisions (newest first)

## 2026-11-05: switch live to 50% SPY / 50% QQQ (buy_and_hold), no leverage
**Why.** The owner asked for the most profit. Every stock-picking or timing strategy we tested
on universes chosen without hindsight did no better than holding the index (see LESSONS
2026-11-05). Holding the market is the most reliable source of return we found. Among
index holdings, 50/50 SPY/QQQ (backtest 2017-26: CAGR 17.3%, Sharpe 0.94, max DD -31%)
nearly matches QQQ alone on risk-adjusted return (19.9%, 0.95, -36%), with less tech concentration.
**Rejected:**
- Leverage 1.5x (22.6%, max DD -44%): this needs the owner's OK, so it's tracked as `core_spy_qqq_x1.5`.
- Trend filters: they cost return this decade.
- Momentum top-10: 15.2%, Sharpe 0.79, so no better than SPY.
- SMA 10/200 on the 8 big tech names: the backtest was flattered by hindsight.
**How.** `config/settings.yaml`: symbols [SPY, QQQ], strategy buy_and_hold, max_position_pct
0.5, rebalance_band 0.10, `liquidate_outside_universe: true` (sells the old stock positions).
All candidates are registered in `memory/challengers.yaml` (since 2026-11-04) for forward tracking.

## 2026-11-04: sma_crossover fast=10 slow=200 on 8 large caps (superseded 2026-11-05)
The anchored walk-forward picked 10/200 in all 8 windows (Sharpe 1.35, 2019-26). It went live
with a first paper rebalance of 6 buys on 2026-11-04. Later tests showed that most of the edge
came from choosing the stocks with hindsight.
