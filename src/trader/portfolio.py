"""Portfolio construction shared by the backtester and the live runner.

Keeping this in one place means the backtest trades exactly the way live trading will.
"""
from __future__ import annotations

import math


def target_weights(signals: dict[str, float], *, max_position_pct: float,
                   max_gross_exposure: float, cash_buffer: float = 0.0) -> dict[str, float]:
    """Equal-weight slots: each symbol gets 1/N of equity (capped) scaled by its signal."""
    if not signals:
        return {}
    slot = min(1.0 / len(signals), max_position_pct)
    weights = {s: max(0.0, min(1.0, v)) * slot for s, v in signals.items()}
    cap = max_gross_exposure * (1.0 - cash_buffer)
    gross = sum(weights.values())
    if gross > cap > 0:
        weights = {s: w * cap / gross for s, w in weights.items()}
    return weights


def plan_orders(*, equity: float, weights: dict[str, float], prices: dict[str, float],
                current_shares: dict[str, float], rebalance_band: float,
                min_order_value: float, cash: float | None = None,
                cash_reserve: float = 0.0) -> dict[str, int]:
    """Return {symbol: share delta}. Positive = buy, negative = sell. Whole shares only.

    A position is only resized when it drifts more than `rebalance_band` (as a fraction
    of its target value) from target. That avoids churning tiny trades every day.
    Exits (target 0) always go through.

    If `cash` is given, buys are scaled down so they fit in cash + sell proceeds - reserve
    (no accidental margin use when held positions have drifted above target).
    """
    orders: dict[str, int] = {}
    for sym, w in weights.items():
        price = prices.get(sym)
        if not price or price <= 0 or math.isnan(price):
            continue
        held = current_shares.get(sym, 0.0)
        target_value = equity * w
        target = math.floor(target_value / price)
        delta = int(target - held)
        if delta == 0:
            continue
        if target == 0:
            orders[sym] = int(-held)  # full exit
            continue
        drift = abs(held * price - target_value) / target_value
        if drift <= rebalance_band and held != 0:
            continue
        if abs(delta) * price < min_order_value:
            continue
        orders[sym] = delta

    if cash is not None:
        proceeds = sum(-d * prices[s] for s, d in orders.items() if d < 0)
        cost = sum(d * prices[s] for s, d in orders.items() if d > 0)
        available = cash + proceeds - cash_reserve
        if cost > 0 and cost > available:
            scale = max(0.0, available) / cost
            for sym in [s for s, d in orders.items() if d > 0]:
                qty = math.floor(orders[sym] * scale)
                if qty * prices[sym] < min_order_value or qty <= 0:
                    del orders[sym]
                else:
                    orders[sym] = qty
    return orders
