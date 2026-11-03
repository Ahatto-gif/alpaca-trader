"""Pre-trade risk checks. Pure functions so they are easy to unit test."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    max_position_pct: float = 0.2
    max_gross_exposure: float = 1.0
    daily_loss_limit_pct: float = 0.03
    max_orders_per_run: int = 20
    min_order_value: float = 100.0

    @classmethod
    def from_settings(cls, risk: dict) -> "RiskLimits":
        fields = cls.__dataclass_fields__
        return cls(**{k: v for k, v in risk.items() if k in fields})


def apply_risk(orders: dict[str, int], *, prices: dict[str, float], equity: float,
               last_equity: float, current_shares: dict[str, float],
               open_order_symbols: set[str], limits: RiskLimits) -> tuple[dict[str, int], list[str]]:
    """Filter/trim proposed orders. Returns (approved orders, list of notes)."""
    notes: list[str] = []
    approved: dict[str, int] = {}

    daily_pnl = (equity - last_equity) / last_equity if last_equity > 0 else 0.0
    halt_buys = daily_pnl <= -limits.daily_loss_limit_pct
    if halt_buys:
        notes.append(f"Daily loss {daily_pnl:.2%} breached limit "
                     f"-{limits.daily_loss_limit_pct:.2%}: buys blocked, sells allowed")

    # Sells first: they always reduce risk.
    for sym, delta in sorted(orders.items(), key=lambda kv: kv[1]):
        if sym in open_order_symbols:
            notes.append(f"{sym}: skipped, an order is already open")
            continue
        if delta < 0:
            approved[sym] = delta
            continue
        if halt_buys:
            continue
        price = prices[sym]
        # Cap so the resulting position never exceeds max_position_pct of equity.
        max_shares = int(equity * limits.max_position_pct / price)
        allowed = max(0, max_shares - int(current_shares.get(sym, 0)))
        if delta > allowed:
            notes.append(f"{sym}: buy trimmed {delta} -> {allowed} (max_position_pct)")
            delta = allowed
        if delta * price < limits.min_order_value:
            continue
        approved[sym] = delta

    # Gross exposure after trading must stay within the limit; trim the largest buys.
    def gross_after() -> float:
        shares = dict(current_shares)
        for s, d in approved.items():
            shares[s] = shares.get(s, 0) + d
        return sum(abs(q) * prices.get(s, 0) for s, q in shares.items()) / equity

    trimmed: set[str] = set()
    while gross_after() > limits.max_gross_exposure + 1e-9:
        buys = {s: d for s, d in approved.items() if d > 0}
        if not buys:
            break
        biggest = max(buys, key=lambda s: buys[s] * prices[s])
        approved[biggest] -= 1
        trimmed.add(biggest)
        if approved[biggest] == 0:
            del approved[biggest]
    notes.extend(f"{s}: buy trimmed to respect max_gross_exposure" for s in sorted(trimmed))

    if len(approved) > limits.max_orders_per_run:
        notes.append(f"Too many orders ({len(approved)}); keeping first "
                     f"{limits.max_orders_per_run} (sells prioritised)")
        approved = dict(list(approved.items())[: limits.max_orders_per_run])
    return approved, notes
