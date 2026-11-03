"""Performance statistics from an equity curve."""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1.0


def performance(equity: pd.Series) -> dict[str, float]:
    equity = equity.dropna()
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return {k: float("nan") for k in
                ("total_return", "cagr", "volatility", "sharpe", "sortino", "max_drawdown", "calmar")}
    rets = equity.pct_change().dropna()
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    total = equity.iloc[-1] / equity.iloc[0] - 1.0
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1.0
    vol = rets.std() * np.sqrt(TRADING_DAYS)
    sharpe = rets.mean() / rets.std() * np.sqrt(TRADING_DAYS) if rets.std() > 0 else 0.0
    downside = rets[rets < 0].std()
    sortino = rets.mean() / downside * np.sqrt(TRADING_DAYS) if downside and downside > 0 else 0.0
    mdd = drawdown(equity).min()
    calmar = cagr / abs(mdd) if mdd < 0 else 0.0
    return {
        "total_return": float(total),
        "cagr": float(cagr),
        "volatility": float(vol),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "max_drawdown": float(mdd),
        "calmar": float(calmar),
    }


def trade_stats(trades: pd.DataFrame) -> dict[str, float]:
    if trades.empty:
        return {"trades": 0, "win_rate": float("nan"), "profit_factor": float("nan"),
                "avg_trade_pnl": float("nan"), "avg_bars_held": float("nan")}
    wins = trades.loc[trades.pnl_net > 0, "pnl_net"].sum()
    losses = -trades.loc[trades.pnl_net < 0, "pnl_net"].sum()
    return {
        "trades": int(len(trades)),
        "win_rate": float((trades.pnl_net > 0).mean()),
        "profit_factor": float(wins / losses) if losses > 0 else float("inf"),
        "avg_trade_pnl": float(trades.pnl_net.mean()),
        "avg_bars_held": float(trades.bars.mean()),
    }
