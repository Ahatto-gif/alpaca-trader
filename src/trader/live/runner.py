"""Daily live/paper trading loop.

Each trading day, shortly after the open:
  1. compute signals on the last *completed* daily bar (yesterday's close)
  2. size target positions with the same portfolio code the backtest uses
  3. run risk checks, then submit market orders

This mirrors the backtest, where a signal at close t fills at the open of t+1.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from ..config import load_credentials
from ..data import load_bars
from ..portfolio import plan_orders, target_weights
from ..strategies import build_strategy
from .broker import AlpacaBroker
from .risk import RiskLimits, apply_risk

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")


class LiveRunner:
    def __init__(self, settings: dict, *, dry_run: bool = False, allow_live_money: bool = False):
        creds = load_credentials()
        if not creds.paper and not allow_live_money:
            raise SystemExit("ALPACA_PAPER=false but --live-money was not passed. Refusing to "
                             "trade real money.")
        self.settings = settings
        self.dry_run = dry_run
        self.broker = AlpacaBroker(creds)
        self.strategy = build_strategy(settings["strategy"]["name"], settings["strategy"].get("params"))
        self.limits = RiskLimits.from_settings(settings["risk"])
        self.portfolio = settings.get("portfolio", {})
        self.log_dir = Path(settings["live"]["log_dir"])
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.log_dir / "state.json"
        self.kill_switch = Path(settings["risk"]["kill_switch_file"])
        log.info("Mode: %s%s | strategy %s", "PAPER" if creds.paper else "LIVE MONEY",
                 " (dry run)" if dry_run else "", self.strategy)

    # -- state ---------------------------------------------------------------
    def _last_run(self) -> str | None:
        try:
            return json.loads(self.state_file.read_text()).get("last_run")
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _mark_run(self, day: date) -> None:
        self.state_file.write_text(json.dumps({"last_run": day.isoformat()}))

    def _journal(self, record: dict) -> None:
        with open(self.log_dir / "journal.jsonl", "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    # -- one rebalance -------------------------------------------------------
    def check_kill_switch(self) -> bool:
        if self.kill_switch.exists():
            log.critical("Kill switch file found at %s", self.kill_switch)
            if not self.dry_run:
                self.broker.flatten()
            self._journal({"time": datetime.now(ET), "event": "kill_switch"})
            return True
        return False

    def run_once(self, force: bool = False) -> None:
        if self.check_kill_switch():
            raise SystemExit("Kill switch active: positions flattened. Delete the file to resume.")

        clock = self.broker.clock()
        if not clock.is_open and not (force or self.dry_run):
            log.info("Market is closed (next open %s). Use --force to queue orders anyway.",
                     clock.next_open)
            return

        account = self.broker.account()
        if account.trading_blocked or account.account_blocked:
            raise SystemExit("Account is blocked from trading. Check the Alpaca dashboard.")
        equity, last_equity = float(account.equity), float(account.last_equity)
        cash = float(account.cash)

        symbols = self.settings["symbols"]
        today = datetime.now(ET).date()
        start = (today - timedelta(days=self.settings["live"]["lookback_days"])).isoformat()
        data_cfg = self.settings["data"]
        bars = load_bars(symbols, start, feed=data_cfg["feed"], adjustment=data_cfg["adjustment"],
                         cache_dir=data_cfg["cache_dir"])
        # Completed bars only. Today's partial bar must never feed the signal.
        bars = {s: df[df.index.date < today] for s, df in bars.items()}

        signals, last_close = {}, {}
        for sym in symbols:
            df = bars.get(sym)
            if df is None or len(df) <= self.strategy.warmup:
                log.warning("%s: not enough history (%s bars), holding flat", sym,
                            0 if df is None else len(df))
                signals[sym] = 0.0
                continue
            if (today - df.index[-1].date()).days > 5:
                log.warning("%s: last bar %s looks stale", sym, df.index[-1].date())
            signals[sym] = float(self.strategy.signals(df).iloc[-1])
            last_close[sym] = float(df["close"].iloc[-1])

        weights = target_weights(signals, max_position_pct=self.limits.max_position_pct,
                                 max_gross_exposure=self.limits.max_gross_exposure,
                                 cash_buffer=self.portfolio.get("cash_buffer", 0.02))
        prices = {**last_close, **self.broker.latest_prices(symbols)}
        positions = self.broker.positions()
        stray = set(positions) - set(symbols)
        if stray:
            log.warning("Ignoring positions not in the universe: %s", ", ".join(sorted(stray)))

        orders = plan_orders(equity=equity, weights=weights, prices=prices,
                             current_shares=positions,
                             rebalance_band=self.portfolio.get("rebalance_band", 0.25),
                             min_order_value=self.limits.min_order_value,
                             cash=cash, cash_reserve=equity * self.portfolio.get("cash_buffer", 0.02))
        approved, notes = apply_risk(orders, prices=prices, equity=equity, last_equity=last_equity,
                                     current_shares=positions,
                                     open_order_symbols=self.broker.open_order_symbols(),
                                     limits=self.limits)
        for n in notes:
            log.warning(n)

        log.info("Equity %.2f | signals %s", equity, {s: round(v, 2) for s, v in signals.items()})
        if not approved:
            log.info("No trades needed.")
        submitted = []
        for sym, delta in approved.items():
            side = "BUY" if delta > 0 else "SELL"
            log.info("%s %s %d @ ~%.2f%s", side, sym, abs(delta), prices[sym],
                     " [dry run]" if self.dry_run else "")
            if not self.dry_run:
                try:
                    order = self.broker.submit_market(sym, delta)
                    submitted.append({"symbol": sym, "qty": delta, "id": str(order.id)})
                except Exception as exc:
                    log.error("Order for %s failed: %s", sym, exc)

        self._journal({"time": datetime.now(ET), "equity": equity, "signals": signals,
                       "weights": weights, "orders": approved, "submitted": submitted,
                       "notes": notes, "dry_run": self.dry_run})
        if not self.dry_run:
            self._mark_run(today)

    # -- scheduler -----------------------------------------------------------
    def loop(self) -> None:
        """Run once per trading day, `run_minutes_after_open` after the open."""
        delay = timedelta(minutes=self.settings["live"]["run_minutes_after_open"])
        log.info("Starting daily loop (Ctrl+C to stop)")
        while True:
            if self.check_kill_switch():
                raise SystemExit("Kill switch active.")
            clock = self.broker.clock()
            now = pd.Timestamp(clock.timestamp)
            today = now.tz_convert(ET).date().isoformat()
            if clock.is_open and self._last_run() != today:
                try:
                    self.run_once()
                except SystemExit:
                    raise
                except Exception:
                    log.exception("Rebalance failed; will retry in 5 minutes")
                    time.sleep(300)
                    continue
            # Sleep until next open + delay, waking at least every 15 min to check the kill switch.
            target = pd.Timestamp(clock.next_open) + delay
            wait = max(60.0, min((target - now).total_seconds(), 900.0))
            time.sleep(wait)
