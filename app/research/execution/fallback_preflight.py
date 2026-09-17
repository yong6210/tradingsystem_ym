"""Offline one-way fallback risk approval; no exchange client or network I/O.

Context must come from one reconciled account snapshot. Risk amounts are USDC;
quantities are BTC. Public filters alone never imply account approval.
"""
from dataclasses import asdict, dataclass, fields, replace
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import json

from .binance_contract import Contract, decimal, parse_query
from .durable_fallback import Command, Journal
from .market_fallback import Action, Snapshot, State, market_client_id

ZERO = Decimal('0')


@dataclass(frozen=True)
class RiskContext:
    observed_ms: int
    quote_observed_ms: int
    filters_observed_ms: int
    equity: Decimal
    peak_equity: Decimal
    day_start_equity: Decimal
    position_qty: Decimal
    position_risk: Decimal
    other_reserved_risk: Decimal
    other_reserved_notional: Decimal
    pending_exit_qty: Decimal
    cycle_initial_budget: Decimal
    cycle_spent: Decimal  # Nonnegative losses + paid costs; profits do not replenish it.
    margin_quantity_cap: Decimal  # Explicit external margin/bracket reservation result.
    mark_price: Decimal
    worst_entry_price: Decimal  # Adverse executable quote/slippage estimate, not mark.
    stop_price: Decimal
    taker_fee_fraction: Decimal
    stop_slippage_fraction: Decimal
    funding_reserve_per_btc: Decimal
    signal_valid: bool
    reconciled: bool
    protection_ready: bool
    warning_latched: bool
    drawdown_halted: bool
    daily_halted: bool

    def __post_init__(self) -> None:
        signed = {'position_qty'}
        positive = {'equity', 'peak_equity', 'day_start_equity', 'mark_price', 'worst_entry_price'}
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name.endswith('_ms'):
                if type(value) is not int or value < 0:
                    raise ValueError('nonnegative integer timestamp required')
            elif field.type is bool:
                if type(value) is not bool:
                    raise ValueError('explicit boolean required')
            elif not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f'{field.name}: finite Decimal required')
            elif field.name in positive and value <= 0:
                raise ValueError(f'{field.name}: positive value required')
            elif field.name not in signed and value < 0:
                raise ValueError(f'{field.name}: nonnegative value required')
        if self.peak_equity < self.equity:
            raise ValueError('peak equity below current equity')
        if self.taker_fee_fraction >= 1 or self.stop_slippage_fraction >= 1:
            raise ValueError('invalid cost fraction')

    @property
    def oldest_ms(self) -> int:
        return min(self.observed_ms, self.quote_observed_ms, self.filters_observed_ms)


@dataclass(frozen=True)
class Approval:
    quantity: Decimal
    reason: str
    remaining_risk: Decimal = ZERO
    loss_per_btc: Decimal = ZERO


def latch_risk(journal: Journal, context: RiskContext, *, now_ms: int) -> RiskContext:
    """Persist halt/warning before planning; one account per offline journal.

    No reset path is provided. Even daily halts require a future explicit,
    reconciled recovery procedure rather than an automatic midnight reset.
    Stale or unreconciled observations may read, but never overwrite latches.
    """
    journal.db.execute('''CREATE TABLE IF NOT EXISTS fallback_risk_latches (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        warning INTEGER NOT NULL, drawdown_halt INTEGER NOT NULL,
        daily_halt INTEGER NOT NULL, observed_ms INTEGER NOT NULL)''')
    with journal.transaction():
        row = journal.db.execute('SELECT * FROM fallback_risk_latches WHERE singleton=1').fetchone()
        warning = bool(row['warning']) if row else False
        drawdown_halt = bool(row['drawdown_halt']) if row else False
        daily_halt = bool(row['daily_halt']) if row else False
        if context.reconciled and 0 <= now_ms - context.observed_ms <= 1000:
            if row and context.observed_ms < row['observed_ms']:
                raise ValueError('risk observation regressed; reconciliation required')
            warning |= context.warning_latched or 1 - context.equity / context.peak_equity >= Decimal('.05')
            drawdown_halt |= context.drawdown_halted or 1 - context.equity / context.peak_equity >= Decimal('.08')
            daily_halt |= context.daily_halted or 1 - context.equity / context.day_start_equity >= Decimal('.02')
            journal.db.execute('INSERT OR REPLACE INTO fallback_risk_latches VALUES (1,?,?,?,?)',
                               (warning, drawdown_halt, daily_halt, context.observed_ms))
        return replace(context, warning_latched=warning or context.warning_latched,
                       drawdown_halted=drawdown_halt or context.drawdown_halted,
                       daily_halted=daily_halt or context.daily_halted)


def rounded(value: Decimal, step: Decimal, *, up: bool = False) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * step


def approve_remaining(state: State, snapshot: Snapshot, context: RiskContext,
                      contract: Contract, *, now_ms: int, max_age_ms: int = 1000) -> Approval:
    """Approve at most the canceled remainder, after existing risk and costs.

    Fixed v1 risk policy: cycle .5%, aggregate 1%, notional 1x, DD warning 5%
    halves new risk, DD halt 8%, daily halt 2%. No automatic warning reset.
    This is a scoped integration prototype, not a production margin engine.
    """
    if type(now_ms) is not int or type(max_age_ms) is not int or min(now_ms, max_age_ms) < 0:
        raise ValueError('invalid clock')
    if snapshot.original_id != state.original_id:
        raise ValueError('original identity mismatch')
    if not snapshot.cumulative_fill.is_finite() or not ZERO <= snapshot.cumulative_fill <= state.quantity:
        raise ValueError('invalid original fill')
    times = (snapshot.observed_ms, context.observed_ms,
             context.quote_observed_ms, context.filters_observed_ms)
    if any(t > now_ms or now_ms - t > max_age_ms for t in times):
        return Approval(ZERO, 'STALE_CONTEXT')
    if not context.reconciled:
        return Approval(ZERO, 'RECONCILIATION_REQUIRED')
    if snapshot.status not in ('CANCELED', 'EXPIRED', 'REJECTED'):
        return Approval(ZERO, 'ORIGINAL_NOT_CANCELED')
    remainder = state.quantity - snapshot.cumulative_fill
    if not remainder:
        return Approval(ZERO, 'NO_REMAINDER')

    lot = contract.filter('LOT_SIZE')
    market_lot = contract.filter('MARKET_LOT_SIZE')
    step = decimal(lot['stepSize'])
    # General lattices need a separate implementation; never assume alignment.
    if (step <= 0 or decimal(market_lot['stepSize']) != step or
            decimal(lot['minQty']) % step or decimal(market_lot['minQty']) % step):
        return Approval(ZERO, 'UNSUPPORTED_QUANTITY_LATTICE')
    maximum = min(decimal(lot['maxQty']), decimal(market_lot['maxQty']))
    risk_room = loss_per_btc = ZERO
    if state.purpose == 'exit':
        if context.position_qty * state.side >= 0:
            return Approval(ZERO, 'FLAT_OR_WRONG_EXIT_SIDE')
        quantity = min(remainder, max(ZERO, abs(context.position_qty) - context.pending_exit_qty), maximum)
    else:
        drawdown = 1 - context.equity / context.peak_equity
        daily_loss = 1 - context.equity / context.day_start_equity
        if context.drawdown_halted or context.daily_halted or drawdown >= Decimal('.08') or daily_loss >= Decimal('.02'):
            return Approval(ZERO, 'ENTRY_RISK_HALTED')
        if not context.signal_valid or not context.protection_ready:
            return Approval(ZERO, 'SIGNAL_OR_PROTECTION_NOT_READY')
        if context.position_qty * state.side < 0 or context.pending_exit_qty:
            return Approval(ZERO, 'POSITION_OR_EXIT_CONFLICT')
        tick = decimal(contract.filter('PRICE_FILTER')['tickSize'])
        if tick <= 0 or context.stop_price <= 0 or context.stop_price % tick:
            return Approval(ZERO, 'INVALID_FIXED_STOP')
        entry = rounded(context.worst_entry_price, tick, up=state.side == 1)
        if state.side * (entry - context.stop_price) <= 0:
            return Approval(ZERO, 'STOP_ALREADY_CROSSED')
        stop_fill = rounded(context.stop_price * (1 - state.side * context.stop_slippage_fraction),
                            tick, up=state.side == -1)
        if stop_fill <= 0:
            return Approval(ZERO, 'INVALID_STOP_FILL')
        loss_per_btc = (state.side * (entry - stop_fill) +
                        (entry + stop_fill) * context.taker_fee_fraction +
                        context.funding_reserve_per_btc)
        multiplier = Decimal('.5') if context.warning_latched or drawdown >= Decimal('.05') else Decimal(1)
        cycle_cap = min(context.cycle_initial_budget, context.equity * Decimal('.005') * multiplier)
        risk_room = max(ZERO, min(cycle_cap - context.cycle_spent - context.position_risk,
                                 context.equity * Decimal('.01') - context.position_risk - context.other_reserved_risk))
        price_bound = max(entry, context.mark_price)
        notional_room = max(ZERO, context.equity - abs(context.position_qty) * price_bound - context.other_reserved_notional)
        quantity = min(remainder, maximum, risk_room / loss_per_btc,
                       notional_room / price_bound, context.margin_quantity_cap)
    quantity = rounded(quantity, step)
    if quantity <= 0:
        return Approval(ZERO, 'NO_ADMISSIBLE_LOT', risk_room, loss_per_btc)
    try:
        contract.check(order_type='MARKET', side='BUY' if state.side == 1 else 'SELL',
                       quantity=quantity, mark_price=context.mark_price,
                       reduce_only=state.purpose == 'exit', position_quantity=context.position_qty)
    except ValueError as exc:
        return Approval(ZERO, 'CONTRACT_REJECTED:' + str(exc), risk_room, loss_per_btc)
    return Approval(quantity, 'APPROVED', risk_room, loss_per_btc)


def advance_from_query(journal: Journal, payload: dict, context: RiskContext,
                       contract: Contract, *, original_id: str, observed_ms: int,
                       now_ms: int) -> tuple[Action, Approval]:
    """Full REST-shaped original query → approval → atomic state/outbox update."""
    state = journal.state(original_id)
    observation = parse_query(payload, client_id=original_id, side='BUY' if state.side == 1 else 'SELL',
                              quantity=state.quantity, order_type='LIMIT',
                              reduce_only=state.purpose == 'exit', observed_ms=observed_ms)
    snapshot = Snapshot(original_id, observation.status, observation.executed, observation.observed_ms)
    context = latch_risk(journal, context, now_ms=now_ms)
    approval = approve_remaining(state, snapshot, context, contract, now_ms=now_ms)
    with journal.transaction():
        journal.db.execute('INSERT INTO audit(kind,detail) VALUES (?,?)',
                           ('RISK_PREFLIGHT', json.dumps(dict(original_id=original_id, now_ms=now_ms,
                            snapshot=asdict(snapshot), context=asdict(context), approval=asdict(approval)), default=str)))
    # Stale/unreconciled context is recoverable; do not turn it into permanent SKIPPED.
    if (approval.reason in ('STALE_CONTEXT', 'RECONCILIATION_REQUIRED') and
            snapshot.status in ('CANCELED', 'EXPIRED', 'REJECTED')):
        action = Action('REFRESH_CONTEXT', approval.reason)
        with journal.transaction():
            journal.db.execute('INSERT INTO audit(kind,detail) VALUES (?,?)', ('PREFLIGHT', approval.reason))
        return action, approval
    action = journal.advance(snapshot, now_ms=now_ms, signal_valid=context.signal_valid,
                             approved_market_qty=approval.quantity, position_qty=context.position_qty,
                             context_observed_ms=context.oldest_ms)
    return action, approval


def authorize_market(command: Command, state: State, snapshot: Snapshot,
                     context: RiskContext, contract: Contract, *, now_ms: int) -> bool:
    """Fresh dispatch-time check; never resize an already journaled command."""
    action = command.action
    if (action.kind != 'MARKET_INTENT' or command.original_id != state.original_id or
            command.command_id != market_client_id(state.original_id) or
            action.client_id != command.command_id or action.side != state.side or
            action.reduce_only != (state.purpose == 'exit') or state.phase != 'MARKET_PLANNED'):
        return False
    approval = approve_remaining(state, snapshot, context, contract, now_ms=now_ms)
    if not ZERO < action.quantity <= approval.quantity:
        return False
    try:
        contract.check(order_type='MARKET', side='BUY' if action.side == 1 else 'SELL',
                       quantity=action.quantity, mark_price=context.mark_price,
                       reduce_only=action.reduce_only, position_quantity=context.position_qty)
    except ValueError:
        return False
    return True


def authorize_journaled_market(journal: Journal, command: Command, snapshot: Snapshot,
                               context: RiskContext, contract: Contract, *, now_ms: int) -> bool:
    """Dispatch entry point: retain latches and immutable original terminal fill."""
    row = journal.db.execute('SELECT original_status, original_fill FROM intents WHERE original_id=?',
                             (command.original_id,)).fetchone()
    if (row is None or row['original_status'] != snapshot.status or
            Decimal(row['original_fill']) != snapshot.cumulative_fill):
        return False
    context = latch_risk(journal, context, now_ms=now_ms)
    allowed = authorize_market(command, journal.state(command.original_id), snapshot,
                               context, contract, now_ms=now_ms)
    with journal.transaction():
        journal.db.execute('INSERT INTO audit(command_id,kind,detail) VALUES (?,?,?)',
                           (command.command_id, 'DISPATCH_RISK_PREFLIGHT',
                            json.dumps(dict(now_ms=now_ms, allowed=allowed, snapshot=asdict(snapshot),
                                            context=asdict(context)), default=str)))
    return allowed
