"""Versioned, offline order semantics. No transport or implicit fill inference.

Reservation results must be committed with an outbox by an external coordinator.
This module does not provide account reconciliation, concurrency or live approval.
"""
from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from enum import Enum
from hashlib import sha256


def positive(value: Decimal):
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError('positive finite Decimal required')


def timestamp(value):
    if type(value) is not int or value < 0:
        raise ValueError('nonnegative integer time required')


class Reentry(str, Enum):
    FRESH_EPISODE = 'FRESH_EPISODE'
    CONTINUING_NEXT_DECISION = 'CONTINUING_NEXT_DECISION'


class TargetAnchor(str, Enum):
    EPISODE_START = 'EPISODE_START'
    ENTRY_DECISION = 'ENTRY_DECISION'


class TakeProfit(str, Enum):
    CLOSE_CONFIRM_MARKET = 'CLOSE_CONFIRM_MARKET'
    TOUCH_MARKET = 'TOUCH_MARKET'
    RESTING_LIMIT = 'RESTING_LIMIT'


class StopBasis(str, Enum):
    ATR = 'ATR'
    STRUCTURE = 'STRUCTURE'


@dataclass(frozen=True)
class Rules:
    reentry: Reentry
    target_anchor: TargetAnchor
    take_profit: TakeProfit
    stop_basis: StopBasis
    tick: Decimal = Decimal('.1')
    atr_multiple: Decimal = Decimal('3')
    structure_buffer_ticks: int = 1
    decision_delay_ms: int = 60000
    maximum_hold_ms: int = 604800000

    def __post_init__(self):
        for value,kind in ((self.reentry,Reentry),(self.target_anchor,TargetAnchor),(self.take_profit,TakeProfit),(self.stop_basis,StopBasis)):
            if not isinstance(value,kind): raise ValueError('explicit enum required')
        positive(self.tick);positive(self.atr_multiple)
        if type(self.structure_buffer_ticks) is not int or self.structure_buffer_ticks < 1:
            raise ValueError('positive structural buffer required')
        timestamp(self.decision_delay_ms);timestamp(self.maximum_hold_ms)
        if self.decision_delay_ms == 0 or self.maximum_hold_ms == 0:
            raise ValueError('positive delays required')


@dataclass(frozen=True)
class Levels:
    available_ms: int  # completed source candle, never a future pivot
    close: Decimal
    atr: Decimal
    structure_low: Decimal
    structure_high: Decimal
    target: Decimal

    def __post_init__(self):
        timestamp(self.available_ms)
        for v in (self.close,self.atr,self.structure_low,self.structure_high,self.target): positive(v)
        if self.structure_low >= self.structure_high: raise ValueError('invalid structure range')


@dataclass(frozen=True)
class SignalState:
    scope: str  # account/paper namespace + symbol + strategy/version
    side: int = 0
    episode_id: str | None = None
    anchor: Levels | None = None
    latest: Levels | None = None

    def __post_init__(self):
        if not self.scope or type(self.side) is not int or self.side not in (-1,0,1):
            raise ValueError('invalid signal state')
        if self.side == 0 and (self.episode_id is not None or self.anchor is not None):
            raise ValueError('neutral state must clear episode')
        if self.side != 0 and (not self.episode_id or self.anchor is None or self.latest is None):
            raise ValueError('directional state requires episode snapshots')
        if self.anchor and self.latest and self.anchor.available_ms > self.latest.available_ms:
            raise ValueError('future anchor')


def update_signal(state: SignalState, side: int, levels: Levels) -> SignalState:
    """New episode only after a completed neutral observation or direction change.

    A stop/fill is not a new signal. Replaying an identical completed observation
    is idempotent; conflicting or older observations fail closed.
    """
    if not state.scope or type(side) is not int or side not in (-1,0,1): raise ValueError('invalid signal')
    if state.latest is not None:
        if levels.available_ms < state.latest.available_ms: raise ValueError('out-of-order signal')
        if levels.available_ms == state.latest.available_ms:
            if side == state.side and levels == state.latest: return state
            raise ValueError('conflicting same-time signal')
    if side == 0:
        return SignalState(state.scope,latest=levels)
    if side != state.side:
        identity=f'{state.scope}|{levels.available_ms}|{side}'
        return SignalState(state.scope,side,sha256(identity.encode()).hexdigest()[:28],levels,levels)
    return replace(state,latest=levels)


@dataclass(frozen=True)
class EntryBook:
    consumed: frozenset[str] = frozenset()
    last_decision_ms: int = -1
    last_closed_ms: int = -1
    active_intent_id: str | None = None


@dataclass(frozen=True)
class Reservation:
    approved: bool
    reason: str
    intent_id: str | None = None


def reserve_entry(book: EntryBook, signal: SignalState, rules: Rules, *, now_ms: int,
                  reconciled_flat_and_orders_clear: bool, risk_approved: bool, signal_valid: bool):
    timestamp(now_ms)
    if any(type(v) is not bool for v in (reconciled_flat_and_orders_clear,risk_approved,signal_valid)):
        raise ValueError('explicit reconciled booleans required')
    def reject(reason): return book,Reservation(False,reason)
    if not signal.side or signal.latest is None or signal.episode_id is None: return reject('NO_SIGNAL')
    decision=signal.latest.available_ms
    if now_ms < decision+rules.decision_delay_ms: return reject('DECISION_NOT_AVAILABLE')
    if book.active_intent_id is not None or not reconciled_flat_and_orders_clear: return reject('POSITION_OR_ORDERS_UNRESOLVED')
    if not signal_valid or not risk_approved: return reject('SIGNAL_OR_RISK_REJECTED')
    if decision <= book.last_decision_ms: return reject('DECISION_ALREADY_RESERVED')
    if decision <= book.last_closed_ms: return reject('NEW_COMPLETED_DECISION_AFTER_CLOSE_REQUIRED')
    if rules.reentry == Reentry.FRESH_EPISODE and signal.episode_id in book.consumed: return reject('EPISODE_ALREADY_RESERVED')
    identity=f'{signal.scope}|{signal.episode_id}|{decision}'
    intent='cy_'+sha256(identity.encode()).hexdigest()[:28]
    return EntryBook(book.consumed|{signal.episode_id},decision,book.last_closed_ms,intent),Reservation(True,'RESERVE_NOT_SEND',intent)


def finish_cycle(book: EntryBook, intent_id: str, *, confirmed_ms: int,
                 reconciled_flat_and_orders_clear: bool) -> EntryBook:
    timestamp(confirmed_ms)
    if type(reconciled_flat_and_orders_clear) is not bool or not reconciled_flat_and_orders_clear:
        raise ValueError('position and all related orders must be reconciled')
    if book.active_intent_id != intent_id or confirmed_ms < max(book.last_decision_ms,book.last_closed_ms):
        raise ValueError('wrong cycle or older closure')
    # A canceled/unfilled attempt still consumes this fresh-episode opportunity.
    return replace(book,last_closed_ms=confirmed_ms,active_intent_id=None)


@dataclass(frozen=True)
class CyclePlan:
    intent_id: str
    side: int
    decision_ms: int
    target_source_ms: int
    stop: Decimal
    target: Decimal
    rules: Rules

    def __post_init__(self):
        if not self.intent_id or type(self.side) is not int or self.side not in (-1,1):
            raise ValueError('invalid cycle identity')
        timestamp(self.decision_ms);timestamp(self.target_source_ms)
        positive(self.stop);positive(self.target)
        if self.target_source_ms > self.decision_ms or self.side*(self.target-self.stop)<=0:
            raise ValueError('invalid cycle levels or time')


def prepare_cycle(signal: SignalState, rules: Rules, intent_id: str, proposed_entry: Decimal) -> CyclePlan:
    """Freeze before submission, not after observing future price/fill outcomes.

    Stop uses the latest completed entry-decision snapshot. Structure is supplied
    by the strategy (e.g. known channel edge), never inferred from future pivots.
    """
    positive(proposed_entry)
    if signal.side not in (-1,1) or signal.anchor is None or signal.latest is None or not intent_id:
        raise ValueError('missing signal/intent')
    side=signal.side;latest=signal.latest
    target_levels=signal.anchor if rules.target_anchor == TargetAnchor.EPISODE_START else latest
    raw=(latest.close-side*rules.atr_multiple*latest.atr if rules.stop_basis == StopBasis.ATR else
         latest.structure_low-rules.tick*rules.structure_buffer_ticks if side==1 else
         latest.structure_high+rules.tick*rules.structure_buffer_ticks)
    rounding=ROUND_FLOOR if side==1 else ROUND_CEILING
    stop=(raw/rules.tick).to_integral_value(rounding=rounding)*rules.tick
    # Target rounds toward entry; this never increases promised reward.
    target=(target_levels.target/rules.tick).to_integral_value(rounding=rounding)*rules.tick
    positive(stop);positive(target)
    if side*(proposed_entry-stop)<=0 or side*(target-proposed_entry)<=0:
        raise ValueError('stop/target invalid at proposed entry; do not chase or move levels')
    return CyclePlan(intent_id,side,latest.available_ms,target_levels.available_ms,stop,target,rules)


def assess_fill(plan: CyclePlan, *, average: Decimal, quantity: Decimal,
                reserved_loss: Decimal, roundtrip_cost_per_btc: Decimal) -> str:
    """First and every partial fill require protection and fresh remaining risk.

    Violation requests an urgent exit; it does not pretend the fill was rejected.
    Cost reserve includes entry/exit fee + adverse exit slippage from caller.
    """
    for value in (average,quantity,reserved_loss): positive(value)
    if not isinstance(roundtrip_cost_per_btc,Decimal) or not roundtrip_cost_per_btc.is_finite() or roundtrip_cost_per_btc < 0:
        raise ValueError('invalid cost reserve')
    stop_distance=plan.side*(average-plan.stop)
    reward=plan.side*(plan.target-average)
    if stop_distance<=0 or reward<=roundtrip_cost_per_btc or quantity*(stop_distance+roundtrip_cost_per_btc)>reserved_loss:
        return 'URGENT_EXIT_CANCEL_ENTRY_REMAINDER'
    return 'PROTECT_FILLED_QUANTITY_RECHECK_REMAINDER'


@dataclass(frozen=True)
class Bar:
    start_ms: int
    end_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal

    def __post_init__(self):
        timestamp(self.start_ms);timestamp(self.end_ms)
        for value in (self.open,self.high,self.low,self.close): positive(value)
        if self.end_ms<=self.start_ms or not self.low<=min(self.open,self.close)<=max(self.open,self.close)<=self.high:
            raise ValueError('invalid bar')


@dataclass(frozen=True)
class ExitDecision:
    kind: str
    reason: str
    reference: Decimal | None = None
    earliest_ms: int | None = None
    ambiguous: bool = False
    # Exit orders must use reconciled remaining quantity and reduce-only.


def evaluate_bar(plan: CyclePlan, bar: Bar, *, active_from_ms: int,
                 risk_halt=False, strategy_close_available=False, pending_exit=False) -> ExitDecision:
    """OHLC research semantics only. A touched limit is NEVER a reported fill.

    Prices returned for intrabar market stops/touches are reference proxies with
    unknown event time; costs/latency belong to a fill engine. Close confirmation
    schedules future execution, never executes using the observed close itself.
    """
    timestamp(active_from_ms)
    if any(type(v) is not bool for v in (risk_halt,strategy_close_available,pending_exit)):
        raise ValueError('explicit flags required')
    if bar.end_ms<=active_from_ms: return ExitDecision('NONE','NOT_ACTIVE')
    if risk_halt:
        return ExitDecision('URGENT_RECONCILE_EXIT' if pending_exit else 'URGENT_EXIT_REQUIRED','ACCOUNT_RISK')
    if active_from_ms>bar.start_ms:
        return ExitDecision('FINER_DATA_REQUIRED','ENTRY_INSIDE_BAR',ambiguous=True)
    side=plan.side
    stop_gap=side*(bar.open-plan.stop)<=0
    stop_touch=bar.low<=plan.stop if side==1 else bar.high>=plan.stop
    target_gap=side*(bar.open-plan.target)>=0
    target_touch=bar.high>=plan.target if side==1 else bar.low<=plan.target
    def protective(reason,reference,ambiguous=False):
        return ExitDecision('URGENT_RECONCILE_EXIT' if pending_exit else 'URGENT_EXIT_REQUIRED',reason,reference,ambiguous=ambiguous)
    if stop_gap: return protective('STOP_GAP',bar.open)
    deadline=active_from_ms+plan.rules.maximum_hold_ms
    if bar.start_ms < deadline < bar.end_ms:
        return ExitDecision('FINER_DATA_REQUIRED','EXPIRY_INSIDE_BAR',ambiguous=True)
    if pending_exit:
        if stop_touch: return protective('STOP_WITH_EXIT_PENDING',plan.stop,target_touch)
        return ExitDecision('RECONCILE_EXIT','DO_NOT_DUPLICATE')
    if bar.start_ms>=active_from_ms+plan.rules.maximum_hold_ms:
        return ExitDecision('EXIT_REQUIRED','TIME_LIMIT',bar.open,bar.start_ms)
    mode=plan.rules.take_profit
    # An opening target crossing is temporally before any later bar extreme.
    if target_gap and mode == TakeProfit.TOUCH_MARKET:
        return ExitDecision('EXIT_REQUIRED','TARGET_GAP_MARKET_PROXY',bar.open,bar.start_ms)
    if stop_touch:
        return protective('STOP_FIRST_OHLC' if target_touch and mode!=TakeProfit.CLOSE_CONFIRM_MARKET else 'STOP_TOUCH',
                          plan.stop,target_touch and mode!=TakeProfit.CLOSE_CONFIRM_MARKET)
    if target_touch and mode==TakeProfit.RESTING_LIMIT:
        return ExitDecision('LIMIT_EXECUTION_EVIDENCE_REQUIRED','TOUCH_IS_NOT_FILL',plan.target,ambiguous=True)
    if target_touch and mode==TakeProfit.TOUCH_MARKET:
        return ExitDecision('EXIT_REQUIRED','TARGET_TOUCH_MARKET_PROXY',plan.target,ambiguous=True)
    if mode==TakeProfit.CLOSE_CONFIRM_MARKET and strategy_close_available and side*(bar.close-plan.target)>=0:
        return ExitDecision('SCHEDULE_EXIT','TARGET_CLOSE_CONFIRMED',earliest_ms=bar.end_ms+plan.rules.decision_delay_ms)
    return ExitDecision('NONE','HOLD')
