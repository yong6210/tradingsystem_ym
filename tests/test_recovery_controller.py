"""Causal state transitions, conservative sizing, actual-fill accounting and recovery."""
import copy
import json
from pathlib import Path

import pytest

from app.research.recovery.models import Bar, Costs, Plan, Policy, Quote, Zone, dec
from app.research.recovery.replay import Replay, make_plan
from app.research.recovery.scenarios import bar, confirmed_path, mirror, quote, scenarios, setup, verify_scenario
from app.research.recovery.signals import BarHistory, Confirmation

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "configs/research/recovery_v01.json").read_text())


def run(events=None, config=None):
    r = Replay(copy.deepcopy(config or CONFIG))
    for event in events or setup():
        r.process(event)
    return r


@pytest.mark.parametrize("name,events,expected", list(scenarios(CONFIG)))
def test_named_scenarios(name, events, expected):
    verify_scenario(name, run(events), expected)


def test_no_signal_on_touch_or_single_candle():
    r = run(setup() + confirmed_path()[:1])
    assert not r.engine.ledger.add_events
    assert r.engine.confirmation.state == "observing"


def test_confirmation_requires_distinct_retest_and_next_bar():
    r = run(setup() + confirmed_path()[:4])
    assert r.engine.confirmation.state == "retest"
    assert not r.engine.ledger.add_events
    r.process(confirmed_path()[4])
    assert r.engine.confirmation.state == "confirmed"
    r.process(quote(53 * 60000, "101.4"))
    assert not r.engine.ledger.add_events
    r.process(quote(53 * 60000 + 1, "101.4"))
    assert len(r.engine.ledger.add_events) == 1


def test_future_data_does_not_change_prefix():
    events = setup() + confirmed_path()
    a, b = run(events), run(events)
    trace = copy.deepcopy(a.engine.trace)
    snap = a.engine.snapshot()
    b.process(bar(54, "90", "120", "92"))
    assert b.engine.trace[:len(trace)] == trace
    assert a.engine.snapshot() == snap


def test_two_break_evens_satisfy_separate_pnl_equations():
    r = run(setup() + confirmed_path())
    e = r.engine
    e._reduce({"fixture:1": dec(1)}, "fixture_partial_loss")
    r.process(quote(53 * 60000 + 2, "102"))
    r.process(dict(type="funding", event_id="f", amount="0.75", time_ms=53 * 60000 + 3))
    a = e.ledger
    b = a.break_evens()
    assert b["position"] != b["campaign"]
    for field in ("position", "campaign"):
        p = b[field]
        execution = p * (1 - a.side * a.costs.slippage)
        pnl = a.side * a.quantity * (execution - a.average) - execution * a.quantity * a.costs.fee
        adjustment = -sum(x.allocated_cost for x in a.lots.values()) if field == "position" else a.cash - a.start_equity
        assert abs(pnl + adjustment) < dec("1e-20")


def test_profit_and_funding_credit_do_not_refill_loss_budget():
    r = run()
    a = r.engine.ledger
    before = a.paid_costs
    a.funding("credit", "-10", r.engine.last_time)
    assert a.paid_costs == before
    assert a.cash > a.start_equity
    assert r.engine.budget == dec(100)


def test_duplicate_fill_is_idempotent_but_conflicting_duplicate_fails():
    r = run()
    a = r.engine.ledger
    fill_id = next(iter(a.seen_fills))
    args = a.seen_fills[fill_id]
    before = a.cash
    assert a.apply_fill(fill_id, *args) is False
    assert a.cash == before
    changed = list(args)
    changed[2] += 1
    with pytest.raises(ValueError, match="conflicting duplicate"):
        a.apply_fill(fill_id, *changed)


def test_repeated_reduce_signal_does_not_oversell():
    r = run()
    e = r.engine
    e._exit("test")
    e._exit("test_again")
    assert sum(o.remaining for o in e.ledger.orders.values() if o.active and not o.increasing) == dec(4)
    r.process(quote(e.last_time + 1, "102"))
    assert e.ledger.quantity == 0
    assert e.ledger.break_evens() == {"position": None, "campaign": None}


def test_quote_jump_invalidates_add_economics():
    r = run(setup() + confirmed_path()[:-1])
    r.process(quote(53 * 60000 + 1, "109.9"))
    assert not r.engine.ledger.add_events
    assert r.engine.confirmation.state == "consumed"


def test_missing_costs_or_capacity_is_not_defaulted():
    q = quote(1, "100")
    q.pop("type")
    q.pop("simulate_fills")
    q.pop("funding_known")
    with pytest.raises(TypeError):
        Quote(**q)


def test_order_quantity_never_increased_to_meet_minimum():
    r = run(setup() + confirmed_path()[:-1])
    event = quote(53 * 60000 + 1, "101.4")
    event["liquidity_qty"] = "0.001"
    r.process(event)
    assert not r.engine.ledger.add_events


def test_atr_uses_only_completed_prior_bars():
    history = BarHistory()
    for i in range(1, 46):
        event = bar(i, "99", "101", "100")
        event.pop("type")
        history.push(Bar(**event))
    assert history.atr() == 2
    event = bar(46, "1", "200", "100")
    event.pop("type")
    history.push(Bar(**event))
    assert history.atr() == 2


def test_out_of_order_or_incomplete_bar_rejected():
    with pytest.raises(ValueError):
        Bar(60000, 100, 101, 99, 100, 59999)
    r = run()
    with pytest.raises(ValueError):
        r.process(bar(48, "103", "104", "103"))


def test_future_and_rewritten_zone_rejected():
    r = run()
    old = r.engine.support
    with pytest.raises(ValueError, match="future zone"):
        r.engine.set_context(r.engine.last_time, thesis_valid=True, context_known=True,
                             support=Zone("new", 1, 100, 101, r.engine.last_time + 1, "future"))
    with pytest.raises(ValueError, match="immutable"):
        r.engine.set_context(r.engine.last_time, thesis_valid=True, context_known=True,
                             support=Zone(old.id, old.version, 99, 101, 0, old.evidence))


def test_restart_is_locked_until_reconciled_and_fresh_evidence():
    r = run(setup() + confirmed_path())
    resumed = Replay.restore(CONFIG, r.checkpoint(), r.engine.last_time + 1)
    assert resumed.engine.ledger.quantity == r.engine.ledger.quantity
    assert "restart" in resumed.engine.locks
    assert resumed.engine.reconcile(resumed.engine.last_time + 1,
        actual_quantity=resumed.engine.ledger.quantity, orders_match=True, balance_matches=True, protection_ok=True,
        thesis_restored=True, gaps_repaired=True)
    assert resumed.engine.confirmation.state == "failed"


def test_corrupt_checkpoint_rejected():
    r = run()
    checkpoint = r.checkpoint()
    checkpoint["payload"]["state"]["snapshot"]["cash"] = "999999"
    with pytest.raises(ValueError, match="digest"):
        Replay.restore(CONFIG, checkpoint, r.engine.last_time + 1)


def test_position_mismatch_uses_authoritative_quantity_and_locks():
    r = run()
    e = r.engine
    assert not e.reconcile(e.last_time + 1, actual_quantity="5", orders_match=True, balance_matches=True,
                           protection_ok=True, thesis_restored=True, gaps_repaired=True)
    assert "position_mismatch" in e.locks
    assert e.trace[-1]["actual_quantity"] == "5"
    assert e.trace[-1]["reduce_only_quantity"] == "5"


def test_data_recovery_requires_three_bars_and_gap_repair():
    r = run()
    r.process(bar(50, 103, 104, 103))
    e = r.engine
    kw = dict(actual_quantity="4", orders_match=True, balance_matches=True, protection_ok=True, thesis_restored=True, gaps_repaired=True)
    assert not e.reconcile(e.last_time, **kw)
    for i in (51, 52, 53):
        r.process(bar(i, 103, 104, 103))
    assert not e.reconcile(e.last_time, **{**kw, "gaps_repaired": False})
    assert e.reconcile(e.last_time, **kw)


def test_no_connection_does_not_pretend_to_close():
    r = run()
    r.engine.fault(r.engine.last_time + 1, "disconnected", connected=False, protection_ok=False)
    assert r.engine.ledger.quantity == 4
    assert any(x["action"] == "external_action_required" for x in r.engine.trace)


def test_no_add_comparison_has_same_first_fill():
    config = {**CONFIG, "mode": "no_add"}
    events = setup() + confirmed_path()
    a, b = run(events), run(events, config)
    assert a.engine.ledger.rows[0] == b.engine.ledger.rows[0]
    assert not b.engine.ledger.add_events


def test_preplanned_splits_reserved_before_first_fill():
    events = setup()
    events[-1]["plan"]["splits"] = [["101", "2"]]
    events[-1]["plan"]["expires_ms"] = 60 * 60000
    r = run(events, {**CONFIG, "mode": "planned"})
    assert r.engine.ledger.quantity == 4
    assert any(o.active and o.kind == "planned" for o in r.engine.ledger.orders.values())
    r.process(quote(r.engine.last_time + 1, "101"))
    assert r.engine.ledger.quantity == 6
    assert not r.engine.ledger.add_events


def test_relabel_adverse_order_as_split_disallowed():
    events = setup()
    events[-1]["plan"]["splits"] = [["101", "2"]]
    events[-1]["plan"]["expires_ms"] = 60 * 60000
    with pytest.raises(ValueError, match="planned comparison"):
        run(events)


def test_plan_cannot_restart_while_cancel_pending():
    events = setup()
    events[-1]["simulate_fills"] = False
    r = run(events)
    r.engine._cancel_increases("test")
    with pytest.raises(ValueError, match="not settled"):
        r.engine.start(make_plan({**events[-1]["plan"], "id": "new"}), Quote(**events[-1]["quote"]))


def test_more_than_two_add_events_not_allowed():
    r = run(setup() + confirmed_path()[:-1])
    r.engine.ledger.add_events.update(("previous:1", "previous:2"))
    r.process(quote(53 * 60000 + 1, "101.4"))
    assert len(r.engine.ledger.add_events) == 2
    assert r.engine.trace[-1]["reason"] == "add_count_or_zone_lock"


def test_exact_deadline_expires_before_confirmation():
    r = run(setup() + confirmed_path()[:3])
    c = r.engine.confirmation
    event = bar(60, "101.01", "101.6", "101.4")
    event.pop("type")
    c.advance(Bar(**event), None, Policy())
    assert c.state == "expired"


def test_risk_reserved_for_pending_add_and_partial_fill_counted_once():
    events = setup() + confirmed_path()[:-1] + [quote(53 * 60000 + 1, "101.4", False)]
    r = run(events)
    e = r.engine
    pending_risk = e.ledger.risk_used()
    assert pending_risk <= e.budget
    for i in (1, 2):
        e.fill(f"part:{i}", "fixture:2", "1", "101.4", "0.02535", e.last_time + 1)
    assert len(e.ledger.add_events) == 1
    assert abs(e.ledger.risk_used() - pending_risk) < dec("1e-20")


def test_second_target_rejection_closes_all_residual_quantity():
    path = next(events for name, events, _ in scenarios(CONFIG) if name == "adverse_add_recovery_reduce")
    r = run(path)
    assert 0 < r.engine.ledger.quantity < 4
    for i in (55, 56, 57):
        r.process(bar(i, "108", "109", "108.5"))
    r.process(bar(58, "109", "110.5", "109.2"))
    r.process(quote(58 * 60000 + 1, "109.2"))
    assert r.engine.ledger.quantity == 0
    assert r.engine.ledger.settled


def test_resistance_stall_exits_adds_without_fixed_half_rule():
    r = run(setup() + confirmed_path())
    for i in range(54, 58):
        r.process(bar(i, "110.1", "110.8", "110.5"))
    assert r.engine.pending_management == "target_stall"
    r.process(quote(57 * 60000 + 1, "110.5"))
    assert not any(lot.kind == "add" for lot in r.engine.ledger.lots.values())


def test_breakout_and_retest_allow_holding_then_new_target():
    r = run(setup() + confirmed_path())
    qty = r.engine.ledger.quantity
    for event in (bar(54, "110.5", "112", "111.5"),
                  bar(55, "111.01", "111.6", "111.2"),
                  bar(56, "111.05", "111.8", "111.5")):
        r.process(event)
    assert r.engine.target_confirmation.state == "confirmed"
    r.process(quote(56 * 60000 + 1, "111.5"))
    assert r.engine.ledger.quantity == qty
    r.engine.set_context(56 * 60000 + 2, thesis_valid=True, context_known=True,
        target=Zone("next_target", 1, "120", "121", 56 * 60000, "new observed resistance"))
    assert r.engine.target.id == "next_target"


def test_target_cannot_be_moved_away_before_breakout():
    r = run()
    with pytest.raises(ValueError, match="extension requires"):
        r.engine.set_context(r.engine.last_time, thesis_valid=True, context_known=True,
            target=Zone("farther", 1, "120", "121", 0, "test"))


def test_breakeven_touch_alone_does_not_reduce():
    r = run()
    r.process(bar(49, "102.9", "103.2", "103.1"))
    r.process(quote(49 * 60000 + 1, "103.1"))
    assert r.engine.ledger.quantity == 4
    assert not any(o.kind == "reduce" for o in r.engine.ledger.orders.values())


def test_signal_and_stop_same_bar_prioritizes_exit():
    r = run(setup() + confirmed_path()[:4])
    r.process(bar(53, "98", "102", "101.5"))
    r.process(quote(53 * 60000 + 1, "101.5"))
    assert r.engine.ledger.quantity == 0
    assert not r.engine.ledger.add_events


def test_two_local_losses_lock_zone_even_if_renamed():
    path = next(events for name, events, _ in scenarios(CONFIG) if name == "reduce_then_fresh_reentry")
    r = run(path)
    r.process(bar(63, "100.5", "101.8", "100.8"))
    r.process(quote(63 * 60000 + 1, "100.8"))
    e = r.engine
    assert "support" in e.zone_locks
    assert e._zone_locked(Zone("renamed", 1, "100", "101", e.last_time, "same area"))
    e.set_context(75 * 60000, thesis_valid=True, context_known=True,
        support=Zone("support", 2, "100", "101.1", 75 * 60000, "new structure", structural_close_ms=75 * 60000))
    assert "support" not in e.zone_locks


def test_new_zone_version_without_structural_close_does_not_unlock():
    r = run()
    e = r.engine
    e.zone_locks["support"] = (1, e.last_time)
    e.set_context(e.last_time + 1, thesis_valid=True, context_known=True,
        support=Zone("support", 2, "100", "101.1", e.last_time + 1, "renumber only"))
    assert "support" in e.zone_locks


def test_pending_add_expires_and_cannot_fill_on_later_quote():
    r = run(setup() + confirmed_path()[:-1] + [quote(53 * 60000 + 1, "101.4", False)])
    for i in range(54, 61):
        r.process(bar(i, "101.1", "102", "101.5"))
    r.process(quote(60 * 60000 + 1, "101.4"))
    assert r.engine.ledger.orders["fixture:2"].status == "cancelled"
    assert not r.engine.ledger.add_events


def test_pending_add_below_its_stop_is_cancelled_before_fill():
    r = run(setup() + confirmed_path()[:-1] + [quote(53 * 60000 + 1, "101.4", False)])
    r.process(quote(53 * 60000 + 2, "100.7"))
    assert not r.engine.ledger.add_events
    assert r.engine.ledger.quantity == 4


def test_margin_capacity_shared_by_preplanned_orders():
    events = setup()
    events[-1]["plan"].update(splits=[["101", "1"], ["100", "1"]], expires_ms=60 * 60000)
    r = run(events, {**CONFIG, "mode": "planned"})
    q = quote(r.engine.last_time + 1, "99.5")
    q["margin_room_qty"] = "1"
    r.process(q)
    assert r.engine.ledger.quantity == 5


def test_expired_planned_order_has_no_assumed_fill():
    events = setup()
    events[-1]["plan"].update(splits=[["101", "2"]], expires_ms=49 * 60000)
    r = run(events, {**CONFIG, "mode": "planned"})
    r.process(bar(49, "101", "103", "101"))
    r.process(quote(49 * 60000 + 1, "101"))
    assert r.engine.ledger.quantity == 4
    assert r.engine.ledger.orders["fixture:2"].status == "cancelled"


def test_heartbeat_without_new_bars_stops_increases():
    r = run()
    r.process(dict(type="heartbeat", time_ms=49 * 60000 + 10001))
    assert "data_late" in r.engine.locks
    assert r.engine.ledger.quantity == 4


def test_fresh_evidence_can_rearm_after_data_recovery_without_old_signal():
    r = run()
    r.process(bar(50, "103", "104", "103"))
    for i in (51, 52, 53):
        r.process(bar(i, "103", "104", "103"))
    e = r.engine
    e.reconcile(e.last_time, actual_quantity="4", orders_match=True, balance_matches=True,
                protection_ok=True, thesis_restored=True, gaps_repaired=True)
    # Rebuild the mandatory prior ATR window after the data gap; no hidden fill.
    for i in range(54, 100):
        r.process(bar(i, "103", "104", "103"))
    assert e.support_armed
    assert not e.ledger.add_events


def test_account_halt_is_not_cleared_by_campaign_exit_or_reconciliation():
    r = run()
    e = r.engine
    e.fault(e.last_time + 1, "account_halt", account_halted=True)
    r.process(quote(e.last_time + 1, "103"))
    assert e.ledger.quantity == 0
    e.reconcile(e.last_time + 1, actual_quantity="0", orders_match=True, balance_matches=True,
                protection_ok=True, thesis_restored=True, gaps_repaired=True)
    assert "account_halted" in e.locks


def test_nonfinite_number_and_invalid_risk_settings_rejected():
    with pytest.raises(ValueError):
        dec("NaN")
    with pytest.raises(ValueError):
        Policy(campaign_fraction="2")


def test_short_break_evens_include_fees_and_slippage():
    r = run(mirror(setup() + confirmed_path()))
    a = r.engine.ledger
    p = a.break_evens()["campaign"]
    execution = p * (1 + a.costs.slippage)
    pnl = a.cash - a.start_equity - a.quantity * (execution - a.average) - execution * a.quantity * a.costs.fee
    assert abs(pnl) < dec("1e-20")


def test_market_view_does_not_force_position_direction():
    r = run(mirror(setup()))
    r.engine.set_context(r.engine.last_time + 1, thesis_valid=True, context_known=True,
                         market_view={"large_flow": "up", "location": "resistance", "short_term": "rejection"})
    assert r.engine.plan.side == -1
    assert r.engine.ledger.quantity == 4
    assert r.engine.market_view["large_flow"] == "up"


def test_snapshot_config_binding_prevents_wrong_policy_resume():
    r = run()
    with pytest.raises(ValueError, match="binding"):
        Replay.restore({**CONFIG, "mode": "no_add"}, r.checkpoint(), r.engine.last_time + 1)


def test_balance_mismatch_cannot_unlock():
    r = run()
    e = r.engine
    e.fault(e.last_time + 1, "restart")
    assert not e.reconcile(e.last_time + 1, actual_quantity="4", orders_match=True, balance_matches=False,
                           protection_ok=True, thesis_restored=True, gaps_repaired=True)
    assert "restart" in e.locks


def test_observation_fifth_three_minute_bar_expires():
    r = run()
    for i in range(49, 64):
        r.process(bar(i, "100.2", "100.8", "100.5"))
    assert r.engine.confirmation.state == "expired"
    assert r.engine.confirmation.reason == "recovery_timeout"


def test_pending_initial_order_cannot_fill_beyond_common_stop():
    events = setup()
    events[-1]["simulate_fills"] = False
    r = run(events)
    r.process(quote(r.engine.last_time + 1, "98"))
    assert r.engine.ledger.quantity == 0
    assert r.engine.ledger.orders["fixture:1"].status == "cancelled"


def test_add_zone_invalidation_exits_its_lots_without_common_stop():
    r = run(setup() + confirmed_path())
    e = r.engine
    e.set_context(e.last_time + 1, thesis_valid=True, context_known=True,
        support=Zone("support", 2, "100", "101", e.last_time, "support invalidated", valid=False))
    r.process(quote(e.last_time + 1, "101.2"))
    assert e.ledger.quantity == 4
    assert not any(lot.kind == "add" for lot in e.ledger.lots.values())


def test_json_string_false_cannot_be_used_as_boolean():
    q = setup()[-1]["quote"]
    q["execution_ok"] = "false"
    with pytest.raises(ValueError, match="booleans"):
        Quote(**q)


def test_new_campaign_preserves_full_ledger_output_and_requires_new_evidence(tmp_path):
    events = setup()
    r = run(events)
    e = r.engine
    r.process(dict(type="context", time_ms=e.last_time + 1, thesis_valid=False, context_known=True))
    r.process(quote(e.last_time + 1, "103"))
    old_closed = e.last_time
    next_event = copy.deepcopy(events[-1])
    next_event["plan"]["id"] = "second"
    next_event["quote"]["time_ms"] = old_closed + 1
    r.process(next_event)
    assert e.trace[-1]["reason"] == "fresh_entry_evidence_required"
    next_event["plan"]["created_ms"] = old_closed + 2
    next_event["quote"]["time_ms"] = old_closed + 3
    r.process(next_event)
    assert e.plan.id == "second"
    assert len(e.archived_ledgers) == 1
    r.write(tmp_path / "result")
    assert len((tmp_path / "result/ledger.jsonl").read_text().splitlines()) == 3
    restored = Replay.restore(CONFIG, r.checkpoint(), e.last_time + 1)
    assert restored.engine.ledger.quantity == 4


def test_failed_context_validation_keeps_existing_judgment():
    r = run()
    e = r.engine
    old_support = e.support
    with pytest.raises(ValueError):
        e.set_context(e.last_time, thesis_valid=False, context_known=False,
            support=Zone("new", 1, "99", "100", 0, "new"),
            target=Zone("unconfirmed_extension", 1, "120", "121", 0, "new"))
    assert e.thesis_valid and e.context_known
    assert e.support == old_support


def test_quote_after_protection_loss_can_only_reduce():
    r = run()
    e = r.engine
    e.reconcile(e.last_time + 1, actual_quantity="4", orders_match=True, balance_matches=True,
                protection_ok=False, thesis_restored=True, gaps_repaired=True)
    r.process(quote(e.last_time + 1, "103"))
    assert e.ledger.quantity == 0


def test_authoritative_mismatch_cannot_auto_fill_stale_reduction():
    r = run()
    e = r.engine
    e._exit("old_exit")
    e.reconcile(e.last_time + 1, actual_quantity="1", orders_match=False, balance_matches=False,
                protection_ok=False, thesis_restored=False, gaps_repaired=True)
    r.process(quote(e.last_time + 1, "98"))
    assert e.ledger.quantity == 4  # Internal ledger is explicitly untrusted, not silently rewritten.
    assert e.snapshot()["authoritative_quantity"] == "1"
    assert len(e.ledger.rows) == 1
