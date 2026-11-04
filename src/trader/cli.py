"""Command line entry point:  trader <command> [options]   (run `trader -h`)."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from .config import load_settings


def _parse_params(items: list[str] | None) -> dict:
    """--param fast=10 --param slow=50  ->  {"fast": 10, "slow": 50}"""
    out = {}
    for item in items or []:
        key, _, raw = item.partition("=")
        for cast in (int, float):
            try:
                out[key] = cast(raw)
                break
            except ValueError:
                continue
        else:
            out[key] = raw
    return out


def _strategy_cfg(settings: dict, args) -> tuple[str, dict]:
    name = args.strategy or settings["strategy"]["name"]
    params = dict(settings["strategy"].get("params") or {}) if name == settings["strategy"]["name"] else {}
    params.update(_parse_params(args.param))
    return name, params


def _load_universe(settings: dict, args, with_benchmark: bool = True):
    from .data import load_bars, load_csv

    symbols = args.symbols.split(",") if getattr(args, "symbols", None) else settings["symbols"]
    bt_cfg = settings["backtest"]
    start = getattr(args, "start", None) or bt_cfg["start"]
    end = getattr(args, "end", None) or bt_cfg.get("end")
    bench_sym = bt_cfg.get("benchmark") if with_benchmark else None

    if getattr(args, "csv_dir", None):
        bars = {}
        for sym in symbols + ([bench_sym] if bench_sym else []):
            path = Path(args.csv_dir) / f"{sym}.csv"
            if path.exists():
                bars[sym] = load_csv(path).loc[start:end]
            else:
                logging.warning("No CSV for %s at %s", sym, path)
    else:
        d = settings["data"]
        bars = load_bars(symbols + ([bench_sym] if bench_sym else []), start, end,
                         feed=d["feed"], adjustment=d["adjustment"], cache_dir=d["cache_dir"],
                         refresh=getattr(args, "refresh", False))
    bench = bars.pop(bench_sym, None) if bench_sym and bench_sym not in symbols else bars.get(bench_sym)
    bars = {s: bars[s] for s in symbols if s in bars}
    if not bars:
        raise SystemExit("No price data loaded.")
    return bars, bench


def _engine_kwargs(settings: dict) -> dict:
    bt_cfg, risk, port = settings["backtest"], settings["risk"], settings.get("portfolio", {})
    return dict(cash=bt_cfg["cash"], slippage_bps=bt_cfg["slippage_bps"],
                commission_per_share=bt_cfg.get("commission_per_share", 0.0),
                cash_buffer=port.get("cash_buffer", 0.02),
                rebalance_band=port.get("rebalance_band", 0.25),
                max_position_pct=risk["max_position_pct"],
                max_gross_exposure=risk["max_gross_exposure"],
                min_order_value=risk["min_order_value"])


def _resolve_grid(settings: dict, args, name: str) -> dict:
    if args.grid:
        return {k: [_parse_params([f"{k}={v}"])[k] for v in vals.split("|")]
                for k, vals in (g.split("=", 1) for g in args.grid)}
    if name == settings["strategy"]["name"]:
        return settings["sweep"]["grid"]
    raise SystemExit(f'The config grid is for {settings["strategy"]["name"]}; '
                     f'pass --grid for {name}, e.g. --grid "period=2|3|5"')


def cmd_fetch(settings, args) -> None:
    bars, bench = _load_universe(settings, args)
    if bench is not None:
        bars[settings["backtest"]["benchmark"]] = bench
    for sym, df in bars.items():
        print(f"{sym:6} {len(df):6d} bars  {df.index[0].date()} -> {df.index[-1].date()}")


def cmd_backtest(settings, args) -> None:
    from .backtest import run_backtest
    from .backtest.report import print_summary, save_report
    from .strategies import build_strategy

    name, params = _strategy_cfg(settings, args)
    strategy = build_strategy(name, params)
    bars, bench = _load_universe(settings, args)
    result = run_backtest(bars, strategy, benchmark=bench, **_engine_kwargs(settings))
    print_summary(result, f"{strategy}  on  {', '.join(bars)}")
    if not args.no_save:
        out = save_report(result, settings["backtest"]["results_dir"], strategy.name)
        print(f"\nSaved report to {out}")


def cmd_sweep(settings, args) -> None:
    from .backtest import run_sweep

    name = args.strategy or settings["strategy"]["name"]
    sweep = settings["sweep"]
    grid = _resolve_grid(settings, args, name)
    bars, _ = _load_universe(settings, args, with_benchmark=False)
    risk, port = settings["risk"], settings.get("portfolio", {})
    metric = args.metric or sweep["metric"]
    table = run_sweep(bars, name, grid, split=args.split or sweep["split"], metric=metric,
                      slippage_bps=settings["backtest"]["slippage_bps"],
                      max_position_pct=risk["max_position_pct"],
                      max_gross_exposure=risk["max_gross_exposure"],
                      cash_buffer=port.get("cash_buffer", 0.02))
    print(f"\nSweep of {name}: {len(table)} combinations, ranked by in-sample {metric}")
    print(f"In-sample < {table.attrs['split_date'].date()} <= out-of-sample\n")
    with pd.option_context("display.float_format", "{:,.3f}".format, "display.width", 200):
        print(table.head(args.top).to_string())
    best = table.iloc[0]
    def clean(v):
        return int(v) if isinstance(v, float) and v.is_integer() else v
    flags = " ".join(f"--param {k}={clean(best[k])}" for k in grid)
    print("\nOut-of-sample numbers are the honest ones. If the in-sample winner falls apart "
          "out of sample, the edge is probably overfit.")
    print(f"Verify the top pick with the full engine:\n  trader backtest --strategy {name} {flags}")


def cmd_walkforward(settings, args) -> None:
    from .backtest import run_backtest, walk_forward
    from .backtest.report import print_summary, save_report

    name = args.strategy or settings["strategy"]["name"]
    grid = _resolve_grid(settings, args, name)
    wf_cfg = settings.get("walkforward", {})
    metric = args.metric or settings["sweep"]["metric"]
    bars, bench = _load_universe(settings, args)
    kw = _engine_kwargs(settings)
    wf = walk_forward(bars, name, grid,
                      train_years=args.train_years or wf_cfg.get("train_years", 3),
                      test_years=args.test_years or wf_cfg.get("test_years", 1),
                      anchored=args.anchored or wf_cfg.get("anchored", False), metric=metric,
                      slippage_bps=kw["slippage_bps"], max_position_pct=kw["max_position_pct"],
                      max_gross_exposure=kw["max_gross_exposure"], cash_buffer=kw["cash_buffer"])

    print(f"\nWalk-forward of {name}: {len(wf.windows)} windows, optimising {metric}\n")
    with pd.option_context("display.float_format", "{:,.3f}".format, "display.width", 200):
        print(wf.windows.to_string(index=False))
    print(f"\nParameters changed {wf.stats['param_changes']} times across "
          f"{wf.stats['windows']} windows (fewer changes = more robust parameters).")

    # Replay the stitched out-of-sample signals through the full backtrader engine.
    result = run_backtest(bars, None, benchmark=bench, signals=wf.signals, **kw)
    print_summary(result, f"Walk-forward {name} (out-of-sample only, backtrader)")
    if not args.no_save:
        out = save_report(result, settings["backtest"]["results_dir"], f"{name}_walkforward")
        wf.windows.to_csv(out / "windows.csv", index=False)
        print(f"\nSaved report to {out}")


def cmd_live(settings, args) -> None:
    from .live.runner import LiveRunner

    runner = LiveRunner(settings, dry_run=args.dry_run, allow_live_money=args.live_money)
    if args.loop:
        runner.loop()
    else:
        runner.run_once(force=args.force)


def cmd_account(settings, args) -> None:
    from .config import load_credentials
    from .live.broker import AlpacaBroker

    broker = AlpacaBroker(load_credentials())
    acct, clock = broker.account(), broker.clock()
    print(f"{'PAPER' if broker.paper else 'LIVE'} account {acct.account_number}  status {acct.status}")
    print(f"Equity {float(acct.equity):,.2f}  Cash {float(acct.cash):,.2f}  "
          f"Buying power {float(acct.buying_power):,.2f}")
    print(f"Market {'OPEN' if clock.is_open else 'closed'}; next open {clock.next_open}")
    for sym, qty in sorted(broker.positions().items()):
        print(f"  {sym:6} {qty:>10g}")


def cmd_report(settings, args) -> None:
    from datetime import timedelta

    from .config import load_credentials
    from .data import load_bars
    from .live.broker import AlpacaBroker
    from .live.report import account_equity_history, compare_to_benchmark

    broker = AlpacaBroker(load_credentials())
    bench_sym = args.benchmark or settings["backtest"].get("benchmark", "SPY")
    equity = account_equity_history(broker.trading, float(broker.account().equity))
    equity = equity[equity > 0]
    if args.start:
        equity = equity[equity.index >= pd.Timestamp(args.start)]
    if equity.empty:
        raise SystemExit("No account equity history in that range yet.")

    d = settings["data"]
    first = equity.index[0] - timedelta(days=10)
    bench = load_bars([bench_sym], first.date().isoformat(), feed=d["feed"],
                      adjustment=d["adjustment"], cache_dir=d["cache_dir"]).get(bench_sym)
    bench_close = bench["close"] if bench is not None else pd.Series(dtype=float)
    live = broker.latest_prices([bench_sym]).get(bench_sym)
    if live:  # today's bar isn't complete yet; use the latest trade for the live row
        bench_close.loc[equity.index[-1]] = live
    table = compare_to_benchmark(equity, bench_close)

    pct = {c: "{:+.2%}".format for c in ("account_return", "benchmark_return", "difference")}
    with pd.option_context("display.width", 200):
        print(table.to_string(formatters={"equity": "{:,.2f}".format,
                                          "benchmark": "{:,.2f}".format, **pct}))
    last = table.iloc[-1]
    verdict = "ahead of" if last["difference"] >= 0 else "behind"
    print(f"\nSince {table.index[0].date()}: account {last['account_return']:+.2%}, "
          f"{bench_sym} {last['benchmark_return']:+.2%} -> {abs(last['difference']):.2%} {verdict} "
          f"{bench_sym}. (Last row uses live prices.)")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trader", description=__doc__)
    p.add_argument("-c", "--config", help="path to settings.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    def data_args(sp):
        sp.add_argument("--symbols", help="comma-separated, overrides config")
        sp.add_argument("--start")
        sp.add_argument("--end")
        sp.add_argument("--csv-dir", help="read <SYMBOL>.csv files instead of Alpaca")
        sp.add_argument("--refresh", action="store_true", help="ignore the local cache")

    sp = sub.add_parser("fetch", help="download and cache historical data")
    data_args(sp)
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("backtest", help="full backtrader backtest + report")
    data_args(sp)
    sp.add_argument("--strategy")
    sp.add_argument("--param", action="append", help="override a param, e.g. --param fast=10")
    sp.add_argument("--no-save", action="store_true")
    sp.set_defaults(func=cmd_backtest)

    sp = sub.add_parser("sweep", help="fast parameter grid search with out-of-sample check")
    data_args(sp)
    sp.add_argument("--strategy")
    sp.add_argument("--grid", action="append", help='e.g. --grid "fast=10|20|50"')
    sp.add_argument("--split", type=float)
    sp.add_argument("--metric", choices=["sharpe", "cagr", "calmar", "sortino"])
    sp.add_argument("--top", type=int, default=15)
    sp.set_defaults(func=cmd_sweep)

    sp = sub.add_parser("walkforward", help="rolling re-optimisation, out-of-sample results only")
    data_args(sp)
    sp.add_argument("--strategy")
    sp.add_argument("--grid", action="append", help='e.g. --grid "fast=10|20|50"')
    sp.add_argument("--metric", choices=["sharpe", "cagr", "calmar", "sortino"])
    sp.add_argument("--train-years", type=float)
    sp.add_argument("--test-years", type=float)
    sp.add_argument("--anchored", action="store_true", help="expanding instead of rolling train window")
    sp.add_argument("--no-save", action="store_true")
    sp.set_defaults(func=cmd_walkforward)

    sp = sub.add_parser("live", help="run the strategy against your Alpaca account")
    sp.add_argument("--dry-run", action="store_true", help="compute orders but don't send them")
    sp.add_argument("--loop", action="store_true", help="keep running, once per trading day")
    sp.add_argument("--force", action="store_true", help="run even if the market is closed")
    sp.add_argument("--live-money", action="store_true",
                    help="required (with ALPACA_PAPER=false) to trade a real-money account")
    sp.set_defaults(func=cmd_live)

    sp = sub.add_parser("account", help="show account, clock and positions")
    sp.set_defaults(func=cmd_account)

    sp = sub.add_parser("report", help="account performance vs benchmark since trading began")
    sp.add_argument("--start", help="rebase from this date (default: first funded day)")
    sp.add_argument("--benchmark", help="benchmark symbol (default: backtest.benchmark)")
    sp.set_defaults(func=cmd_report)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    for noisy in ("urllib3", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    settings = load_settings(args.config)
    args.func(settings, args)


if __name__ == "__main__":
    sys.exit(main())
