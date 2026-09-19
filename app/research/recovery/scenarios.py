"""Fixed invented prices for behavior tests; never reported as investment returns."""
from copy import deepcopy

from .models import dec


def bar(minute, low, high, close, open_price=None):
    return dict(type="bar", end_ms=minute * 60000, received_ms=minute * 60000,
                open=str(close if open_price is None else open_price), low=str(low), high=str(high), close=str(close))


def quote(time_ms, price, auto=True):
    return dict(type="quote", time_ms=time_ms, bid=str(dec(price) - dec("0.01")), ask=str(price),
                max_total_qty="100", margin_room_qty="100", liquidity_qty="100",
                execution_ok=True, funding_known=True, simulate_fills=auto)


def setup():
    events = [bar(i, "103.9", "104.1", "104") for i in range(1, 49)]
    q = quote(48 * 60000 + 1, "103")
    q.pop("type")
    q.pop("simulate_fills")
    plan = dict(id="fixture", side=1, created_ms=48 * 60000,
                support=dict(id="support", version=1, low="100", high="101", available_ms=0, evidence="fixture_support"),
                target=dict(id="target", version=1, low="110", high="111", available_ms=0, evidence="fixture_target"),
                stop="99", initial_qty="4", reason="independent synthetic support thesis")
    events.append(dict(type="start", plan=plan, quote=q, simulate_fills=True))
    return events


def confirmed_path():
    return [bar(49, "100.8", "102", "100.9"), bar(50, "100.9", "101.5", "101.3"),
            bar(51, "101.2", "101.6", "101.4"), bar(52, "101.01", "101.4", "101.2"),
            bar(53, "101.05", "101.5", "101.4"), quote(53 * 60000 + 1, "101.4")]


def mirror(events):
    out = deepcopy(events)
    def price(p):
        return str(dec(206) - dec(p))
    for event in out:
        if event["type"] == "bar":
            event["low"], event["high"] = price(event["high"]), price(event["low"])
            event["open"], event["close"] = price(event["open"]), price(event["close"])
        q = event.get("quote") if event["type"] == "start" else event if event["type"] == "quote" else None
        if q:
            q["bid"], q["ask"] = price(q["ask"]), price(q["bid"])
        if event["type"] == "start":
            p = event["plan"]
            p["side"], p["stop"] = -1, price(p["stop"])
            for z in (p["support"], p["target"]):
                z["low"], z["high"] = price(z["high"]), price(z["low"])
    return out


def scenarios(config):
    base = setup()
    confirmed = base + confirmed_path()
    rejection = [bar(54, "109", "110.5", "109.2"), quote(54 * 60000 + 1, "109.2"),
                 quote(54 * 60000 + 2, "109.2")]
    larger_initial = deepcopy(base)
    larger_initial[-1]["plan"]["initial_qty"] = "6"
    yield "support_to_resistance", larger_initial + [bar(49, "109", "110.5", "109.2"),
         quote(49 * 60000 + 1, "109.2")], dict(adds=0, reduced=True)
    yield "adverse_add_recovery_reduce", confirmed + rejection, dict(adds=1, reduced=True, no_add_lots=True)
    yield "residual_final_exit", confirmed + rejection + [
        bar(i, "108", "109", "108.5") for i in (55, 56, 57)] + [
        bar(58, "109", "110.5", "109.2"), quote(58 * 60000 + 1, "109.2")], dict(adds=1, quantity="0")
    yield "target_breakout_hold", confirmed + [bar(54, "110.5", "112", "111.5"),
        bar(55, "111.01", "111.6", "111.2"), bar(56, "111.05", "111.8", "111.5"),
        quote(56 * 60000 + 1, "111.5")], dict(adds=1, breakout=True)
    yield "local_add_failure", confirmed + [bar(54, "100.8", "101.4", "100.9"),
         quote(54 * 60000 + 1, "100.9")], dict(adds=1, quantity="4", no_add_lots=True)
    yield "whole_support_failure", confirmed + [dict(type="context", time_ms=53 * 60000 + 2,
         thesis_valid=False, context_known=True), quote(53 * 60000 + 3, "100")], dict(adds=1, quantity="0")
    yield "one_way_decline", base + [bar(49, "94", "102", "94.2"),
         quote(49 * 60000 + 1, "94.2")], dict(adds=0, quantity="0")
    yield "no_retest_rally", base + confirmed_path()[:3] + [
        bar(i, "102", "103", "102.5") for i in range(52, 61)] + [
        quote(60 * 60000 + 1, "102.5")], dict(adds=0, quantity="4")
    yield "short_countertrend_independent_thesis", mirror(confirmed + rejection), dict(adds=1, reduced=True)
    yield "breakout_entry_failure", base + [dict(type="context", time_ms=48 * 60000 + 2,
         thesis_valid=False, context_known=True), quote(48 * 60000 + 3, "102")], dict(adds=0, quantity="0")
    yield "box_becomes_trend", base + [dict(type="context", time_ms=48 * 60000 + 2,
         thesis_valid=False, context_known=True), quote(48 * 60000 + 3, "99"),
         bar(49, "96", "100", "97")], dict(adds=0, quantity="0")
    yield "funding_recomputes_recovery", confirmed + [dict(type="funding", event_id="f1",
         amount="0.5", time_ms=53 * 60000 + 2)], dict(adds=1, funding=True)
    yield "data_gap_blocks_add", base + [bar(50, "100.8", "102", "101.4"),
         quote(50 * 60000 + 1, "101.4")], dict(adds=0, quantity="4", locked=True)
    # Failed local add -> genuinely fresh favorable 3m close -> visit/reclaim/retest.
    second = confirmed + [bar(54, "100.8", "101.4", "100.9"), quote(54 * 60000 + 1, "100.9"),
        bar(55, "101.1", "102", "101.5"), bar(56, "101.3", "102", "101.6"),
        bar(57, "101.3", "102", "101.6"), bar(58, "100.8", "101.8", "101.1"),
        bar(59, "101", "101.8", "101.5"), bar(60, "101.3", "101.8", "101.6"),
        bar(61, "101.02", "101.8", "101.5"), bar(62, "101.05", "101.8", "101.6"),
        quote(62 * 60000 + 1, "101.6")]
    yield "reduce_then_fresh_reentry", second, dict(adds=2)
    race = base + confirmed_path()[:-1] + [quote(53 * 60000 + 1, "101.4", False),
        dict(type="fill", fill_id="partial", order_id="fixture:2", quantity="1", price="101.4", fee="0.02535", time_ms=53 * 60000 + 2),
        dict(type="fault", time_ms=53 * 60000 + 3, reason="opposing_signal"),
        dict(type="fill", fill_id="late", order_id="fixture:2", quantity="1", price="101.4", fee="0.02535", time_ms=53 * 60000 + 4),
        dict(type="cancel_ack", order_id="fixture:2", time_ms=53 * 60000 + 5),
        quote(53 * 60000 + 6, "101.3")]
    yield "cancel_race_partial_fill", race, dict(adds=1, quantity="4", locked=True)


def verify_scenario(name, replay, expected):
    ledger = replay.engine.ledger
    ledger.audit()
    assert len(ledger.add_events) == expected["adds"], (name, "adds", replay.engine.snapshot())
    if "quantity" in expected:
        assert ledger.quantity == dec(expected["quantity"]), (name, "quantity", ledger.quantity)
    if expected.get("reduced"):
        assert any(row.get("kind") == "reduce" for row in ledger.rows), (name, "missing reduction")
    if expected.get("no_add_lots"):
        assert not any(lot.kind == "add" for lot in ledger.lots.values()), name
    if expected.get("locked"):
        assert replay.engine.locks, name
    if expected.get("funding"):
        assert "f1" in ledger.seen_funding, name
    if expected.get("breakout"):
        assert replay.engine.target_confirmation.state == "confirmed", name
        assert any(lot.kind == "add" for lot in ledger.lots.values()), name
    assert replay.engine.snapshot()["live_orders_sent"] == 0
