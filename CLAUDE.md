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
  4. Consider promotion (below). Log any change in DECISIONS.md.
  5. Optionally register 1-2 new challengers with a written hypothesis. Keep the list short (<= 10).
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
.venv/bin/trader review --start 2026-11-03 --out memory/reviews/$(date +%F).md
.venv/bin/pytest -q
```
`research/` holds the scripts behind the decisions (run from the repo root with `.venv/bin/python`).
Historical data from Alpaca starts in 2016.
