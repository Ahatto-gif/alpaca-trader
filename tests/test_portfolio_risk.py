from trader.live.risk import RiskLimits, apply_risk
from trader.portfolio import plan_orders, target_weights


def test_target_weights_equal_slots_and_cap():
    w = target_weights({"A": 1, "B": 1, "C": 0, "D": 1}, max_position_pct=0.2,
                       max_gross_exposure=1.0)
    assert w == {"A": 0.2, "B": 0.2, "C": 0.0, "D": 0.2}
    w = target_weights({"A": 1, "B": 1}, max_position_pct=1.0, max_gross_exposure=1.0,
                       cash_buffer=0.1)
    assert abs(sum(w.values()) - 0.9) < 1e-12


def test_plan_orders_band_and_exit():
    kwargs = dict(equity=10_000, prices={"A": 100, "B": 50}, rebalance_band=0.25,
                  min_order_value=100)
    # A slightly over target (within band) -> no trade; B should be exited.
    orders = plan_orders(weights={"A": 0.5, "B": 0.0}, current_shares={"A": 55, "B": 10}, **kwargs)
    assert orders == {"B": -10}
    # Fresh entry
    orders = plan_orders(weights={"A": 0.5, "B": 0.0}, current_shares={}, **kwargs)
    assert orders == {"A": 50}


def test_risk_blocks_buys_after_daily_loss():
    approved, notes = apply_risk({"A": 10, "B": -5}, prices={"A": 100, "B": 100},
                                 equity=9_600, last_equity=10_000,
                                 current_shares={"B": 5}, open_order_symbols=set(),
                                 limits=RiskLimits(daily_loss_limit_pct=0.03))
    assert approved == {"B": -5}
    assert any("Daily loss" in n for n in notes)


def test_risk_caps_position_and_gross():
    limits = RiskLimits(max_position_pct=0.2, max_gross_exposure=0.5, min_order_value=0)
    approved, _ = apply_risk({"A": 50, "B": 50, "C": 50}, prices={"A": 100, "B": 100, "C": 100},
                             equity=10_000, last_equity=10_000, current_shares={},
                             open_order_symbols={"C"}, limits=limits)
    assert "C" not in approved                       # open order -> skipped
    assert all(q <= 20 for q in approved.values())   # 20% cap
    assert sum(approved.values()) * 100 <= 5_000     # 50% gross cap


def test_plan_orders_respects_cash():
    # A has drifted up within band; not enough cash for B's full slot.
    orders = plan_orders(equity=10_000, weights={"A": 0.5, "B": 0.5},
                         prices={"A": 100, "B": 100}, current_shares={"A": 60},
                         rebalance_band=0.25, min_order_value=0, cash=4_000, cash_reserve=200)
    assert orders == {"B": 38}
