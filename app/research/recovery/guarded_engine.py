"""Opt-in offline engine: evidence is mandatory for each initial order intent.

No broker transport. Quote-driven increases stay disabled. Each purpose uses
its own submission API; reductions and protection remain available.
"""
from dataclasses import dataclass, replace
from .engine import RecoveryEngine
from .entry_assessment import AdmissionPolicy, Reachability, assess_entry
from .evidence import Evidence, TargetEvidence
from .models import jsonable, dec, floor_step, require_flags
from .zone_observer import ZoneObserver
from .exit_execution import ExitExecution
from .add_admission import AddSubmission, ReentrySubmission, ProfitAddSubmission
from .split_admission import SplitSubmission


@dataclass(frozen=True)
class EntrySubmission:
    support: ZoneObserver
    target: ZoneObserver
    contract: TargetEvidence | None
    reach: Reachability | None
    policy: AdmissionPolicy
    context_evidence: Evidence
    market_side: int | None
    trade_type: str
    conflict: bool
    conflict_resolution: str
    countertrend_reason: str
    thesis_valid: bool
    execution: ExitExecution | None = None
    preplanned: bool = False


class GuardedRecoveryEngine(RecoveryEngine):
    def __init__(self, equity, costs, policy=None):
        super().__init__(equity, costs, policy, mode="no_add")
        self.execution = None
        self.reaction_seen = False
        self.residual_armed = False
        self.execution_exit_reason = None
        self.first_response_price = None
        self.response_goal = dec(0)
        self.response_closed = dec(0)
        self._admitted_add = False
        self.reentry_sources = {}
        self.continuation_levels = {}
        self.split_slots = []
        self.split_budget_cap = dec(0)
        self._admitted_split = False

    def unsubmitted_split_risk(self):
        if not self.plan:
            return dec(0)
        return sum((slot["qty"]*self.costs.loss(slot["price"], self.plan.stop, self.plan.side)
                    for slot in self.split_slots if not slot["released"] and slot["order_id"] is None), dec(0))

    def _release_split_reservations(self, reason):
        indices = []
        for i, slot in enumerate(self.split_slots):
            if not slot["released"] and slot["order_id"] is None:
                slot["released"] = True
                indices.append(i)
        if indices:
            self.record("split_reservations_released", reason, indices=indices)

    def _exit(self, reason):
        self._release_split_reservations(reason)
        return super()._exit(reason)

    def _cancel_increases(self, reason):
        if reason == "first_response_reached":
            self._release_split_reservations(reason)
        return super()._cancel_increases(reason)

    def _time(self, time_ms):
        super()._time(time_ms)
        if self.split_slots and self.plan.expires_ms is not None and time_ms >= self.plan.expires_ms:
            self._release_split_reservations("preplanned_deadline")
            self._cancel_increases("preplanned_deadline")
        rules = self.execution
        if rules is None or self.ledger is None or self.ledger.settled:
            return
        reason = ("holding_deadline" if time_ms >= rules.exit_by_ms else
                  "reaction_deadline" if time_ms >= rules.reaction_by_ms and not self.reaction_seen else None)
        if reason and self.execution_exit_reason is None:
            self.execution_exit_reason = reason
            self.record("execution_exit", reason)
        if self.execution_exit_reason:
            self._exit(self.execution_exit_reason)

    def start(self, plan, quote, *, submission=None):
        self._time(quote.time_ms)
        if submission is not None and not isinstance(submission, EntrySubmission):
            raise ValueError("typed entry submission required")
        if submission is not None:
            require_flags(submission.preplanned)
        blocked = []
        if submission is None:
            blocked.append("entry_submission_required")
        elif submission.execution is None:
            blocked.append("executable_exit_rules_required")
        # There is no reusable READY token. Rebuild evidence at a later decision.
        if plan.created_ms != quote.time_ms:
            blocked.append("fresh_submission_at_quote_time_required")
        if self.mode != "no_add" or (plan.splits and not (submission and submission.preplanned)):
            blocked.append("guarded_increases_not_implemented")
        if submission and submission.preplanned:
            if not plan.splits:
                blocked.append("preplanned_tranches_required")
            if any(not plan.support.low <= price <= plan.support.high for price, _ in plan.splits):
                blocked.append("split_outside_declared_zone")
        if (self.account_halted or self.locks or not self.connected or not self.reconciled
                or not self.protection_ok or not self.context_known or not self.thesis_valid):
            blocked.append("current_engine_state_blocks_entry")
        if self.ledger and not self.ledger.settled:
            blocked.append("previous_campaign_unsettled")
        if submission is not None and submission.contract is not None:
            boundary = plan.target.low if plan.side == 1 else plan.target.high
            if (submission.contract.first_response_price != boundary
                    and (submission.execution is None or submission.execution.first_response_qty is None)):
                blocked.append("first_response_execution_plan_required")
            rules = submission.execution
            if rules is not None:
                if not isinstance(rules, ExitExecution):
                    raise ValueError("typed exit rules required")
                contract = submission.contract
                if (rules.reaction_by_ms != contract.reaction_by_ms or rules.exit_by_ms != contract.expected_by_ms
                        or not plan.created_ms < rules.reaction_by_ms):
                    blocked.append("execution_deadlines_mismatch")
                if not (0 < plan.side*(rules.reaction_price-contract.reference_price)
                        <= plan.side*(contract.first_response_price-contract.reference_price)):
                    blocked.append("invalid_reaction_price")
                if not (plan.side*(rules.residual_stop-plan.stop) >= 0
                        and plan.side*(quote.entry(plan.side)-rules.residual_stop) > 0):
                    blocked.append("invalid_residual_stop")
                q = rules.first_response_qty
                if q is not None and (q > plan.initial_qty or floor_step(q, self.costs.step) != q
                        or not self.costs.executable(q, contract.first_response_price)):
                    blocked.append("invalid_first_response_quantity")
        if blocked:
            return self.record("entry_rejected", "guarded_entry_blocked", reasons=blocked,
                               candidate_plan_id=plan.id, order_authorized=False)
        # Current cash and engine policy cap the submitted research budget.
        equity = self.ledger.cash if self.ledger else self.equity
        effective_policy = replace(submission.policy,
            loss_budget=min(submission.policy.loss_budget, equity*self.policy.campaign_fraction),
            minimum_rr=max(submission.policy.minimum_rr, self.policy.minimum_rr))
        result = assess_entry(plan, submission.support, submission.target,
            submission.contract, submission.reach, quote, self.costs, effective_policy,
            context_evidence=submission.context_evidence, market_side=submission.market_side,
            trade_type=submission.trade_type, conflict=submission.conflict,
            conflict_resolution=submission.conflict_resolution,
            countertrend_reason=submission.countertrend_reason, thesis_valid=submission.thesis_valid)
        self.record("entry_assessment", "fresh_evidence_assessed", candidate_plan_id=plan.id,
                    assessment=result, plan=jsonable(plan), quote=jsonable(quote),
                    submission=jsonable(submission), effective_policy=jsonable(effective_policy))
        if result["status"] != "READY":
            return self.record("entry_rejected", "admission_not_ready", candidate_plan_id=plan.id,
                               assessment=result, order_authorized=False)
        # Synchronous local intent generation: base engine independently applies
        # zone locks, expiry, used IDs, fresh campaign and executable-size checks.
        initial_plan = replace(plan, splits=()) if plan.splits else plan
        result = super().start(initial_plan, quote)
        if result["action"] == "plan_accepted":
            self.plan = plan
            self.split_slots = [dict(price=p, qty=q, order_id=None, released=False) for p,q in plan.splits]
            self.split_budget_cap = effective_policy.loss_budget
            self.execution = submission.execution
            self.reaction_seen = self.residual_armed = False
            self.execution_exit_reason = None
            self.first_response_price = submission.contract.first_response_price
            self.response_goal = self.response_closed = dec(0)
            self.reentry_sources = {}
            self.record("execution_rules", "exit_rules_bound", execution=jsonable(self.execution))
            if self.split_slots:
                self.record("split_plan_frozen", "all_tranches_reserved_before_entry", plan=jsonable(plan),
                            unsubmitted_risk=self.unsubmitted_split_risk())
        return result

    def submit_split(self, quote, submission):
        if not isinstance(submission, SplitSubmission):
            raise ValueError("typed split submission required")
        self.on_quote(quote)
        reasons = []
        if (not self.plan or submission.plan_id != self.plan.id or submission.decision_ms != quote.time_ms
                or submission.context.recorded_ms > quote.time_ms):
            reasons.append("split_time_or_campaign_mismatch")
        slot = self.split_slots[submission.index] if submission.index < len(self.split_slots) else None
        if slot is None or slot["released"] or slot["order_id"] is not None:
            reasons.append("split_not_available")
        if (not self.ledger or not self.ledger.quantity or self._blocked() or not quote.execution_ok
                or not quote.funding_known or self.response_goal or self.residual_armed):
            reasons.append("split_state_blocked")
        if self.ledger and any(o.active for o in self.ledger.orders.values()):
            reasons.append("orders_unsettled")
        if not (submission.thesis_valid and submission.context_known and submission.conflicts_resolved and submission.reason.strip()):
            reasons.append("split_thesis_incomplete")
        for role, observer, zone in (("support",submission.support,self.plan.support if self.plan else None),
                                     ("target",submission.target,self.plan.target if self.plan else None)):
            expected_side = (self.plan.side if role == "support" else -self.plan.side) if self.plan else 0
            if (observer.history.zone != zone or observer.side != expected_side
                    or observer.history.as_of(quote.time_ms)["state"] != "valid"
                    or observer.last_bar is None or not self.history.minutes
                    or observer.last_bar != self.history.minutes[-1]
                    or observer.last_bar.end_ms != quote.time_ms//60000*60000
                    or observer.last_bar.received_ms > quote.time_ms):
                reasons.append(f"{role}:original_current_valid_zone_required")
        if self.plan and (self.support != self.plan.support or self.target != self.plan.target
                          or self._zone_locked(self.support)):
            reasons.append("original_split_basis_changed")
        if reasons:
            return self.record("split_rejected", "preplanned_admission_blocked", reasons=reasons,
                               submission=jsonable(submission))
        price, qty = slot["price"], slot["qty"]
        side = self.plan.side
        if side*(quote.entry(side)-price) > 0 or side*(quote.entry(side)-self.plan.stop) <= 0:
            return self.record("split_rejected", "outside_predeclared_execution_price")
        committed = self.ledger.risk_used()+self.unsubmitted_split_risk()
        if committed > min(self.budget,self.split_budget_cap):
            return self.record("split_rejected", "reserved_plan_loss_budget_exceeded")
        if qty > min(quote.margin_room_qty,quote.liquidity_qty,max(dec(0),quote.max_total_qty-self.ledger.quantity)):
            return self.record("split_rejected", "current_split_capacity_insufficient")
        if not self.costs.executable(qty, quote.entry(side)) or not self._rr(price,self.plan.stop,self.first_response_price,side):
            return self.record("split_rejected", "split_cost_or_minimum")
        self.record("split_assessment", "predeclared_tranche_rechecked", submission=jsonable(submission),
                    total_committed_loss=committed, price=price, quantity_to_add=qty)
        self._admitted_split = True
        try:
            order = self._new_order("planned",qty,"guarded_planned_completion",limit=price,stop=self.plan.stop,
                event_id=f"{self.plan.id}:split:{submission.index}",zone_key=self.plan.support.key,
                expires_ms=min(self.plan.expires_ms,self.execution.exit_by_ms))
            slot["order_id"] = order.id
            return order
        finally:
            self._admitted_split = False

    def on_bar(self, bar):
        # Observe the existing 3m recovery + later 1m retest/hold sequence,
        # but keep automatic quote-driven increases disabled.
        self.mode = "confirmed"
        try:
            result = super().on_bar(bar)
        finally:
            self.mode = "no_add"
        if (self.execution and self.ledger and self.ledger.quantity and not self.exit_latched
                and not self._blocked() and not self.reaction_seen and bar.received_ms < self.execution.reaction_by_ms
                and bar.end_ms > self.plan.created_ms
                and any(r["type"] == "fill" and r["kind"] == "initial" and r["time_ms"] <= bar.end_ms
                        for r in self.ledger.rows)
                and self.plan.side*(bar.close-self.execution.reaction_price) >= 0):
            self.reaction_seen = True
            self.record("execution_progress", "completed_close_reaction_confirmed", bar_end_ms=bar.end_ms)
        if (self.execution and self.residual_armed and self.ledger and self.ledger.quantity
                and self.plan.side*(bar.close-self.execution.residual_stop) <= 0):
            self.execution_exit_reason = "residual_stop"
            self._exit("residual_stop")
        return result

    def submit_add(self, quote, submission):
        if type(submission) is not AddSubmission:
            raise ValueError("adverse-add submission required; reentry has its own API")
        return self._submit_increase(quote, submission, reentry=False)

    def submit_reentry(self, quote, submission):
        if not isinstance(submission, ReentrySubmission):
            raise ValueError("typed reentry submission required")
        return self._submit_increase(quote, submission, reentry=True)

    def register_continuation_level(self, zone, time_ms):
        self._time(time_ms)
        self._validate_zone(zone, time_ms)
        if not zone.valid or zone.key in self.continuation_levels:
            raise ValueError("valid new continuation-zone version required")
        self.continuation_levels[zone.key] = (zone, time_ms)
        self.zone_definitions[zone.key] = zone
        return self.record("continuation_level", "prior_zone_registered", zone=jsonable(zone))

    def submit_profit_add(self, quote, submission):
        if not isinstance(submission, ProfitAddSubmission):
            raise ValueError("typed profit-add submission required")
        return self._submit_increase(quote, submission, reentry=False, profit=True)

    def _submit_increase(self, quote, submission, *, reentry, profit=False):
        # Stops, timeouts, pending management and first-response reductions win.
        self.on_quote(quote)
        reasons = []
        c = self.confirmation
        if not self.plan or not self.ledger or not self.ledger.quantity:
            reasons.append("no_held_campaign")
        if (not self.plan or submission.plan_id != self.plan.id or submission.decision_ms != quote.time_ms
                or submission.context.recorded_ms > quote.time_ms):
            reasons.append("submission_time_or_campaign_mismatch")
        if (not submission.thesis_valid or not submission.context_known or not submission.conflicts_resolved
                or not submission.independent_reason.strip()):
            reasons.append("additional_thesis_incomplete")
        if self._blocked() or not quote.execution_ok or not quote.funding_known:
            reasons.append("execution_or_account_blocked")
        if self.ledger and any(o.active for o in self.ledger.orders.values()):
            reasons.append("orders_unsettled")
        if self.unsubmitted_split_risk():
            reasons.append("preplanned_reservations_must_finish_or_expire")
        if not reentry and (self.response_goal or self.residual_armed or self.reduced_once):
            reasons.append("reentry_after_reduction_requires_separate_contract")
        credit = submission.maximum_qty
        if profit:
            registered = self.continuation_levels.get(submission.prior_resistance_key)
            breakout = next((b for b in self.history.minutes if b.end_ms == submission.breakout_end_ms), None)
            previous = next((b for b in self.history.minutes if b.end_ms == submission.breakout_end_ms-60000), None)
            if registered is None or breakout is None or previous is None or self.plan is None or self.support is None:
                reasons.append("registered_breakout_history_required")
            else:
                prior, registered_ms = registered
                side = self.plan.side
                edge = prior.high if side == 1 else prior.low
                if (registered_ms > breakout.end_ms-60000 or prior.available_ms > breakout.end_ms-60000
                        or breakout.received_ms > quote.time_ms or side*(breakout.close-edge) <= 0
                        or side*(previous.close-edge) > 0):
                    reasons.append("prior_zone_or_completed_breakout_invalid")
                if (self.support.id != prior.id or self.support.version <= prior.version
                        or (self.support.low,self.support.high) != (prior.low,prior.high)
                        or self.support.available_ms < breakout.received_ms):
                    reasons.append("new_support_must_bind_broken_resistance")
                if not c or c.started_ms <= breakout.end_ms:
                    reasons.append("independent_retest_after_breakout_required")
        if reentry:
            rows = self.ledger.rows if self.ledger else []
            reductions = [r for r in rows if r["type"] == "fill" and r["kind"] == "reduce"]
            source = next((r for r in reductions if r["fill_id"] == submission.reduction_fill_id
                           and r["reason"] == "first_response"), None)
            if source is None or not self.residual_armed or not self.execution.first_response_qty:
                reasons.append("first_response_fill_required")
                credit = dec(0)
            else:
                restored = sum((o.filled + (o.remaining if o.active else dec(0))
                                for oid, o in self.ledger.orders.items()
                                if self.reentry_sources.get(oid) == source["fill_id"]), dec(0))
                credit = max(dec(0), source["qty"]-restored)
                if not credit:
                    reasons.append("reduction_credit_consumed")
                if not c or c.started_ms <= max(r["time_ms"] for r in reductions):
                    reasons.append("new_confirmation_after_reduction_required")
                if self.response_closed < self.response_goal:
                    reasons.append("first_response_not_completed")
        if (not c or c.state != "confirmed" or c.retest is None or c.confirmed_ms != submission.confirmed_ms
                or quote.time_ms <= submission.confirmed_ms):
            reasons.append("live_confirmation_required")
        for label, observer, expected, side in (
                ("support", submission.support, self.support, self.plan.side if self.plan else 0),
                ("target", submission.target, self.target, -self.plan.side if self.plan else 0)):
            bar = observer.last_bar
            if (observer.history.zone != expected or observer.side != side
                    or observer.history.as_of(quote.time_ms)["state"] != "valid"
                    or bar is None or bar.end_ms != quote.time_ms//60000*60000
                    or bar.received_ms > quote.time_ms
                    or not self.history.minutes or bar != self.history.minutes[-1]):
                reasons.append(f"{label}:fresh_valid_observation_required")
        if c and c.recovery_ms is not None and quote.time_ms >= c.recovery_ms+self.policy.confirmation_ms:
            reasons.append("confirmation_expired")
        if c and c.zone != self.support:
            reasons.append("confirmation_zone_changed")
        if self.ledger and (len(self.ledger.add_events) >= self.policy.max_adds or self._zone_locked(self.support)):
            reasons.append("add_count_or_zone_lock")
        if reasons:
            return self.record("add_rejected", "additional_admission_blocked", reasons=reasons,
                               submission=jsonable(submission))
        side = self.plan.side
        entry = quote.entry(side)
        if profit:
            out = quote.exit(side)
            net = sum((lot.quantity*(side*(out-lot.entry)-out*self.costs.fee)-lot.allocated_cost
                       for lot in self.ledger.lots.values()), dec(0))
            if net <= 0:
                return self.record("add_rejected", "remaining_position_not_profitable_after_cost")
        if not reentry and not profit and side*(entry-self.ledger.average) >= 0:
            return self.record("add_rejected", "not_adverse_position")
        stop = side*max(side*self.plan.stop, c.retest.normalized(side)[0]-c.buffer)
        if reentry:
            stop = side*max(side*stop, side*self.execution.residual_stop)
        target = self.first_response_price
        if not self._rr(entry, stop, target, side):
            return self.record("add_rejected", "additional_trade_geometry_or_cost")
        available = max(dec(0), self.budget-self.ledger.risk_used())
        cap = min(available, self.budget*self.policy.add_fraction, submission.maximum_loss)
        unit = self.costs.loss(entry, stop, side)
        qty = floor_step(min(cap/unit, submission.maximum_qty, credit, quote.margin_room_qty, quote.liquidity_qty,
                             max(dec(0), quote.max_total_qty-self.ledger.quantity)), self.costs.step)
        if not self.costs.executable(qty, entry):
            return self.record("add_rejected", "additional_size_below_minimum")
        self.record("add_assessment", "additional_risk_reserved", submission=jsonable(submission),
                    quantity_to_add=qty, additional_loss=qty*unit,
                    total_loss_after_add=self.ledger.risk_used()+qty*unit, stop=stop)
        event = f"{self.plan.id}:{c.zone.key}:{c.started_ms}:{c.confirmed_ms}"
        expiry = min(c.recovery_ms+self.policy.confirmation_ms, self.execution.exit_by_ms)
        c.state = "consumed"
        self._admitted_add = True
        try:
            reason = "guarded_profit_add" if profit else "guarded_reentry" if reentry else "guarded_adverse_add"
            order = self._new_order("add", qty, reason, limit=entry, stop=stop,
                event_id=event, zone_key=c.zone.key, expires_ms=expiry)
            if reentry:
                self.reentry_sources[order.id] = submission.reduction_fill_id
            return order
        finally:
            self._admitted_add = False

    def on_quote(self, quote):
        result = super().on_quote(quote)
        if (self.execution and self.residual_armed and self.ledger and self.ledger.quantity
                and self.plan.side*(quote.exit(self.plan.side)-self.execution.residual_stop) <= 0):
            self.execution_exit_reason = "residual_stop"
            self._exit("residual_stop")
        self._first_response(quote)
        return result

    def _manage_target(self, bar, three, prior_five, buffer):
        # A declared first response replaces the legacy target-rejection sizing.
        # Residual risk stays governed by its stop, invalidation and hard deadline.
        if self.execution and self.execution.first_response_qty is not None:
            return
        return super()._manage_target(bar, three, prior_five, buffer)

    def _first_response(self, quote):
        if (not self.execution or self.execution.first_response_qty is None
                or not self.ledger or not self.ledger.quantity or self._blocked()
                or not quote.execution_ok or not quote.funding_known):
            return
        price = quote.exit(self.plan.side)
        if not self.response_goal:
            if self.plan.side*(price-self.first_response_price) < 0:
                return
            # Decide from actual filled quantity; never sell unfilled entry units.
            goal = min(self.execution.first_response_qty, self.ledger.quantity)
            rest = self.ledger.quantity-goal
            if (rest and not self.costs.executable(rest, price)) or not self.costs.executable(goal, price):
                goal = self.ledger.quantity  # explicit close-position dust fallback
            self.response_goal = goal
            self._cancel_increases("first_response_reached")
            self.record("execution_progress", "first_response_latched", quantity_to_close=goal)
        reserved = sum((o.remaining for o in self.ledger.orders.values()
                        if o.active and o.reason == "first_response"), dec(0))
        remaining = min(self.ledger.quantity, max(dec(0), self.response_goal-self.response_closed-reserved))
        if not remaining:
            return
        targets = {}
        for key, lot in self.ledger.lots.items():
            reserved_lot = sum((o.targets.get(key, dec(0)) for o in self.ledger.orders.values()
                                if o.active and not o.increasing), dec(0))
            part = min(remaining, max(dec(0), lot.quantity-reserved_lot))
            if part:
                targets[key] = part
                remaining -= part
        if targets:
            self._reduce(targets, "first_response")

    def fill(self, fill_id, order_id, quantity, price, fee, time_ms):
        previous = self.ledger.quantity if self.ledger else 0
        reentry_first = (self.ledger and fill_id not in self.ledger.seen_fills
                         and order_id in self.reentry_sources and not self.ledger.orders[order_id].filled)
        counted = (self.ledger and fill_id not in self.ledger.seen_fills
                   and order_id in self.ledger.orders and self.ledger.orders[order_id].reason == "first_response")
        result = super().fill(fill_id, order_id, quantity, price, fee, time_ms)
        if counted:
            self.response_closed += max(dec(0), previous-self.ledger.quantity)
        if reentry_first:
            self.response_goal = self.response_closed = dec(0)
            self.record("execution_progress", "reentry_fill_rearmed_first_response")
        if self.execution and self.ledger and 0 < self.ledger.quantity < previous:
            self.residual_armed = True
            self._discard_signal("reduction_requires_new_confirmation")
            self.record("execution_progress", "partial_fill_armed_residual_stop")
            if self.plan.side*(dec(price)-self.execution.residual_stop) <= 0:
                self.execution_exit_reason = "residual_stop"
                self._exit("residual_stop")
        if self.ledger and self.ledger.settled:
            self._release_split_reservations("campaign_settled")
        return result

    def cancel_ack(self, order_id, time_ms):
        result = super().cancel_ack(order_id, time_ms)
        if self.ledger and self.ledger.settled:
            self._release_split_reservations("campaign_settled")
        return result

    def snapshot(self):
        result = super().snapshot()
        result["guarded_execution"] = jsonable(dict(rules=self.execution, reaction_seen=self.reaction_seen,
            residual_armed=self.residual_armed, exit_reason=self.execution_exit_reason,
            first_response_price=self.first_response_price, response_goal=self.response_goal,
            response_closed=self.response_closed))
        result["guarded_add"] = jsonable(dict(admission_mode="explicit_increase_contracts",
                                              confirmation=self.confirmation, reentry_sources=self.reentry_sources,
                                              continuation_levels=self.continuation_levels))
        result["guarded_splits"] = jsonable(dict(slots=self.split_slots, budget_cap=self.split_budget_cap,
            unsubmitted_risk=self.unsubmitted_split_risk(), total_committed_loss=(self.ledger.risk_used() if self.ledger else dec(0))+self.unsubmitted_split_risk()))
        return result

    def _new_order(self, kind, qty, reason, **kwargs):
        # Defense against changing mode or triggering an inherited increase path.
        if kind not in {"initial", "reduce"} and not (kind == "add" and self._admitted_add) and not (kind == "planned" and self._admitted_split):
            raise ValueError("additional intents require explicit submit_add admission")
        return super()._new_order(kind, qty, reason, **kwargs)
