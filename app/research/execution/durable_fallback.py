"""SQLite-backed offline outbox for fallback intents.

A send is claimed durably before transport invocation. Uncertain sends are only
queried, never automatically resent, even when lookup returns not-found. This
prefers a visible unresolved order over a duplicate; it is not exchange exactly-once.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Callable, Protocol

from .market_fallback import Action, Snapshot, State, market_client_id, plan

TERMINAL = {'FILLED', 'CANCELED', 'EXPIRED', 'REJECTED'}


def encode(value):
    return json.dumps(asdict(value), default=str, sort_keys=True)


def decode_state(payload):
    fields=json.loads(payload)
    fields['quantity']=Decimal(fields['quantity'])
    return State(**fields)


def decode_action(payload):
    fields=json.loads(payload)
    fields['quantity']=Decimal(fields['quantity'])
    return Action(**fields)


@dataclass(frozen=True)
class Command:
    command_id: str
    original_id: str
    action: Action
    delivery: str
    executed: Decimal
    exchange_status: str | None = None


@dataclass(frozen=True)
class Receipt:
    command_id: str
    original_id: str
    status: str
    executed: Decimal
    sequence: int  # Monotonic per-command version from a reconciled adapter.


class OfflineTransport(Protocol):
    def submit(self, command: Command) -> Receipt: ...
    def lookup(self, command: Command) -> Receipt | None: ...


class Journal:
    def __init__(self, path: str | Path):
        self.db=sqlite3.connect(str(path), isolation_level=None, timeout=5)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS intents (
            original_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
            original_fill TEXT NOT NULL DEFAULT '0', original_status TEXT,
            original_observed INTEGER NOT NULL DEFAULT -1
        );
        CREATE TABLE IF NOT EXISTS outbox (
            command_id TEXT PRIMARY KEY, original_id TEXT NOT NULL REFERENCES intents(original_id),
            action TEXT NOT NULL, delivery TEXT NOT NULL, executed TEXT NOT NULL DEFAULT '0',
            receipt_sequence INTEGER NOT NULL DEFAULT -1, exchange_status TEXT,
            error TEXT
        );
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, command_id TEXT,
            kind TEXT NOT NULL, detail TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fill_deltas (
            command_id TEXT NOT NULL REFERENCES outbox(command_id), sequence INTEGER NOT NULL,
            quantity TEXT NOT NULL, PRIMARY KEY(command_id, sequence)
        );
        ''')

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def register(self, state: State):
        if state.phase!='LIMIT_PENDING':
            raise ValueError('register initial state only')
        with self.transaction():
            row=self.db.execute('SELECT payload FROM intents WHERE original_id=?',(state.original_id,)).fetchone()
            if row:
                old=decode_state(row['payload'])
                original=State(old.original_id,old.quantity,old.side,old.purpose,old.deadline_ms)
                if original!=state:
                    raise ValueError('original id reused for a different intent')
            else:
                self.db.execute('INSERT INTO intents(original_id,payload) VALUES (?,?)',(state.original_id,encode(state)))

    def state(self, original_id: str) -> State:
        row=self.db.execute('SELECT payload FROM intents WHERE original_id=?',(original_id,)).fetchone()
        if row is None:
            raise KeyError(original_id)
        return decode_state(row['payload'])

    def command(self, command_id: str) -> Command:
        row=self.db.execute('SELECT * FROM outbox WHERE command_id=?',(command_id,)).fetchone()
        if row is None:
            raise KeyError(command_id)
        return Command(row['command_id'],row['original_id'],decode_action(row['action']),row['delivery'],Decimal(row['executed']),row['exchange_status'])

    def commands(self) -> list[Command]:
        return [self.command(row[0]) for row in self.db.execute('SELECT command_id FROM outbox ORDER BY rowid').fetchall()]

    def advance(self, snapshot: Snapshot, *, fault: Callable | None = None, **context) -> Action:
        """Atomically commit a state transition and its cancel/market command."""
        with self.transaction():
            row=self.db.execute('SELECT * FROM intents WHERE original_id=?',(snapshot.original_id,)).fetchone()
            if row is None:
                raise KeyError(snapshot.original_id)
            state=decode_state(row['payload'])
            # UNKNOWN is not evidence capable of replacing a known terminal state.
            authoritative = (snapshot.status!='UNKNOWN' and
                             0 <= context['now_ms']-snapshot.observed_ms <= context.get('max_age_ms',1000))
            if authoritative:
                if snapshot.observed_ms<row['original_observed']:
                    raise ValueError('older original snapshot')
                if snapshot.cumulative_fill<Decimal(row['original_fill']):
                    raise ValueError('cumulative original fill regressed')
                if row['original_status'] in TERMINAL and (snapshot.status!=row['original_status'] or snapshot.cumulative_fill!=Decimal(row['original_fill'])):
                    raise ValueError('original terminal state changed; reconciliation required')
            new_state,action=plan(state,snapshot,**context)
            self.db.execute('UPDATE intents SET payload=? WHERE original_id=?',(encode(new_state),state.original_id))
            if authoritative:
                self.db.execute('UPDATE intents SET original_fill=?, original_status=?, original_observed=? WHERE original_id=?',
                                (str(snapshot.cumulative_fill),snapshot.status,snapshot.observed_ms,state.original_id))
            if fault:
                fault('after_state_before_outbox')
            if action.kind in ('CANCEL_ORIGINAL','MARKET_INTENT'):
                command_id=action.client_id or market_client_id(state.original_id)+'_c'
                self.db.execute('INSERT INTO outbox(command_id,original_id,action,delivery) VALUES (?,?,?,?)',
                                (command_id,state.original_id,encode(action),'READY'))
            self.db.execute('INSERT INTO audit(kind,detail) VALUES (?,?)',('PLAN',encode(action)))
            return action

    def claim(self, command_id: str) -> bool:
        """At most one dispatcher can cross READY→SENDING."""
        with self.transaction():
            cursor=self.db.execute("UPDATE outbox SET delivery='SENDING' WHERE command_id=? AND delivery='READY'",(command_id,))
            if cursor.rowcount:
                self.db.execute('INSERT INTO audit(command_id,kind,detail) VALUES (?,?,?)',(command_id,'CLAIM','persisted before transport'))
            return cursor.rowcount==1

    def mark_problem(self, command_id: str, delivery: str, reason: str):
        if delivery not in ('UNCERTAIN','BLOCKED'):
            raise ValueError('invalid problem delivery')
        with self.transaction():
            # Do not overwrite a concurrently reconciled acknowledgement or fill.
            self.db.execute('UPDATE outbox SET delivery=?,error=? WHERE command_id=? AND delivery=?',
                            (delivery,reason,command_id,'SENDING'))
            self.db.execute('INSERT INTO audit(command_id,kind,detail) VALUES (?,?,?)',(command_id,delivery,reason))

    def receipt(self, receipt: Receipt):
        if receipt.status not in TERMINAL|{'NEW','PARTIALLY_FILLED'} or receipt.sequence<0 or not receipt.executed.is_finite() or receipt.executed<0:
            raise ValueError('invalid receipt')
        with self.transaction():
            row=self.db.execute('SELECT * FROM outbox WHERE command_id=?',(receipt.command_id,)).fetchone()
            if row is None or row['original_id']!=receipt.original_id:
                raise ValueError('receipt identity mismatch')
            if row['delivery'] in ('READY','BLOCKED'):
                raise ValueError('receipt for unsubmitted command')
            action=decode_action(row['action'])
            bound=action.quantity if action.kind=='MARKET_INTENT' else self.state(receipt.original_id).quantity
            if receipt.executed>bound or (receipt.status=='FILLED' and receipt.executed!=bound):
                raise ValueError('receipt exceeds or disagrees with intended quantity')
            if receipt.sequence<row['receipt_sequence']:
                return  # Old stream events cannot roll the ledger backwards.
            old_qty=Decimal(row['executed'])
            if receipt.sequence==row['receipt_sequence']:
                if receipt.executed!=old_qty or receipt.status!=row['exchange_status']:
                    raise ValueError('conflicting duplicate receipt')
                return
            if receipt.executed<old_qty:
                raise ValueError('cumulative replacement fill regressed')
            if row['exchange_status'] in TERMINAL and (receipt.status!=row['exchange_status'] or receipt.executed!=old_qty):
                raise ValueError('terminal replacement state changed')
            delivery='TERMINAL' if receipt.status in TERMINAL else 'ACKNOWLEDGED'
            self.db.execute('UPDATE outbox SET delivery=?, executed=?, receipt_sequence=?, exchange_status=?, error=NULL WHERE command_id=?',
                            (delivery,str(receipt.executed),receipt.sequence,receipt.status,receipt.command_id))
            delta=receipt.executed-old_qty
            if action.kind=='MARKET_INTENT' and delta>0:
                self.db.execute('INSERT INTO fill_deltas VALUES (?,?,?)',(receipt.command_id,receipt.sequence,str(delta)))
            if action.kind=='MARKET_INTENT' and receipt.status in TERMINAL:
                state=self.state(receipt.original_id)
                phase='DONE' if receipt.status=='FILLED' else 'MARKET_PLANNED'
                self.db.execute('UPDATE intents SET payload=? WHERE original_id=?',
                                (encode(State(state.original_id,state.quantity,state.side,state.purpose,state.deadline_ms,phase)),state.original_id))
                if receipt.status!='FILLED':
                    self.db.execute('INSERT INTO audit(command_id,kind,detail) VALUES (?,?,?)',
                                    (receipt.command_id,'UNRESOLVED_REMAINDER','No automatic new order; position/risk review required'))
            self.db.execute('INSERT INTO audit(command_id,kind,detail) VALUES (?,?,?)',(receipt.command_id,'RECEIPT',encode(receipt)))

    def filled_quantity(self, command_id: str) -> Decimal:
        return sum((Decimal(row[0]) for row in self.db.execute('SELECT quantity FROM fill_deltas WHERE command_id=?',(command_id,))),Decimal('0'))


def dispatch_once(journal: Journal, command_id: str, transport: OfflineTransport,
                  authorize: Callable[[Command], bool], fault: Callable | None = None) -> str:
    """Offline transport only; authorize must freshly recheck all live constraints.

    Unknown/not-found after a durable claim never results in a second submit.
    A crash before the first actual send thus requires explicit reconciliation.
    """
    command=journal.command(command_id)
    if command.delivery=='TERMINAL':
        if command.action.kind=='MARKET_INTENT' and command.exchange_status!='FILLED':
            return 'TERMINAL_REMAINDER_REQUIRES_REVIEW'
        return 'TERMINAL'
    if command.delivery=='BLOCKED':
        return 'BLOCKED'
    if command.delivery=='READY':
        if not journal.claim(command_id):
            return 'CLAIMED_ELSEWHERE'
        command=journal.command(command_id)
        if fault:
            fault('after_claim_before_send')
        try:
            if not authorize(command):
                journal.mark_problem(command_id,'BLOCKED','Fresh original/position/risk/filter check rejected')
                return 'BLOCKED'
            response=transport.submit(command)
            if fault:
                fault('after_send_before_receipt_commit')
            journal.receipt(response)
            current=journal.command(command_id)
            if current.delivery=='TERMINAL' and current.action.kind=='MARKET_INTENT' and current.exchange_status!='FILLED':
                return 'TERMINAL_REMAINDER_REQUIRES_REVIEW'
            return current.delivery
        except Exception as exc:
            journal.mark_problem(command_id,'UNCERTAIN',type(exc).__name__)
            return 'UNCERTAIN'
    try:
        response=transport.lookup(command)
        if response is None:
            return 'UNRESOLVED_NOT_FOUND'
        journal.receipt(response)
        current=journal.command(command_id)
        if current.delivery=='TERMINAL' and current.action.kind=='MARKET_INTENT' and current.exchange_status!='FILLED':
            return 'TERMINAL_REMAINDER_REQUIRES_REVIEW'
        return current.delivery
    except Exception:
        return 'UNRESOLVED_QUERY'
