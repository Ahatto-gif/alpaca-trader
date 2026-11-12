# alpaca-trader: instructions for Claude sessions

Automated trading on the owner's Alpaca **paper** account. The owner has asked Claude to run
this project to make as much profit as it can, to learn from past results, and to ask
when it needs something from them.

## Read first
1. `memory/DECISIONS.md`: what is live, and why (newest first).
2. `memory/LESSONS.md`: things already learned. Don't repeat tests that are recorded there.
3. `memory/challengers.yaml`: strategies tracked forward, and which one is the champion (live).
4. The latest file in `memory/reviews/`, if there is one.

## Hard rules
- Paper only. `ALPACA_PAPER` must be `true`; if it isn't, stop and tell the owner. Never pass
  `--live-money`. Never pass `--force` to `trader live`.
- Daily runs push only to the `trading-logs` branch (`logs/journal.jsonl`, `logs/state.json`).
  Code, config and memory changes go to `main`, in review sessions only, with tests passing.
- Anything that adds leverage (`max_gross_exposure` > 1), shorting, options, or real money
  needs the owner's explicit OK. Ask them, don't do it.
- Don't put credentials or account numbers in the repo.

## How the project learns
- **Evidence comes from forward data, not more backtests on the same 2016-2026 history.**
  That history has been looked at a lot (see LESSONS), so a new idea that wins on it is
  probably overfit. Instead, register the idea in `memory/challengers.yaml` with today's date
  as `since`. `trader review` then tracks it forward, out of sample.
- **Weekly review** (`trader review --start 2026-11-03 --out memory/reviews/YYYY-MM-DD.md`):
  1. Read the review. Write anything new and surprising into LESSONS.md, with evidence and date.
  2. Check execution: if mean live slippage is clearly above `backtest.slippage_bps`, raise
     `slippage_bps` to match (honest backtests), and note it in LESSONS.
  3. Check that the account roughly tracks the champion's forward record. A big gap means an
     execution or code problem: investigate it.
  4. Read the **trade ledger** section (the review also writes `memory/trades.csv`;
     commit it). Apply "Learning from trades" below.
  5. Consider promotion (below). Log any change in DECISIONS.md.
  6. Optionally register 1-2 new challengers with a written hypothesis. Keep the list short (<= 10).
- **Learning from trades.** Every closed trade's P&L is split into `market_pnl` (what the
  benchmark did on the same money over the same days), `selection_pnl` (the rest), and
  `execution_cost` (fills vs decision prices). Draw lessons from patterns, never from single trades:
  - **Execution:** if mean execution cost is above the backtest assumption over 20+ fills, raise
    `slippage_bps`. If it's concentrated in one symbol or time, look for the cause.
  - **Selection:** a strategy's summed `selection_pnl` over 20+ closed trades (or 3+ months) is
    evidence about its edge. Record it in LESSONS. It only changes the champion through the promotion rule.
  - **Close reasons:** repeated losses from one reason (e.g. many small `rebalance trim` losses)
    can mean a band or rule is too tight. Test the change as a challenger before switching.
  - **Never** blacklist a symbol or change a rule because of one losing trade. It's noise, and
    reacting to it is overfitting.
- **Promotion rule** (challenger replaces champion). All of these must hold:
  - at least 126 trading days (about 6 months) of forward record;
  - forward CAGR at least 3 points above the champion's, and forward max drawdown no more than
    5 points worse;
  - the 2017+ backtest isn't clearly worse (Sharpe within 0.1 of the champion's);
  - no leverage, or the owner approved it.
  Then change `config/settings.yaml`, update `champion:`, run the tests and a dry run, push to
  `main`, and log it in DECISIONS.md. The old champion stays registered.
- Demote or stop a challenger only by adding a note; never delete history or edit `since`.

## Commands
```bash
.venv/bin/trader account            # equity, cash, positions, market clock
.venv/bin/trader live --dry-run     # what the next rebalance would do
.venv/bin/trader report --start 2026-11-03
.venv/bin/trader trades              # closed-trade ledger: P&L = market + selection, execution cost
.venv/bin/trader review --start 2026-11-03 --out memory/reviews/$(date +%F).md
.venv/bin/pytest -q
```
**Dashboard**: https://claude.ai/artifact/Sa4exuAZTSW6j2YEzgr5ok (a claude.ai "Data" dashboard).
Its six datasets (`account`, `equity`, `positions`, `challengers`, `trades`, `fills`) are attached CSV
files written by `.venv/bin/trader dashboard-export --out logs/dashboard`. To refresh them:
1. Upload each CSV as an asset of that artifact.
2. Update each `datasets/<id>`: set `source.url` to the new `/_blob/<id>` and stamp `updated.at` and `edit`.
3. Delete the old asset.
Never put account numbers in them.

`research/` holds the scripts behind the decisions (run from the repo root with `.venv/bin/python`).
Historical data from Alpaca starts in 2016.
