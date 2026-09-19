"""Offline event controller for ADVERSE_POSITION_RECOVERY_SPEC v0.1.

Produces order intents; only explicit fills change positions. A broker adapter
must implement cancellation, protection and reconciliation before live use.
"""
from .ledger import Ledger, Order
from .models import Costs, Plan, Policy, Quote, Zone, dec, floor_step, jsonable, positive, require_flags
from .signals import BarHistory, Confirmation


class RecoveryEngine:
    def __init__(self, equity, costs: Costs, policy=None, mode="confirmed"):
        if mode not in ("confirmed", "no_add", "planned"):
            raise ValueError("unknown comparison mode")
        self.costs, self.policy, self.mode = costs, policy or Policy(), mode
        self.equity = positive(equity)
        self.plan = None
        self.ledger = None
        self.history = BarHistory()
        self.support = None
        self.target = None
        self.confirmation = None
        self.target_confirmation = None
        self.buffer = None
        self.recovery_stop = None
        self.target_stalls = 0
        self.target_armed = True
        self.support_armed = True
        self.reduced_once = False
        self.pending_management = None
        self.locks = set()
        self.thesis_valid = True
        self.context_known = True
        self.connected = True
        self.protection_ok = True
        self.healthy_bars = 0
        self.loss_streaks = {}
        self.zone_locks = {}
        self.zone_definitions = {}
        self.stopped_events = set()
        self.event_realized = {}
        self.rearm_after_ms = -1
        self.used_plans = set()
        self.archives = []
        self.archived_ledgers = {}
        self.trace = []
        self.last_time = -1
        self.sequence = 0
        self.quote = None
        self.exit_latched = False
        self.budget = dec(0)
        self.account_halted = False
        self.reconciled = True
        self.closed_at_ms = -1
        self.market_view = {}
        self.authoritative_quantity = None

    def _time(self, time_ms):
        if time_ms < self.last_time:
            raise ValueError("events must be delivered chronologically")
        self.last_time = time_ms

    def record(self, action, reason, **extra):
        row = dict(time_ms=self.last_time, action=action, reason=reason,
                   plan_id=self.plan.id if self.plan else None,
                   quantity=self.ledger.quantity if self.ledger else dec(0),
                   risk_used=self.ledger.risk_used() if self.ledger else dec(0),
                   budget=self.budget, locks=sorted(self.locks), **extra)
        self.trace.append(jsonable(row))
        return row

    def _discard_signal(self, reason):
        if self.confirmation:
            self.confirmation.state, self.confirmation.reason = "failed", reason
        self.support_armed = False
        self.rearm_after_ms = self.last_time

    def _cancel_increases(self, reason):
        if not self.ledger:
            return
        for o in self.ledger.orders.values():
            if o.active and o.increasing and o.status != "cancel_pending":
                o.status = "cancel_pending"
                self.record("cancel_request", reason, order_id=o.id, transport_available=self.connected)

    def _new_order(self, kind, qty, reason, **kwargs):
        self.sequence += 1
        o = Order(f"{self.plan.id}:{self.sequence}", self.last_time, qty, kind, reason, **kwargs)
        self.ledger.orders[o.id] = o
        self.record("order_intent", reason, order=jsonable(o), evidence=self.evidence())
        return o

    def evidence(self):
        return dict(support=jsonable(self.support), target=jsonable(self.target),
                    confirmation=jsonable(self.confirmation), context_known=self.context_known,
                    thesis_valid=self.thesis_valid, market_view=self.market_view,
                    break_evens=self.ledger.break_evens() if self.ledger else None)

    def _reduce(self, targets, reason):
        # Reserve reductions by lot so repeated signals cannot over-close.
        if "position_mismatch" in self.locks or "archived_campaign_fill" in self.locks:
            self.record("external_action_required", "authoritative_reconciliation_before_attributed_reduction",
                        actual_quantity=self.authoritative_quantity)
            return None
        if not self.connected:
            self.record("external_action_required", reason, targets=targets)
            return None
        net = {}
        for key, requested in targets.items():
            lot = self.ledger.lots.get(key)
            if not lot:
                continue
            reserved = sum((o.targets.get(key, dec(0)) for o in self.ledger.orders.values()
                            if o.active and not o.increasing), dec(0))
            amount = min(requested, max(dec(0), lot.quantity - reserved))
            if amount:
                net[key] = amount
        qty = sum(net.values(), dec(0))
        if not qty:
            return None
        return self._new_order("reduce", qty, reason, targets=net)

    def _exit(self, reason):
        self.exit_latched = True
        self._discard_signal(reason)
        self._cancel_increases(reason)
        if self.ledger:
            self._reduce({k: lot.quantity for k, lot in self.ledger.lots.items()}, reason)

    def _blocked(self):
        return bool(self.locks or not self.connected or not self.reconciled or
                    not self.context_known or not self.thesis_valid or not self.protection_ok or self.exit_latched)

    def _rr(self, entry, stop, target, side):
        out = self.costs.exit_price(stop, side)
        goal = self.costs.exit_price(target, side)
        if side * (entry - stop) <= 0 or side * (target - entry) <= 0:
            return False
        loss = side * (entry - out) + self.costs.fee * (entry + out)
        gain = side * (goal - entry) - self.costs.fee * (entry + goal)
        return loss > 0 and gain / loss >= self.policy.minimum_rr

    def start(self, plan: Plan, quote: Quote):
        self._time(quote.time_ms)
        if plan.created_ms > quote.time_ms or plan.id in self.used_plans:
            raise ValueError("future/reused plan")
        if plan.expires_ms is not None and quote.time_ms >= plan.expires_ms:
            return self.record("wait", "plan_expired")
        if plan.created_ms <= self.closed_at_ms:
            return self.record("wait", "fresh_entry_evidence_required")
        self._validate_zone(plan.support, quote.time_ms)
        self._validate_zone(plan.target, quote.time_ms)
        if self.ledger and not self.ledger.settled:
            raise ValueError("previous campaign/orders not settled")
        if self.account_halted or self.locks or not self.reconciled or not self.connected:
            return self.record("wait", "account_not_ready")
        if not quote.execution_ok or not quote.funding_known:
            return self.record("wait", "execution_or_cost_unknown")
        if plan.splits and self.mode != "planned":
            raise ValueError("preplanned splits require planned comparison mode")
        if self._zone_locked(plan.support):
            return self.record("wait", "zone_locked")
        side = plan.side
        entry = quote.entry(side)
        target = plan.target.low if side == 1 else plan.target.high
        if not self._rr(entry, plan.stop, target, side):
            return self.record("wait", "initial_geometry_or_cost")
        total = plan.initial_qty + sum((q for _, q in plan.splits), dec(0))
        all_tranches = ((entry, plan.initial_qty),) + plan.splits
        if any(q != floor_step(q, self.costs.step) or not self.costs.executable(q, p) or
               not self._rr(p, plan.stop, target, side) for p, q in all_tranches):
            return self.record("wait", "invalid_planned_tranche")
        if any(side * (p - entry) >= 0 for p, _ in plan.splits):
            return self.record("wait", "split_not_in_adverse_direction")
        if any(p != floor_step(p, self.costs.tick) or not plan.support.low <= p <= plan.support.high
               for p, _ in plan.splits):
            return self.record("wait", "split_outside_declared_zone_or_tick")
        equity = self.ledger.cash if self.ledger else self.equity
        budget = equity * self.policy.campaign_fraction
        risk = sum((q * self.costs.loss(p, plan.stop, side) for p, q in all_tranches), dec(0))
        if risk > budget or total > min(quote.max_total_qty, quote.margin_room_qty, quote.liquidity_qty):
            return self.record("wait", "initial_plan_capacity")
        if self.ledger:
            self.archives.append(self.snapshot())
            self.archived_ledgers[self.plan.id] = self.ledger
        self.plan, self.support, self.target = plan, plan.support, plan.target
        self.ledger = Ledger(equity, side, self.costs)
        self.budget, self.quote = budget, quote
        self.confirmation = self.target_confirmation = None
        self.target_armed = self.support_armed = True
        self.pending_management = self.recovery_stop = self.buffer = None
        self.target_stalls = 0
        self.reduced_once = self.exit_latched = False
        self.thesis_valid = self.context_known = True
        self.used_plans.add(plan.id)
        self.zone_definitions[plan.support.key] = plan.support
        self._new_order("initial", plan.initial_qty, "independent_entry", limit=entry, stop=plan.stop,
                        event_id=plan.id, zone_key=plan.support.key, expires_ms=plan.expires_ms)
        for index, (price, qty) in enumerate(plan.splits):
            self._new_order("planned", qty, "predeclared_split", limit=price, stop=plan.stop,
                            event_id=f"{plan.id}:split:{index}", zone_key=plan.support.key, expires_ms=plan.expires_ms)
        return self.record("plan_accepted", "full_plan_risk_reserved", plan=jsonable(plan))

    def set_context(self, time_ms, *, thesis_valid, context_known, support=None, target=None, market_view=None):
        self._time(time_ms)
        require_flags(thesis_valid, context_known)
        for zone in (support, target):
            if zone is not None:
                self._validate_zone(zone, time_ms)
        if target and self.target and target.key != self.target.key and self.ledger and self.ledger.quantity:
            if not (self.target_confirmation and self.target_confirmation.state == "confirmed"):
                raise ValueError("target extension requires breakout/retest confirmation")
        self.thesis_valid, self.context_known = thesis_valid, context_known
        if market_view is not None:
            self.market_view = dict(market_view)
        if support is not None:
            self._zone_update(support, time_ms)
            if self.support is None or support.key != self.support.key:
                self._discard_signal("new_zone_version")
                self.confirmation = None
                self.support_armed = True
            self.support = support
        if target is not None:
            self._zone_update(target, time_ms)
            if self.target and target.key != self.target.key:
                self.target_confirmation = None
                self.target_armed = True
                self.reduced_once = False
            self.target = target
        if not thesis_valid:
            self._exit("whole_thesis_invalid")
        elif not context_known or (self.support and not self.support.valid):
            self._discard_signal("context_or_zone_unknown")
            self._cancel_increases("context_or_zone_unknown")
            if self.support and not self.support.valid and self.ledger:
                self._reduce({k: lot.quantity for k, lot in self.ledger.lots.items()
                              if lot.kind == "add" and lot.zone_key.rsplit(":", 1)[0] == self.support.id},
                             "additional_zone_invalid")
        self.record("context", "context_updated")

    def _zone_update(self, zone: Zone, time_ms):
        self._validate_zone(zone, time_ms)
        self.zone_definitions[zone.key] = zone
        lock = self.zone_locks.get(zone.id)
        if lock and zone.version > lock[0] and zone.structural_close_ms is not None:
            stamp = zone.structural_close_ms
            if stamp % 900000 == 0 and lock[1] < stamp <= zone.available_ms <= time_ms:
                del self.zone_locks[zone.id]
                self.loss_streaks[zone.id] = 0
                self.record("unlock", "new_completed_15m_structure", zone=zone.key)

    def _validate_zone(self, zone, time_ms):
        if zone.available_ms > time_ms:
            raise ValueError("future zone")
        for old in (*self.zone_definitions.values(), self.support, self.target):
            if old and old.id == zone.id:
                if zone.version < old.version or (zone.version == old.version and zone != old):
                    raise ValueError("zone version must be immutable/increasing")

    def _zone_locked(self, zone):
        if zone.id in self.zone_locks:
            return True
        # A renamed but overlapping old region cannot evade the loss lock.
        return any(old.id in self.zone_locks and old.low <= zone.high and old.high >= zone.low
                   for old in self.zone_definitions.values())

    def fault(self, time_ms, reason, *, connected=True, protection_ok=True, account_halted=False):
        self._time(time_ms)
        require_flags(connected, protection_ok, account_halted)
        self.connected, self.protection_ok = connected, protection_ok
        self.account_halted = self.account_halted or account_halted
        self.locks.add(reason)
        self.reconciled = False
        self.healthy_bars = 0
        self._discard_signal(reason)
        self._cancel_increases(reason)
        if account_halted or not protection_ok:
            self._exit("account_or_protection_failure")
        self.record("locked", reason, transport_available=connected)

    def reconcile(self, time_ms, *, actual_quantity, orders_match, balance_matches, protection_ok,
                  thesis_restored, gaps_repaired, connected=True):
        self._time(time_ms)
        require_flags(orders_match, balance_matches, protection_ok, thesis_restored, gaps_repaired, connected)
        self.connected, self.protection_ok = connected, protection_ok
        actual = dec(actual_quantity)
        expected = self.ledger.quantity * self.plan.side if self.ledger else dec(0)
        if actual != expected:
            self.authoritative_quantity = actual
            self.locks.add("position_mismatch")
            self.reconciled = False
            self._cancel_increases("position_mismatch")
            self.record("external_action_required", "reconcile_authoritative_position",
                        actual_quantity=actual, reduce_only_quantity=abs(actual),
                        direction_to_close=-1 if actual > 0 else 1 if actual < 0 else 0,
                        transport_available=connected)
            return False
        if not protection_ok:
            self._exit("reconciliation_protection_missing")
        data_fault = bool(self.locks & {"data_gap", "data_late"})
        healthy = not data_fault or (gaps_repaired and self.healthy_bars >= 3)
        unresolved = self.ledger and any(o.status == "cancel_pending" for o in self.ledger.orders.values())
        if not (orders_match and balance_matches and protection_ok and thesis_restored and connected and healthy) or unresolved:
            self.record("wait", "reconciliation_incomplete")
            return False
        self.reconciled = True
        self.authoritative_quantity = None
        self.locks.clear()
        if self.account_halted:
            self.locks.add("account_halted")
        self._discard_signal("reconciled_require_fresh_evidence")
        self.record("reconciled", "position_orders_protection_matched")
        return True

    def cancel_ack(self, order_id, time_ms):
        self._time(time_ms)
        o = self.ledger.orders[order_id]
        if o.status != "filled":
            o.status = "cancelled"
        if self.ledger.settled:
            self.closed_at_ms = time_ms
        self.record("cancel_ack", "terminal_order_state", order_id=order_id)

    def fill(self, fill_id, order_id, quantity, price, fee, time_ms):
        self._time(time_ms)
        if order_id not in self.ledger.orders:
            old = next((a for a in self.archived_ledgers.values() if order_id in a.orders), None)
            if old is None:
                raise ValueError("unknown fill order; reconcile exchange history")
            if old.apply_fill(fill_id, order_id, quantity, price, fee, time_ms):
                self.locks.add("archived_campaign_fill")
                self.authoritative_quantity = old.side * old.quantity + self.plan.side * self.ledger.quantity
                self.reconciled = False
                self._cancel_increases("archived_campaign_fill")
                self.record("external_action_required", "late_fill_from_closed_campaign",
                            old_campaign_quantity=old.side * old.quantity,
                            actual_combined_quantity=old.side * old.quantity + self.plan.side * self.ledger.quantity)
            return
        o = self.ledger.orders[order_id]
        was_cancelled = o.status in ("cancel_pending", "cancelled")
        outcomes = []
        if not o.increasing and fill_id not in self.ledger.seen_fills:
            remaining = dec(quantity)
            for key, requested in o.targets.items():
                lot = self.ledger.lots.get(key)
                if lot is None or not remaining:
                    continue
                part = min(remaining, requested, lot.quantity)
                if lot.kind == "add" and part:
                    net = self.plan.side * part * (dec(price) - lot.entry)
                    net -= lot.allocated_cost * part / lot.quantity + dec(fee) * part / dec(quantity)
                    outcomes.append((lot.event_id, lot.zone_key, net))
                remaining -= part
        changed = self.ledger.apply_fill(fill_id, order_id, quantity, price, fee, time_ms)
        if not changed:
            return
        for event, zone_key, net in outcomes:
            self.event_realized[event] = self.event_realized.get(event, dec(0)) + net
            if any(lot.event_id == event for lot in self.ledger.lots.values()) or event in self.stopped_events:
                continue
            self.stopped_events.add(event)
            zone_id, version = zone_key.rsplit(":", 1)
            if self.event_realized[event] < 0:
                self.loss_streaks[zone_id] = self.loss_streaks.get(zone_id, 0) + 1
                if self.loss_streaks[zone_id] >= 2:
                    self.zone_locks[zone_id] = (int(version), self.last_time)
            else:
                self.loss_streaks[zone_id] = 0
        if was_cancelled and o.increasing:
            self.locks.add("late_fill")
            self.reconciled = False
            self._reduce({o.id: self.ledger.lots[o.id].quantity}, "cancel_race_unwind")
        if self.exit_latched:
            self._exit("exit_latched_late_fill")
        if self.ledger.risk_used() > self.budget:
            self._exit("campaign_risk_breach_after_fill")
        self.record("fill", "actual_fill_applied", fill_id=fill_id,
                    break_evens=self.ledger.break_evens())
        if self.ledger.settled:
            self.closed_at_ms = time_ms

    def funding(self, event_id, amount, time_ms):
        self._time(time_ms)
        if not self.ledger:
            raise ValueError("funding requires campaign")
        self.ledger.funding(event_id, amount, time_ms)
        if self.ledger.risk_used() > self.budget:
            self._exit("campaign_risk_breach_after_funding")
        self.record("funding", "costs_recomputed", break_evens=self.ledger.break_evens())

    def _stop_lots(self, adverse):
        if not self.ledger or not self.ledger.quantity:
            return
        side = self.plan.side
        if side * (adverse - self.plan.stop) <= 0:
            self._exit("common_stop")
            return
        targets = {}
        for key, lot in self.ledger.lots.items():
            if side * (adverse - lot.stop) <= 0:
                targets[key] = lot.quantity
        if targets:
            self._discard_signal("local_stop")
            self._cancel_increases("local_stop")
            self._reduce(targets, "local_stop")

    def on_bar(self, bar):
        self._time(bar.received_ms)
        prior_atr = self.history.atr()
        prior_five = list(self.history.minutes)[-5:]
        three, gap = self.history.push(bar)
        late = bar.received_ms - bar.end_ms > self.policy.late_ms
        if gap or late:
            self.fault(bar.received_ms, "data_gap" if gap else "data_late",
                       connected=self.connected, protection_ok=self.protection_ok)
        else:
            self.healthy_bars += 1
        if not self.ledger or not self.ledger.quantity:
            return self.record("wait", "no_position")
        side = self.plan.side
        self._stop_lots(bar.low if side == 1 else bar.high)
        if self.exit_latched or any(o.active and not o.increasing for o in self.ledger.orders.values()):
            return self.record("wait", "reduction_priority")
        if self._blocked():
            return self.record("wait", "state_not_trustworthy")
        if prior_atr is None or gap or late:
            return self.record("wait", "atr_or_fresh_data_missing")
        buffer = max(2 * self.costs.tick, prior_atr * self.policy.buffer_atr)
        self._manage_target(bar, three, prior_five, buffer)
        if self.pending_management:
            return self.record("wait", "management_before_add")
        if self.mode != "confirmed" or self._zone_locked(self.support) or not self.support.valid:
            return self.record("wait", "add_disabled_or_zone_locked")
        lower, upper = self.support.bounds(side)
        low, high, close = bar.normalized(side)
        terminal = self.confirmation is None or self.confirmation.state in ("failed", "expired", "consumed")
        if terminal and not self.support_armed:
            ended = max(self.rearm_after_ms, self.confirmation.confirmed_ms or self.confirmation.started_ms) if self.confirmation else self.rearm_after_ms
            if three and three.end_ms > ended and three.normalized(side)[2] > upper + buffer:
                self.support_armed = True
                self.confirmation = None
                return self.record("rearmed", "new_favorable_three_minute_close")
        if self.confirmation is None and self.support_armed and low <= upper and high >= lower:
            if self.support.available_ms > bar.end_ms - 60000:
                return self.record("wait", "zone_not_yet_known")
            self.confirmation = Confirmation(self.support, side, buffer, bar.end_ms)
            self.support_armed = False
        if self.confirmation:
            previous = self.confirmation.state
            self.confirmation.advance(bar, three, self.policy)
            if self.confirmation.state != previous:
                self.record("signal", self.confirmation.reason, state=self.confirmation.state)
        return self.record("observe", "completed_bar", evidence=self.evidence())

    def _manage_target(self, bar, three, prior_five, buffer):
        side = self.plan.side
        low, high, close = bar.normalized(side)
        lower, upper = self.target.bounds(side)
        if not self.target_armed:
            if three and three.normalized(side)[2] < lower - buffer:
                self.target_armed = True
            return
        if self.target_confirmation is None and low <= upper and high >= lower:
            if len(prior_five) < 5 or self.target.available_ms > bar.end_ms - 60000:
                return
            self.buffer = buffer
            self.target_confirmation = Confirmation(self.target, side, buffer, bar.end_ms)
            extreme = min(x.normalized(side)[0] for x in prior_five)
            self.recovery_stop = side * max(side * self.plan.stop, extreme - buffer)
            self.target_stalls = 0
        if self.target_confirmation is None:
            return
        b = self.buffer
        rejection = close < lower - b
        if three:
            c3 = three.normalized(side)[2]
            self.target_stalls = self.target_stalls + 1 if lower <= c3 <= upper else 0
        stalled = self.target_stalls >= 2
        if rejection or stalled:
            self.pending_management = "target_rejection" if rejection else "target_stall"
            self._cancel_increases(self.pending_management)
            self._discard_signal(self.pending_management)
            self.record("management", self.pending_management)
            return
        self.target_confirmation.advance(bar, three, self.policy)
        if self.target_confirmation.state == "confirmed":
            self.record("hold", "target_breakout_held")

    def _manage_quantity(self, quote):
        reason = self.pending_management
        if self.reduced_once or not self.thesis_valid or self.recovery_stop is None:
            self.pending_management = None
            self._exit(reason or "residual_thesis_missing")
            return
        # Finish cancelling increases before fixing a residual target.
        if any(o.active and o.increasing for o in self.ledger.orders.values()):
            self._cancel_increases(reason)
            return
        side = self.plan.side
        price = quote.exit(side)
        stop = self.recovery_stop
        if side * (price - stop) <= 0:
            self.pending_management = None
            self._exit("residual_stop_already_crossed")
            return
        adds = {k: lot.quantity for k, lot in self.ledger.lots.items() if lot.kind == "add"}
        if adds:
            self._reduce(adds, "recovery_add_exit")
            return  # Recalculate after actual fills/costs, not estimated cancellation.
        if any(o.active and not o.increasing for o in self.ledger.orders.values()):
            return
        lots = list(self.ledger.lots.values())
        # Never loosen any lot's existing protection.
        for lot in lots:
            lot.stop = side * max(side * lot.stop, side * stop)
        total = self.ledger.quantity
        if not total:
            self.pending_management = None
            return

        def admissible(keep):
            # Uniform allocation gives a monotone linear loss/cost function.
            fraction = keep / total
            projected_used = self.ledger.realized_losses + self.ledger.paid_costs
            future_loss = dec(0)
            for lot in lots:
                retained = lot.quantity * fraction
                closed = lot.quantity - retained
                projected_used += closed * (max(dec(0), side * (lot.entry - price)) + price * self.costs.fee)
                projected_used += retained * self.costs.loss(lot.entry, lot.stop, side, False)
                future_loss += retained * self.costs.loss(price, lot.stop, side, False)
            return projected_used <= self.budget and future_loss <= min(
                self.budget * self.policy.add_fraction,
                max(dec(0), self.budget - projected_used))

        # Bisection over executable steps, bounded even for tiny contract units.
        lo, hi = 0, int(total / self.costs.step)
        if not admissible(dec(0)):
            hi = 0
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if admissible(mid * self.costs.step):
                lo = mid
            else:
                hi = mid - 1
        keep = lo * self.costs.step
        if not self.costs.executable(keep, price):
            keep = dec(0)
        if keep < total and not self.costs.executable(total - keep, price):
            keep = dec(0)  # Whole-position close rather than an unexecutable required cut.
        # Preserve strict limits when rounding individual lots: retained lots down.
        targets = {lot.id: lot.quantity - floor_step(keep * lot.quantity / total, self.costs.step) for lot in lots}
        self._reduce(targets, reason)
        self.pending_management = None
        self.reduced_once = True
        self.target_confirmation = None
        self.target_armed = False
        self.record("residual_plan", reason, stop=stop, target=jsonable(self.target),
                    next_review_ms=self.last_time + 60000, keep_upper_bound=keep)

    def on_quote(self, quote: Quote):
        self._time(quote.time_ms)
        self.quote = quote
        if not self.ledger:
            return self.record("wait", "no_plan")
        self.heartbeat(quote.time_ms)
        for order in self.ledger.orders.values():
            if order.active and order.increasing and order.expires_ms is not None and quote.time_ms >= order.expires_ms:
                order.status = "cancel_pending"
                self.record("cancel_request", "entry_order_expired", order_id=order.id)
            if order.active and order.increasing and self.plan.side * (quote.entry(self.plan.side) - order.stop) <= 0:
                order.status = "cancel_pending"
                self.record("cancel_request", "pending_entry_stop_crossed", order_id=order.id)
                self._discard_signal("pending_entry_stop_crossed")
        if self.ledger.quantity:
            self._stop_lots(quote.exit(self.plan.side))
        if self.ledger.risk_used() > self.budget or self.ledger.quantity > quote.max_total_qty:
            self._exit("risk_or_exposure_limit")
        if self.exit_latched:
            self._exit("exit_in_progress")
            return
        if not quote.execution_ok or not quote.funding_known:
            self._cancel_increases("execution_or_funding_unknown")
            self._discard_signal("execution_or_funding_unknown")
            return self.record("wait", "execution_or_funding_unknown")
        if self.pending_management:
            self._manage_quantity(quote)
            return
        if self._blocked() or any(o.active for o in self.ledger.orders.values()):
            return self.record("wait", "reconcile_or_pending_order")
        c = self.confirmation
        if self.mode != "confirmed" or not c or c.state != "confirmed" or not self.ledger.quantity:
            return self.record("wait", "no_new_confirmation")
        if quote.time_ms <= c.confirmed_ms:
            return self.record("wait", "quote_not_after_confirmation")
        c.state = "consumed"  # One first executable quote evaluation per evidence event.
        if quote.time_ms >= c.recovery_ms + self.policy.confirmation_ms:
            return self.record("wait", "confirmation_expired_before_quote")
        if len(self.ledger.add_events) >= self.policy.max_adds or self._zone_locked(self.support):
            return self.record("wait", "add_count_or_zone_lock")
        side = self.plan.side
        entry = quote.entry(side)
        if side * (entry - self.ledger.average) >= 0:
            return self.record("wait", "not_adverse_position")
        stop = side * max(side * self.plan.stop, c.retest.normalized(side)[0] - c.buffer)
        target = self.target.low if side == 1 else self.target.high
        if not self._rr(entry, stop, target, side):
            return self.record("wait", "additional_trade_geometry_or_cost")
        available = max(dec(0), self.budget - self.ledger.risk_used())
        risk_cap = min(available, self.budget * self.policy.add_fraction)
        unit = self.costs.loss(entry, stop, side)
        qty = floor_step(min(risk_cap / unit, quote.margin_room_qty, quote.liquidity_qty,
                             max(dec(0), quote.max_total_qty - self.ledger.quantity)), self.costs.step)
        if not self.costs.executable(qty, entry):
            return self.record("wait", "additional_size_below_minimum")
        event = f"{self.plan.id}:{c.zone.key}:{c.started_ms}:{c.confirmed_ms}"
        return self._new_order("add", qty, "confirmed_adverse_add", limit=entry, stop=stop,
                               event_id=event, zone_key=c.zone.key,
                               expires_ms=c.recovery_ms + self.policy.confirmation_ms)

    def heartbeat(self, time_ms):
        self._time(time_ms)
        end = self.history.last_end
        if end is not None and time_ms > end + 60000 + self.policy.late_ms:
            self.fault(time_ms, "data_late", connected=self.connected, protection_ok=self.protection_ok)

    def snapshot(self):
        ledger = self.ledger
        return jsonable(dict(schema=1, evidence_kind="SYNTHETIC_OR_OFFLINE_REPLAY", mode=self.mode,
                             time_ms=self.last_time, plan=self.plan, policy=self.policy,
                             budget=self.budget, locks=sorted(self.locks), account_halted=self.account_halted,
                             quantity=ledger.quantity if ledger else dec(0),
                             cash=ledger.cash if ledger else self.equity,
                             risk_used=ledger.risk_used() if ledger else dec(0),
                             break_evens=ledger.break_evens() if ledger else None,
                             break_even_near=self.break_even_near(),
                             lots=ledger.lots if ledger else {}, orders=ledger.orders if ledger else {},
                             add_events=sorted(ledger.add_events) if ledger else [],
                             zone_locks=self.zone_locks, settled=ledger.settled if ledger else True,
                             market_view=self.market_view,
                             authoritative_quantity=self.authoritative_quantity,
                             live_orders_sent=0))

    def break_even_near(self):
        if not self.ledger or not self.quote or not self.ledger.quantity:
            return {"position": None, "campaign": None}
        atr = self.history.atr()
        width = self.buffer or (self.confirmation.buffer if self.confirmation else None)
        if width is None and atr is not None:
            width = max(2 * self.costs.tick, atr * self.policy.buffer_atr)
        price = self.quote.exit(self.plan.side)
        return {key: abs(price - value) <= width if value is not None and width is not None else None
                for key, value in self.ledger.break_evens().items()}
