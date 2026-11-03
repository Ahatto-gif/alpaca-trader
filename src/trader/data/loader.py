"""Historical daily bars from Alpaca, cached locally as parquet.

Every frame returned has a tz-naive DatetimeIndex (one row per trading day, US/Eastern
date) and lowercase columns: open, high, low, close, volume.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

COLUMNS = ["open", "high", "low", "close", "volume"]


def _cache_path(cache_dir: str, symbol: str, feed: str, adjustment: str) -> Path:
    return Path(cache_dir) / f"{symbol.upper()}_1Day_{feed}_{adjustment}.parquet"


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("America/New_York").tz_localize(None)
    df.index = idx.normalize()
    df.index.name = "date"
    df = df[COLUMNS].astype(float)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.dropna()


def _fetch_from_alpaca(symbols: list[str], start: datetime, end: datetime,
                       feed: str, adjustment: str) -> dict[str, pd.DataFrame]:
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    from ..config import load_credentials

    creds = load_credentials()
    client = StockHistoricalDataClient(creds.api_key, creds.secret_key)
    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        adjustment=Adjustment(adjustment),
        feed=DataFeed(feed),
    )
    try:
        raw = client.get_stock_bars(request).df
    except Exception as exc:  # alpaca raises APIError with a JSON body
        msg = str(exc)
        if "sip" in msg.lower() or "subscription" in msg.lower():
            raise SystemExit(
                f"Alpaca rejected the request ({msg}).\n"
                "Your plan may not include SIP data: set data.feed: iex in config/settings.yaml."
            ) from exc
        raise

    out: dict[str, pd.DataFrame] = {}
    if raw.empty:
        return out
    for sym in raw.index.get_level_values("symbol").unique():
        out[sym] = _normalize(raw.xs(sym, level="symbol"))
    return out


def load_bars(symbols: list[str], start: str, end: str | None = None, *,
              feed: str = "sip", adjustment: str = "all",
              cache_dir: str = "data/cache", refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Return {symbol: OHLCV frame} for [start, end], fetching only what the cache lacks."""
    start_ts = pd.Timestamp(start)
    # Free SIP data must be >15 min old; default end = start of today (completed bars only).
    now_utc = datetime.now(timezone.utc)
    end_dt = (pd.Timestamp(end).to_pydatetime().replace(tzinfo=timezone.utc) if end
              else now_utc.replace(hour=0, minute=0, second=0, microsecond=0))
    end_dt = min(end_dt, now_utc - timedelta(minutes=16))
    end_ts = pd.Timestamp(end_dt).tz_localize(None)

    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    result: dict[str, pd.DataFrame] = {}
    # Group symbols by the fetch window they need so we can batch API calls.
    needs: dict[tuple, list[str]] = {}

    for sym in symbols:
        path = _cache_path(cache_dir, sym, feed, adjustment)
        cached = pd.read_parquet(path) if path.exists() and not refresh else None
        if cached is not None and not cached.empty and cached.index[0] <= start_ts + timedelta(days=7):
            result[sym] = cached
            last = cached.index[-1]
            if last < end_ts.normalize() - timedelta(days=1):
                needs.setdefault((last + timedelta(days=1),), []).append(sym)
        else:
            needs.setdefault((start_ts,), []).append(sym)

    for (fetch_start,), syms in needs.items():
        log.info("Fetching %s from %s", ",".join(syms), fetch_start.date())
        fetched = _fetch_from_alpaca(syms, fetch_start.to_pydatetime(), end_dt, feed, adjustment)
        for sym in syms:
            new = fetched.get(sym)
            if new is None or new.empty:
                if sym not in result:
                    log.warning("No data returned for %s", sym)
                continue
            merged = pd.concat([result[sym], new]) if sym in result else new
            merged = merged[~merged.index.duplicated(keep="last")].sort_index()
            merged.to_parquet(_cache_path(cache_dir, sym, feed, adjustment))
            result[sym] = merged

    return {s: df.loc[start_ts:end_ts] for s, df in result.items() if not df.loc[start_ts:end_ts].empty}


def load_csv(path: str | Path) -> pd.DataFrame:
    """Load a CSV with a date column plus open/high/low/close/volume (any case)."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    date_col = next(c for c in df.columns if c in ("date", "datetime", "timestamp", "time"))
    df = df.set_index(pd.to_datetime(df.pop(date_col)))
    return _normalize(df)
