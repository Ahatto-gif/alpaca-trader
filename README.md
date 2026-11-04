# trading-logs

Daily output of `trader live`, kept so it survives between cloud runs.

- `logs/journal.jsonl` – one line per run: equity, signals, target weights, orders, notes.
- `logs/state.json` – date of the last real (non-dry-run) rebalance.

Restore before a run: `git fetch origin trading-logs && git show origin/trading-logs:logs/journal.jsonl > logs/journal.jsonl` (same for `state.json`).
