# Lessons (append new ones at the top, with the date and the evidence)

## 2026-11-12: first trade-ledger read
- The 6 closed trades (old 8-stock positions, held 2026-11-04 to 11-05, closed by the switch to SPY/QQQ)
  lost -308.10: market +239.17, selection -547.27. NVDA alone was -733.78 of selection
  (-5.6% vs SPY +0.3%). That's 6 trades over one day, so noise: no lesson about NVDA or the old
  strategy beyond what the research already showed. Execution cost is unknown for these
  (entries predate decision-price logging, added 2026-11-05).

## 2026-11-12
- **YAML 1.1 reads `on`/`off`/`yes`/`no` as booleans.** `{on: 1.3}` became `{True: 1.3}` and
  `trader review` crashed. Use other key names (we use `above`/`below`), and check ticker lists
  for symbols like ON, Y or NO too.
- The account has tracked SPY since 2026-11-11 (+0.24% vs +0.23% since 11-03). The 11-04 entry gap has closed.

## 2026-11-07: first weekly review
- **Execution beats the model.** The 8 paper fills on 2026-11-05 averaged +1.9 bps (median +1.8,
  worst +8.3 on NVDA) against the decision price, while backtests assume 5 bps. Keep 5 bps:
  real-money fills will be worse than paper ones, and 8 fills is too few to cut the assumption.
- **`summarize()` bug, fixed.** Forward records shorter than 2 days showed +0.00% return.
  Now total return and drawdown are always shown; CAGR and Sharpe only after 20 days.
- **The forward record lags a day.** Returns are open-to-open, so a day counts only after
  the next open: Friday's move appears after Monday's open. On 2026-11-07 that left 1 day (11-05: core -3.7%).
- **Infrastructure:**
  - A setup script that does `cd <repo>` breaks scheduled sessions that don't have the repo
    attached: the session never starts (2026-11-05).
  - Scheduled sessions started fresh can clone a public repo but can't push (403), and they
    have no add_repo tool (2026-11-06).
  - Fix: the scheduled tasks now run inside the owner's long-lived session, which has push access.
- **The account tracks the champion.** Equity went from about 99.8k at the switch (11-05 09:38 ET) to 96.7k
  at the 11-06 close (-3.1%), in line with SPY/QQQ over the same window. The -0.9% gap vs SPY since
  11-03 comes from the old 8-stock portfolio on 11-04, not from execution.

## 2026-11-05: strategy research (2017-2026, scripts in research/)
- **Stock lists chosen today flatter backtests.** SMA 10/200 made 23% a year on 8 of today's
  mega caps. On lists fixed in 2016 it made 8.9% (30 largest) and 6.6% (~100 largest, including
  later-delisted names), against 14.7% for SPY. More stocks gave less edge. Always test on a list
  that could have been known at the start of the test.
- **Trend filters (price vs 200-day average) cut drawdowns roughly in half but cost about
  half the return in 2016-26.** They got whipsawed in the 2018, 2020 and 2023 recoveries.
  Checking them monthly instead of daily was worse. They only beat SPY in down years (2018, 2022).
- **Cross-sectional momentum** (12-1 month, top 10 of the 2016 S&P 100): 15.2% a year, Sharpe
  0.79, max DD -29%. Shorter lookbacks (6 and 3 months) were worse. Adding a SPY 200-day filter
  cut it to about 7%.
- **Dual momentum (SPY/EFA/AGG):** 8.2%, Sharpe 0.59. Poor in this decade.
- **Spreading cash across only the stocks with a signal** brings returns closer to buy-and-hold;
  it doesn't add edge. A **15% trailing stop** cut drawdowns but cost 1.5-8 points a year.
- **Leverage** raises return about linearly, but drawdowns grow faster: 50/50 SPY/QQQ at 1.5x
  made 22.6% with max DD -44%; at 2x, 26.8% with -56% (margin at T-bill + 2.5% included).

## 2026-11-05: data and engine pitfalls
- Alpaca SIP daily history starts 2016-01-04, so a 12-month lookback means tests start in 2017.
- Alpaca keeps data for delisted names (CELG, RTN, TWX, ESRX, WBA...), so use it to avoid
  survivorship bias. **Some tickers were reused** by other companies: EMC after 2016-09-06,
  MON after 2018-06-06, BK ended 2026-05-20. Check any list for this.
- **Spin-offs aren't adjusted:** RTX shows a fake -71% on 2020-04-03 (UTX spun off Carrier and
  Otis). Momentum and other ranking strategies seek out bad prints like this, so screen for
  daily moves above 30%.
- `backtest/engine.py` `align()` trims all symbols to their common dates. With a delisted
  name in the list, everything gets cut to its short history. Use the vectorized research
  engine (`src/trader/challengers.py` or `research/research.py`) for such lists.
- A forward-fill of monthly weights that doesn't zero dropped names silently leaks leverage
  (that's how we got the -100% drawdowns at first). `target_weight_frame` writes full rows.

## 2026-11-04: execution
- The rebalance runs at 9:35 ET, so it misses the overnight gap. On 2026-11-04 SPY opened +1.2%
  (AAPL +6.7%) before our buys. With buy-and-hold this matters little; for signal strategies,
  compare against open-to-open returns, not close-to-close.
- Paper market orders filled within about 25 seconds of the open.
