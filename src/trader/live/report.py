"""Compare the Alpaca account's equity with a benchmark (default SPY) since trading began."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

ET = ZoneInfo("America/New_York")


def compare_to_benchmark(equity: pd.Series, bench_close: pd.Series) -> pd.DataFrame:
    """Daily table of account vs benchmark, both rebased to the first equity date.

    `equity` and `bench_close` are indexed by date. Benchmark prices are taken as of each
    equity date (last known price on or before it), so weekends/holidays line up.
    """
    equity = equity[equity > 0].sort_index()
    if equity.empty:
        raise ValueError("No account equity history yet.")
    bench = bench_close.sort_index().reindex(equity.index, method="ffill")
    if pd.isna(bench.iloc[0]):
        raise ValueError(f"No benchmark price on or before {equity.index[0].date()}.")
    out = pd.DataFrame({"equity": equity, "benchmark": bench})
    out["account_return"] = out["equity"] / out["equity"].iloc[0] - 1
    out["benchmark_return"] = out["benchmark"] / out["benchmark"].iloc[0] - 1
    out["difference"] = out["account_return"] - out["benchmark_return"]
    return out


def account_equity_history(trading_client, current_equity: float | None = None,
                           period: str = "1A") -> pd.Series:
    """Daily closing equity from Alpaca, plus today's live equity if given."""
    from alpaca.trading.requests import GetPortfolioHistoryRequest

    hist = trading_client.get_portfolio_history(
        GetPortfolioHistoryRequest(period=period, timeframe="1D"))
    dates = [datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ET).date()
             for ts in hist.timestamp]
    equity = pd.Series([float(e or 0.0) for e in hist.equity],
                       index=pd.DatetimeIndex(dates), name="equity")
    if current_equity is not None:
        today = pd.Timestamp(datetime.now(ET).date())
        equity.loc[today] = float(current_equity)
    return equity[~equity.index.duplicated(keep="last")].sort_index()
