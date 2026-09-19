"""Offline admission evidence; never submits orders."""
from dataclasses import dataclass
from decimal import Decimal
from .evidence import TargetEvidence, assess_evidence, timestamp
from .models import dec, positive, floor_step


@dataclass(frozen=True)
class Reachability:
    target: TargetEvidence
    window_start_ms: int
    source: str
    excursions: tuple[Decimal, ...]

    def __post_init__(self):
        timestamp(self.window_start_ms)
        values = tuple(dec(x) for x in self.excursions)
        object.__setattr__(self, "excursions", values)
        duration = self.target.expected_by_ms-self.target.decision_ms
        if not self.source.strip() or any(x < 0 for x in values):
            raise ValueError("invalid reachability source or excursions")
        if self.window_start_ms >= self.target.decision_ms or len(values) != (self.target.decision_ms-self.window_start_ms)//duration:
            raise ValueError("sample count does not match horizon and lookback")

    @property
    def reached_fraction(self):
        if not self.excursions:
            return None
        t = self.target
        distance = t.side * (t.first_response_price-t.reference_price) / t.reference_price
        return dec(sum(x >= distance for x in self.excursions)) / len(self.excursions)


def measure_reachability(target, bars, *, source, lookback_minutes):
    """Disjoint full horizons: historical favorable excursions, not win odds.

    Only bars closed AND received by decision time may enter the statistic.
    This ignores stop/target ordering and does not model fills or returns.
    """
    if type(lookback_minutes) is not int or lookback_minutes < 1 or not source.strip():
        raise ValueError("explicit source and positive lookback required")
    duration = target.expected_by_ms - target.decision_ms
    if duration % 60000:
        raise ValueError("horizons must be minute aligned")
    horizon = duration // 60000
    # Decisions may arrive between minute boundaries. Use only the latest
    # fully closed minute; never backdate the decision or include a partial bar.
    end = target.decision_ms // 60000 * 60000
    start = end - lookback_minutes * 60000
    timestamp(start)
    selected = [b for b in bars if start < b.end_ms <= end and b.received_ms <= target.decision_ms]
    if [b.end_ms for b in selected] != list(range(start+60000, end+1, 60000)):
        raise ValueError("complete ordered, received lookback required")
    selected = selected[len(selected) % horizon:]
    excursions = []
    for i in range(0, len(selected), horizon):
        block = selected[i:i+horizon]
        opening = block[0].open
        extreme = max(b.high for b in block) if target.side == 1 else min(b.low for b in block)
        excursions.append(max(dec(0), target.side * (extreme-opening) / opening))
    return Reachability(target, start, source, tuple(excursions))


@dataclass(frozen=True)
class AdmissionPolicy:
    minimum_samples: int
    minimum_reached_fraction: Decimal
    minimum_rr: Decimal
    loss_budget: Decimal
    maximum_quote_age_ms: int

    def __post_init__(self):
        if type(self.minimum_samples) is not int or self.minimum_samples < 1:
            raise ValueError("explicit positive sample minimum required")
        object.__setattr__(self, "minimum_reached_fraction", dec(self.minimum_reached_fraction))
        if not 0 <= self.minimum_reached_fraction <= 1:
            raise ValueError("invalid sample fraction")
        for name in ("minimum_rr", "loss_budget"):
            object.__setattr__(self, name, positive(getattr(self, name)))
        timestamp(self.maximum_quote_age_ms)


def assess_entry(plan, support, target, contract, reach, quote, costs, policy, *,
                 context_evidence, market_side, trade_type, conflict,
                 conflict_resolution, countertrend_reason, thesis_valid):
    """Combine explicit research inputs; READY still never authorizes an order."""
    from .models import require_flags
    require_flags(conflict, thesis_valid)
    if market_side is not None and (type(market_side) is not int or market_side not in (-1, 0, 1)):
        raise ValueError("invalid market side")
    if trade_type not in {"trend", "range", "breakout_retest", "countertrend"}:
        raise ValueError("explicit trade type required")
    now = plan.created_ms
    timestamp(now)
    if plan.support != support.history.zone or plan.target != target.history.zone:
        raise ValueError("plan must bind exact observed zone versions")
    if support.side != plan.side or target.side != -plan.side:
        raise ValueError("zone roles disagree with plan")
    if context_evidence.recorded_ms > now:
        raise ValueError("future context evidence")
    if contract is not None and contract.side != plan.side:
        raise ValueError("target side mismatch")
    if reach is not None and reach.target != contract:
        raise ValueError("reachability belongs to another contract")
    if support.last_bar != target.last_bar:
        raise ValueError("zone observers must use the same market stream")
    if contract is not None and support.last_bar is not None and contract.reference_price != support.last_bar.close:
        raise ValueError("target reference must match last observed close")
    evidence = assess_evidence(support.history, target.history, contract, now)
    blocked, invalid, missing, conflicts, rejected = [], [], list(evidence["reasons"]), [], []
    for label, observer in (("support", support), ("target", target)):
        b = observer.last_bar
        if b is None or b.end_ms != now // 60000 * 60000 or b.received_ms > now:
            blocked.append(f"{label}:observation_not_current")
    if quote.time_ms > now or now-quote.time_ms > policy.maximum_quote_age_ms:
        blocked.append("quote_not_current")
    if not quote.execution_ok or not quote.funding_known:
        blocked.append("execution_or_funding_unknown")
    if evidence["status"] == "INVALIDATED" or not thesis_valid:
        invalid.append("thesis_or_zone_invalidated")
    if market_side is None:
        missing.append("market_context_unknown")
    if conflict and not conflict_resolution.strip():
        conflicts.append("unresolved_context_conflict")
    opposite = market_side == -plan.side
    if opposite and trade_type != "countertrend":
        conflicts.append("countertrend_type_required")
    if (opposite or trade_type == "countertrend") and not countertrend_reason.strip():
        missing.append("countertrend_independent_reason")
    if reach is None:
        missing.append("horizon_evidence_missing")
    elif len(reach.excursions) < policy.minimum_samples:
        missing.append("insufficient_horizon_samples")
    elif reach.reached_fraction < policy.minimum_reached_fraction:
        rejected.append("horizon_sample_criterion_not_met")
    entry = quote.entry(plan.side)
    orders = ((entry, plan.initial_qty),) + plan.splits
    qty = sum((q for _, q in orders), dec(0))
    risk = sum((costs.loss(p, plan.stop, plan.side)*q for p, q in orders), dec(0))
    if risk > policy.loss_budget:
        rejected.append("planned_loss_budget_exceeded")
    if qty > min(quote.max_total_qty, quote.margin_room_qty, quote.liquidity_qty):
        blocked.append("capacity_insufficient_for_plan")
    for i, (p, q) in enumerate(orders):
        if plan.side * (p-plan.stop) <= 0:
            rejected.append(f"order:{i}:invalid_stop")
        if not costs.executable(q, p) or floor_step(q, costs.step) != q:
            rejected.append(f"order:{i}:invalid_quantity")
        if i and (floor_step(p, costs.tick) != p or plan.side*(p-entry) >= 0):
            rejected.append(f"order:{i}:invalid_adverse_split")
        if contract is not None:
            out = costs.exit_price(contract.first_response_price, plan.side)
            reward = plan.side*(out-p) - (p+out)*costs.fee
            if reward < policy.minimum_rr*costs.loss(p, plan.stop, plan.side):
                rejected.append(f"order:{i}:cost_adjusted_rr")
    status = ("EXECUTION_BLOCKED" if blocked else "INVALIDATED" if invalid else
              "UNASSESSED" if missing else "CONFLICTED" if conflicts else
              "REJECTED" if rejected else "READY")
    return dict(status=status, reasons=tuple(blocked+invalid+missing+conflicts+rejected),
                planned_loss=risk, planned_quantity=qty, order_authorized=False,
                scope="OFFLINE_RESEARCH_ADMISSION")
