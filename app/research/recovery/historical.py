"""Causal minute-open proxy adapter; independent matched episodes, never live."""
from collections import Counter
from dataclasses import replace
import math

import pandas as pd

from app.research.diagnostics.context_timing_signals_v2 import entry_intent, context
from .engine import RecoveryEngine
from .models import Bar, Costs, Plan, Policy, Quote, Zone, dec, floor_step, jsonable
from .replay import Replay


def costs_for(config, name):
    return Costs(config["fee"], (dec(config["costs"][name]) + dec(config["half_spread_bps"])) / 10000,
                 config["tick"], config["step"], config["minimum_qty"], config["minimum_notional"])


def proxy_quote(time_ms, raw_open, prior_volume, equity, quantity, costs, config):
    p = dec(raw_open)
    # Costs.slippage includes the assumed half-spread for boundary/risk estimates.
    bid = costs.exit_price(p, 1)
    ask = costs.exit_price(p, -1)
    total = floor_step(max(dec(0), equity) * dec(config["total_exposure_fraction"]) / p, costs.step)
    liquidity = floor_step(dec(prior_volume) * dec(config["prior_minute_volume_participation"]), costs.step)
    return Quote(time_ms, bid, ask, total, max(dec(0), total - quantity), liquidity, True, True)


def make_bar(start_ms, values):
    return Bar(start_ms + 60000, *map(dec, values[:4]), start_ms + 60000)


def common_candidate(t_ms, values, zones, cutoff, raw_open, prior_volume, config):
    """Only then-known inputs; no future episode outcomes in eligibility."""
    if not values.get("decision"):
        return None, "not_decision"
    needed = ("daily", "four_hour", "hour", "quarter", "atr", "b_l", "b_h", "b_c", "b_o",
              "b_previous_close", "m_c", "m_o", "m_previous_close", "m_previous_high", "m_previous_low")
    if any(not math.isfinite(float(values[k])) for k in needed):
        return None, "context_missing"
    side, support, bias = entry_intent(zones, values)
    if not side:
        return None, "no_entry_reaction"
    cost = costs_for(config, "stress")
    quote = proxy_quote(t_ms + 1, raw_open, prior_volume, dec(config["initial_equity"]), dec(0), cost, config)
    entry = quote.entry(side)
    targets = [z for z in zones if side * (dec(z.low if side == 1 else z.high) - entry) > 0]
    if not targets:
        return None, "no_target"
    target = min(targets, key=lambda z: side * (dec(z.low if side == 1 else z.high) - entry))
    buffer = max(2 * cost.tick, dec(values["atr"]) * dec("0.10"))
    stop = dec(support.low if side == 1 else support.high) - side * buffer
    if side == 1:
        stop = floor_step(stop, cost.tick)
    # Round protective boundary away from entry, never make risk appear smaller.
    if side == -1:
        rounded = floor_step(stop, cost.tick)
        stop = rounded if rounded == stop else rounded + cost.tick
    checker = RecoveryEngine(config["initial_equity"], cost)
    target_price = dec(target.low if side == 1 else target.high)
    if not checker._rr(entry, stop, target_price, side):
        return None, "initial_rr"
    if cutoff + 60000 > t_ms:
        raise ValueError("profile not yet available")
    low, high = dec(support.low), dec(support.high)
    fractions = (dec("0.75"), dec("0.25")) if side == 1 else (dec("0.25"), dec("0.75"))
    split_prices = [floor_step(low + (high - low) * f, cost.tick) for f in fractions]
    if any(side * (p - entry) >= 0 or not checker._rr(p, stop, target_price, side) for p in split_prices):
        return None, "split_geometry"
    b = dec(config["initial_equity"]) * dec(config["campaign_fraction"])
    capacity = min(quote.max_total_qty, quote.margin_room_qty, quote.liquidity_qty)
    initial = floor_step(min(b * dec(config["initial_risk_fraction_of_campaign"]) /
                             cost.loss(entry, stop, side), capacity * dec("0.5")), cost.step)
    splits = tuple((p, floor_step(min(b * dec(config["split_risk_fraction_of_campaign"]) /
                                      cost.loss(p, stop, side), capacity * dec("0.25")), cost.step)) for p in split_prices)
    if not cost.executable(initial, entry) or any(not cost.executable(q, p) for p, q in splits):
        return None, "common_size_below_minimum"
    identifier = f"hist:{t_ms}"
    def z(source, label):
        return Zone(identifier + ":" + label, 1, dec(source.low), dec(source.high), cutoff + 60000,
                    f"E055 executed-volume {source.horizon}; cutoff={cutoff}; share={source.share}")
    plan = Plan(identifier, side, t_ms, z(support, "support"), z(target, "target"), stop, initial,
                f"E056-v2 entry_intent; context={bias}; source_3m_available_by={t_ms}", splits, t_ms + 900000)
    # The compared controller, not a duplicate sizing implementation, has final admission.
    checker.mode = "planned"
    checker.start(plan, quote)
    if checker.ledger is None:
        return None, "controller_" + checker.trace[-1]["reason"]
    return plan, "eligible"


def select_plans(trade, features, profiles, config):
    start, end = pd.Timestamp(config["entry_start"]), pd.Timestamp(config["entry_end"])
    days = {str(d.date()): dict(selected=None, rejections=Counter()) for d in pd.date_range(start, end, inclusive="left", freq="D")}
    plans = []
    for t, row in features.loc[(features.index >= start) & (features.index < end)].iterrows():
        day = days[str(t.date())]
        if day["selected"] is not None or not row["decision"]:
            continue
        t_ms = int(t.timestamp() * 1000)
        anchor = int(row.anchor_ms) if math.isfinite(row.anchor_ms) else None
        zones, cutoff = profiles.snapshot(t_ms, anchor)
        prior = trade.loc[t - pd.Timedelta(minutes=1)]
        plan, reason = common_candidate(t_ms, row.to_dict(), zones, cutoff, trade.loc[t, "o"], prior.v, config)
        if plan is None:
            day["rejections"][reason] += 1
        else:
            plans.append(plan)
            day["selected"] = plan.id
    return plans, days


def simulate_episode(trade, mark, features, funding, plan, config, policy, cost_name):
    cost = costs_for(config, cost_name)
    e = RecoveryEngine(config["initial_equity"], cost, Policy(campaign_fraction=config["campaign_fraction"]), policy)
    broker = Replay({"initial_equity": config["initial_equity"], "mode": policy,
                     "costs": jsonable(cost)})
    broker.engine = e
    left = pd.to_datetime(plan.created_ms, unit="ms", utc=True)
    right = left + pd.Timedelta(hours=config["observation_hours"])
    selected = trade.loc[(trade.index >= left) & (trade.index < right)]
    if len(selected) != config["observation_hours"] * 60:
        raise ValueError("episode input incomplete")
    # Warmup has no position; directly feed history without fictitious decisions.
    warmup = trade.loc[(trade.index >= left - pd.Timedelta(minutes=48)) & (trade.index < left)]
    for t, row in warmup.iterrows():
        e.on_bar(make_bar(int(t.timestamp() * 1000), row[["o", "h", "l", "c"]]))
    e.trace.clear()
    effective_plan = replace(plan, splits=plan.splits if policy == "planned" else (),
                             expires_ms=plan.expires_ms if policy == "planned" else None)
    opening = proxy_quote(plan.created_ms + 1, selected.o.iloc[0], warmup.v.iloc[-1],
                          dec(config["initial_equity"]), dec(0), cost, config)
    e.start(effective_plan, opening)
    if e.ledger is None:
        raise AssertionError(f"shared admission failed: {policy}/{cost_name}: {e.trace[-1]}")
    broker.match(opening)
    if e.ledger.quantity != plan.initial_qty:
        raise AssertionError("initial fills differ across paired policies")
    decisions = list(e.trace)
    e.trace.clear()
    reasons = Counter()
    peak = dec(config["initial_equity"])
    max_dd, max_exposure = dec(0), dec(0)
    max_qty = e.ledger.quantity
    last_mark = dec(mark.loc[left, "o"])
    ending_reference = dec(selected.o.iloc[0])
    liquidation = e.ledger.cash
    held_minutes = 0
    ambiguous = 0
    equity_path = []
    fund_rows = [r for r in funding if plan.created_ms + 1 < int(r["fundingTime"]) < int(right.timestamp() * 1000)]
    fund_index = 0
    previous = None
    for t, row in selected.iterrows():
        ts = int(t.timestamp() * 1000)
        if ts > plan.created_ms:
            # Funding may occur inside the previous minute. There are no synthetic
            # intraminute fills, so its held quantity is known without finer prices.
            while fund_index < len(fund_rows) and int(fund_rows[fund_index]["fundingTime"]) <= ts:
                event = fund_rows[fund_index]
                amount = e.plan.side * e.ledger.quantity * dec(event["markPrice"]) * dec(event["fundingRate"])
                e.funding(str(event["fundingTime"]), amount, int(event["fundingTime"]))
                fund_index += 1
            # Closed previous minute becomes known before this minute's proxy quote.
            e.on_bar(make_bar(ts - 60000, previous[["o", "h", "l", "c"]]))
            v = features.loc[t]
            lower = plan.support.low if plan.side == 1 else plan.support.high
            valid_context = all(math.isfinite(float(v[k])) for k in ("daily", "four_hour", "hour", "quarter", "h_close", "h_previous_close"))
            failed = valid_context and all(plan.side * (dec(v[k]) - lower) < 0 for k in ("h_close", "h_previous_close"))
            e.set_context(ts, thesis_valid=not failed, context_known=valid_context,
                          market_view={k: float(v[k]) if math.isfinite(float(v[k])) else None
                                       for k in ("daily", "four_hour", "hour", "quarter")})
            # Exchange funding timestamps may be minute+1ms, the same timestamp as
            # our proxy fill. Funding belongs to the pre-fill position.
            while fund_index < len(fund_rows) and int(fund_rows[fund_index]["fundingTime"]) <= ts + 1:
                event = fund_rows[fund_index]
                amount = e.plan.side * e.ledger.quantity * dec(event["markPrice"]) * dec(event["fundingRate"])
                e.funding(str(event["fundingTime"]), amount, int(event["fundingTime"]))
                fund_index += 1
            # Capacity includes funding already paid, but never the future bar low.
            mark_open = dec(mark.loc[t, "o"])
            equity = e.ledger.cash + plan.side * e.ledger.quantity * (mark_open - (e.ledger.average or mark_open))
            quote = proxy_quote(ts + 1, row.o, previous.v, equity, e.ledger.quantity, cost, config)
            e.on_quote(quote)
            broker.match(quote)
        q = e.ledger.quantity
        if q:
            held_minutes += 1
        if q and (dec(row.l) <= plan.stop <= dec(row.h)):
            ambiguous += 1  # Boundary seen only at this bar's close; never fill retrospectively.
        last_mark = dec(mark.loc[t, "c"])
        ending_reference = dec(row.c)
        execution = cost.exit_price(ending_reference, plan.side)
        liquidation = e.ledger.cash + plan.side * q * (execution - (e.ledger.average or execution)) - q * execution * cost.fee
        mark_equity = e.ledger.cash + plan.side * q * (last_mark - (e.ledger.average or last_mark))
        # Completed-minute close drawdown only; not an intrabar guarantee.
        peak = max(peak, liquidation)
        max_dd = max(max_dd, (peak - liquidation) / peak)
        if mark_equity <= 0:
            raise ValueError("requires exchange liquidation model")
        max_exposure = max(max_exposure, q * ending_reference / mark_equity)
        max_qty = max(max_qty, q)
        for record in e.trace:
            reasons[record["reason"]] += 1
            if record["action"] not in ("observe", "context", "wait", "hold") or record["reason"] in (
                "additional_trade_geometry_or_cost", "additional_size_below_minimum", "not_adverse_position"):
                decisions.append(record)
        e.trace.clear()
        equity_path.append(dict(time_ms=ts+59999, liquidation_equity=liquidation, mark_equity=mark_equity,
                                quantity=q, exposure=q*ending_reference/mark_equity))
        previous = row
        if e.ledger.settled:
            break
    else:
        while fund_index < len(fund_rows):
            event = fund_rows[fund_index]
            amount = e.plan.side * e.ledger.quantity * dec(event["markPrice"]) * dec(event["fundingRate"])
            e.funding(str(event["fundingTime"]), amount, int(event["fundingTime"]))
            fund_index += 1
        # End-of-window observed bar can create a pending exit, but no post-window fill.
        e.on_bar(make_bar(int(selected.index[-1].timestamp()*1000), previous[["o", "h", "l", "c"]]))
        decisions.extend(e.trace)
        e.trace.clear()
        q = e.ledger.quantity
        execution = cost.exit_price(ending_reference, plan.side)
        liquidation = e.ledger.cash + plan.side * q * (execution - (e.ledger.average or execution)) - q * execution * cost.fee
        max_dd = max(max_dd, (peak - liquidation) / peak)
    e.ledger.audit()
    first = e.ledger.rows[0]
    if first["qty"] != plan.initial_qty:
        raise AssertionError("first fill quantity mismatch")
    for record in e.ledger.rows:
        if record["type"] != "fill":
            continue
        source_ms = (record["time_ms"] // 60000) * 60000
        source_open = dec(trade.loc[pd.to_datetime(source_ms, unit="ms", utc=True), "o"])
        action_side = plan.side if record["kind"] != "reduce" else -plan.side
        expected = cost.exit_price(source_open, -action_side)
        if record["price"] != expected or record["fee"] != record["qty"] * expected * cost.fee:
            raise AssertionError("fill not explained by raw minute open and cost")
        if record["time_ms"] % 60000 != 1:
            raise AssertionError("fill not after completed signal/open proxy")
    summary = dict(plan_id=plan.id, entry_ms=plan.created_ms, policy=policy, cost=cost_name,
                   initial_qty=plan.initial_qty, initial_price=first["price"], side=plan.side,
                   net_liquidation_pnl=liquidation-dec(config["initial_equity"]),
                   cash_pnl=e.ledger.cash-dec(config["initial_equity"]), remaining_qty=e.ledger.quantity,
                   right_censored=not e.ledger.settled, fills=len(e.ledger.seen_fills),
                   add_events=len(e.ledger.add_events), planned_fills=sum(r.get("kind")=="planned" for r in e.ledger.rows),
                   max_quantity=max_qty, max_close_drawdown=max_dd, max_close_exposure=max_exposure,
                   holding_minutes=held_minutes, stop_touch_minutes=ambiguous,
                   reasons=dict(reasons), final=e.snapshot())
    return jsonable(summary), jsonable(e.ledger.rows), decisions, jsonable(equity_path)
