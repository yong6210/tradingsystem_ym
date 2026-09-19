"""Immutable, point-in-time research evidence. Never authorizes an order."""
from dataclasses import dataclass
from .models import Zone, positive


def timestamp(value):
    if type(value) is not int or value < 0:
        raise ValueError("expected nonnegative integer timestamp")


@dataclass(frozen=True)
class Evidence:
    source: str
    observed_ms: int
    available_ms: int
    recorded_ms: int
    reason: str

    def __post_init__(self):
        for t in (self.observed_ms, self.available_ms, self.recorded_ms):
            timestamp(t)
        if not self.source.strip() or not self.reason.strip():
            raise ValueError("source and reason required")
        if not self.observed_ms <= self.available_ms <= self.recorded_ms:
            raise ValueError("evidence timestamps out of order")


@dataclass(frozen=True)
class ZoneEvent:
    id: str
    kind: str
    evidence: Evidence

    def __post_init__(self):
        if not self.id.strip() or self.kind not in {"formed", "validated", "reaction", "broken", "reclaimed", "retired"}:
            raise ValueError("invalid zone event")


@dataclass(frozen=True)
class ZoneHistory:
    zone: Zone
    events: tuple[ZoneEvent, ...]

    def __post_init__(self):
        object.__setattr__(self, "events", tuple(self.events))
        if not self.events or self.events[0].kind != "formed":
            raise ValueError("formation event required")
        if self.events[0].evidence.available_ms < self.zone.available_ms:
            raise ValueError("formation predates zone availability")
        ids, previous, observed, state = set(), -1, -1, "unknown"
        for event in self.events:
            if event.id in ids or event.evidence.recorded_ms < previous:
                raise ValueError("duplicate or out-of-order event")
            ids.add(event.id)
            previous = event.evidence.recorded_ms
            if event.evidence.observed_ms < observed:
                raise ValueError("stale observation cannot change current zone state")
            observed = event.evidence.observed_ms
            state = self._transition(state, event.kind)

    @staticmethod
    def _transition(state, kind):
        transitions = {("unknown", "formed"): "candidate",
                       ("candidate", "validated"): "valid",
                       ("valid", "reaction"): "valid",
                       ("valid", "broken"): "broken",
                       ("candidate", "broken"): "broken",
                       ("broken", "reclaimed"): "candidate"}
        if kind == "retired" and state in {"candidate", "valid", "broken"}:
            return "retired"
        if (state, kind) not in transitions:
            raise ValueError(f"illegal zone transition: {state}/{kind}")
        return transitions[state, kind]

    def append(self, event):
        """Returns a new history; cannot change an already issued snapshot."""
        return ZoneHistory(self.zone, self.events + (event,))

    def as_of(self, decision_ms):
        timestamp(decision_ms)
        state, visible = "unknown", []
        for event in self.events:
            if event.evidence.recorded_ms > decision_ms:
                break
            state = self._transition(state, event.kind)
            visible.append(event.id)
        return dict(zone_key=self.zone.key, decision_ms=decision_ms, state=state,
                    event_ids=tuple(visible))


@dataclass(frozen=True)
class TargetEvidence:
    target_key: str
    decision_ms: int
    side: int
    reference_price: object
    first_response_price: object
    expected_by_ms: int
    reaction_by_ms: int
    evidence: Evidence
    reachability_reason: str
    intervening_structure: str
    timeout_action: str
    residual_exit: str

    def __post_init__(self):
        for name in ("decision_ms", "expected_by_ms", "reaction_by_ms"):
            timestamp(getattr(self, name))
        if type(self.side) is not int or self.side not in (-1, 1):
            raise ValueError("invalid side")
        for name in ("reference_price", "first_response_price"):
            object.__setattr__(self, name, positive(getattr(self, name)))
        if self.side * (self.first_response_price - self.reference_price) <= 0:
            raise ValueError("first response must be favorable")
        if not self.decision_ms < self.reaction_by_ms <= self.expected_by_ms:
            raise ValueError("invalid explicit horizon")
        if self.evidence.recorded_ms > self.decision_ms:
            raise ValueError("target evidence was not recorded before decision")
        if not self.target_key.strip():
            raise ValueError("target version required")


def assess_evidence(support, target, contract, decision_ms):
    """Assess only zone/target completeness, not trade readiness or profitability."""
    timestamp(decision_ms)
    if contract is not None and contract.decision_ms != decision_ms:
        raise ValueError("contract bound to another decision; reassess explicitly")
    snapshots = [h.as_of(decision_ms) for h in (support, target)]
    missing = []
    for label, snapshot in zip(("support", "target"), snapshots):
        if snapshot["state"] != "valid":
            missing.append(f"{label}:{snapshot['state']}")
    for label, history in (("support", support), ("target", target)):
        if not history.zone.valid:
            missing.append(f"{label}:invalid_zone_record")
    if contract is None:
        missing.append("target_contract_missing")
    else:
        if contract.target_key != target.zone.key:
            raise ValueError("target version mismatch")
        boundary = target.zone.low if contract.side == 1 else target.zone.high
        if contract.side * (contract.first_response_price - boundary) > 0:
            missing.append("first_response_beyond_target")
        for field in ("reachability_reason", "intervening_structure", "timeout_action", "residual_exit"):
            if not getattr(contract, field).strip():
                missing.append(field)
    invalidated = any(s["state"] in {"broken", "retired"} for s in snapshots) or not (support.zone.valid and target.zone.valid)
    status = "INVALIDATED" if invalidated else "UNASSESSED" if missing else "EVIDENCE_COMPLETE"
    return dict(status=status, reasons=tuple(missing), zones=snapshots,
                order_authorized=False)
