# Decisions (newest first)

## 2026-11-12: switch the core to cheaper funds (VOO + QQQM); track international (owner approved)
- `symbols: [VOO, QQQM]` replace SPY/QQQ: same indexes, lower fees (VOO 0.03% vs 0.0945%; QQQM 0.15% vs
  0.20%), about 0.06%/yr saved. Since 2021 VOO beat SPY by 0.9 pts and QQQM beat QQQ by 0.5 pts in total;
  daily correlation is above 0.999. The next run sells SPY/QQQ and buys VOO/QQQM (liquidate_outside_universe).
  New champion entry `core_voo_qqqm`; `core_spy_qqq` stays registered.
- International: backtest 2017-26 showed every international slice lowered both CAGR and Sharpe
  (20% VXUS: 15.9% vs 17.5%), with little drawdown benefit (correlation 0.85 with SPY). So it isn't live.
  It's tracked forward as `global_40_40_20` and `vt_world` in case the US lags (as in 2000-09, or in 2025: VXUS +33% vs live +19%).
- Note: `trader backtest` on the live config now starts in Oct 2020 (QQQM's launch); use the
  challenger backtests in `trader review` for 2017+ context.

## 2026-11-12: smaller cash buffer + cash sweep; 3 new challengers (owner approved)
- `portfolio.cash_buffer` 0.02 -> 0.005 and new `portfolio.cash_sweep_pct: 0.01`. When spare cash
  is above 1% of equity, under-target positions are topped up even inside the 10% rebalance band.
  Without the sweep, a lower buffer does nothing: positions sat about 1.5% under target, inside the band.
  Full backtest 2016-26: CAGR 16.89% -> 17.14%, max DD -30.0% -> -30.7%. Same risk, idle cash invested.
- New challengers tracked from 2026-11-12: `tilt_qqq80_spy20`, `core_trend_lev_1.3`
  (leverage needs the owner's OK to promote), and `sector_momentum_top3`. Each has a hypothesis in
  challengers.yaml.

## 2026-11-05: owner declined leverage for now
The owner was offered 1.5x (backtest 22.6%/yr, max DD -44%, about -70% in a 2008-style crash)
and said to wait: the risk is too high. Keep `max_gross_exposure: 1.0`. Keep tracking
`core_spy_qqq_x1.5` as a challenger, but don't ask again in every review. Raise it only if its
forward record meets the promotion rule, or if the owner asks.

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
