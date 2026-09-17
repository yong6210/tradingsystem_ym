"""Pure cancel-then-market planning; persistent dispatcher integration is separate."""
from dataclasses import dataclass, replace
from decimal import Decimal
from hashlib import sha256


@dataclass(frozen=True)
class State:
    original_id: str
    quantity: Decimal
    side: int
    purpose: str  # entry or exit, one-way position mode only
    deadline_ms: int
    phase: str = 'LIMIT_PENDING'

    def __post_init__(self):
        if not self.original_id or self.side not in (-1, 1) or self.purpose not in ('entry', 'exit'):
            raise ValueError('invalid intent')
        if not self.quantity.is_finite() or self.quantity <= 0 or self.deadline_ms < 0:
            raise ValueError('invalid quantity or deadline')
        if self.phase not in ('LIMIT_PENDING','CANCEL_REQUESTED','MARKET_PLANNED','DONE','SKIPPED'):
            raise ValueError('invalid phase')


@dataclass(frozen=True)
class Snapshot:
    original_id: str
    status: str  # UNKNOWN means no authoritative exchange state
    cumulative_fill: Decimal
    observed_ms: int


@dataclass(frozen=True)
class Action:
    kind: str
    reason: str
    quantity: Decimal = Decimal('0')
    side: int = 0
    reduce_only: bool = False
    client_id: str | None = None


def market_client_id(original_id: str) -> str:
    return 'fb_' + sha256(original_id.encode()).hexdigest()[:28]


def plan(state: State, snapshot: Snapshot, *, now_ms: int, signal_valid: bool,
         approved_market_qty: Decimal, position_qty: Decimal,
         context_observed_ms: int, max_age_ms: int = 1000) -> tuple[State, Action]:
    """Inputs must be reconciled cumulative fills and freshly checked risk/lot limits.

    approved_market_qty is computed by an external risk/contract checker using
    market costs, remaining cycle risk and actual positions; this function never
    increases or rounds it. The returned new state must be committed before any
    dispatcher sends an order. No exactly-once exchange guarantee is implied.
    """
    if now_ms < 0 or max_age_ms < 0 or snapshot.original_id != state.original_id:
        raise ValueError('invalid clock or order identity')
    values=(snapshot.cumulative_fill,approved_market_qty,position_qty)
    if not all(value.is_finite() for value in values) or snapshot.cumulative_fill < 0 or snapshot.cumulative_fill > state.quantity or approved_market_qty < 0:
        raise ValueError('inconsistent quantities')
    if state.phase in ('DONE','SKIPPED'):
        return state, Action('NONE','terminal_intent')
    if state.phase == 'MARKET_PLANNED':
        return state, Action('RECONCILE_MARKET','do_not_resubmit',client_id=market_client_id(state.original_id))
    if snapshot.status not in ('UNKNOWN','NEW','PARTIALLY_FILLED','FILLED','CANCELED','EXPIRED','REJECTED'):
        raise ValueError('unknown normalized order status')
    if snapshot.observed_ms > now_ms or now_ms-snapshot.observed_ms > max_age_ms or snapshot.status == 'UNKNOWN':
        return state, Action('QUERY_ORIGINAL','fresh_authoritative_status_required')
    if snapshot.status == 'FILLED':
        if snapshot.cumulative_fill != state.quantity:
            raise ValueError('filled status with inconsistent cumulative quantity')
        return replace(state,phase='DONE'),Action('NONE','original_filled')
    if snapshot.cumulative_fill == state.quantity:
        return state,Action('QUERY_ORIGINAL','quantity_full_but_status_nonterminal')
    terminal=snapshot.status in ('CANCELED','EXPIRED','REJECTED')
    if not terminal:
        if now_ms < state.deadline_ms and (signal_valid or state.purpose=='exit'):
            return state,Action('WAIT','deadline_not_reached')
        if state.phase == 'CANCEL_REQUESTED':
            return state,Action('QUERY_ORIGINAL','cancel_not_confirmed')
        return replace(state,phase='CANCEL_REQUESTED'),Action('CANCEL_ORIGINAL','cancel_before_replacement')
    if state.phase != 'CANCEL_REQUESTED' and now_ms < state.deadline_ms:
        return state,Action('WAIT','terminal_before_fallback_deadline')
    if context_observed_ms > now_ms or now_ms-context_observed_ms > max_age_ms:
        return state,Action('REFRESH_CONTEXT','fresh_risk_and_position_required')
    if state.purpose=='entry' and not signal_valid:
        return replace(state,phase='SKIPPED'),Action('NONE','entry_signal_invalid')
    remaining=state.quantity-snapshot.cumulative_fill
    quantity=min(remaining,approved_market_qty)
    if state.purpose=='exit':
        if position_qty == 0:
            return replace(state,phase='DONE'),Action('NONE','already_flat')
        if position_qty*state.side >= 0:
            return state,Action('HALT_RECONCILE','exit_would_increase_or_reverse_position')
        quantity=min(quantity,abs(position_qty))
    if quantity <= 0:
        if state.purpose=='exit':
            return state,Action('ESCALATE_EXIT','risk_reducing_exit_requires_resolution')
        return replace(state,phase='SKIPPED'),Action('NONE','market_risk_or_contract_rejected')
    return replace(state,phase='MARKET_PLANNED'),Action('MARKET_INTENT','confirmed_remaining_only',quantity,state.side,state.purpose=='exit',market_client_id(state.original_id))
