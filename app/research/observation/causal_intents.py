"""Arrival-ordered T0 entry probes. No trading account, orders, or PnL claim."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
import sqlite3
from pathlib import Path

from .t0_signal import T0Signal
from ..baseline.account import Costs
from ..baseline.risk import Risk,size_order


def encode(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)


def initial_state(signal):
    return dict(signal=signal.checkpoint(),phase='BOOTSTRAP',armed_ms=None,
                last_received_ns=None,last_received_utc_ns=None,pending=None,
                signal_count=0,probe_count=0,last_quote_time=None)


def check_clock(state,clock):
    fields=('request_started_ns','received_ns','request_started_utc_ns','received_utc_ns')
    if any(type(clock.get(k)) is not int or clock[k]<0 for k in fields):
        raise ValueError('integer receipt clocks required')
    if clock['request_started_ns']>clock['received_ns'] or clock['request_started_utc_ns']>clock['received_utc_ns']:
        raise ValueError('receipt precedes request')
    if clock['received_ns']-clock['request_started_ns']>5_000_000_000:
        raise ValueError('response too slow')
    previous=state['last_received_ns']
    if previous is not None:
        if clock['request_started_ns']<previous:
            raise ValueError('overlapping or reordered requests')
        utc_delta=clock['received_utc_ns']-state['last_received_utc_ns']
        mono_delta=clock['received_ns']-previous
        if abs(utc_delta-mono_delta)>1_000_000_000:
            raise ValueError('wall/monotonic clock jump')
    return clock['received_utc_ns']//1_000_000


def transition(original,kind,body,clock,*,costs=Costs(),risk=Risk()):
    """Pure copy-on-write state transition; caller commits input/state/output together."""
    state=deepcopy(original)
    now=check_clock(state,clock)
    outputs=[]
    if kind=='ARM':
        if state['phase']!='BOOTSTRAP' or body!={}:
            raise ValueError('invalid arm transition')
        signal=T0Signal.restore(state['signal'])
        if signal.completed<80 or signal.last_open_ms is None or not 0<=now-(signal.last_open_ms+60000)<=120000:
            raise ValueError('warmup not ready or stale')
        state['phase']='OBSERVE';state['armed_ms']=now
        outputs.append(dict(kind='ARMED_ENTRY_PROBES_ONLY',at_ms=now))
    elif kind=='KLINES':
        if not isinstance(body,list) or not body or len(body)>1000:
            raise ValueError('bounded kline list required')
        signal=T0Signal.restore(state['signal'])
        consumed=0
        last_response_open=None
        for row in body:
            if not isinstance(row,list) or len(row)!=12 or type(row[0]) is not int or type(row[6]) is not int:
                raise ValueError('invalid kline schema')
            when=row[0]
            if when%60000 or row[6]!=when+59999 or (last_response_open is not None and when!=last_response_open+60000):
                raise ValueError('invalid kline ordering/interval')
            last_response_open=when
            # One-second clock uncertainty buffer. Incomplete bars never enter indicators.
            if when+60000>now-1000:
                continue
            record=dict(open_ms=when,o=float(row[1]),h=float(row[2]),l=float(row[3]),c=float(row[4]),received_ms=now)
            found=signal.step(record);consumed+=1
            if found is None or state['phase']=='BOOTSTRAP':
                continue
            state['signal_count']+=1
            signal_id=str(found['signal_close_ms'])
            if state['pending'] is not None:
                outputs.append(dict(kind='SUPERSEDED',signal_id=state['pending']['id']))
                state['pending']=None
            if found['signal_close_ms']<state['armed_ms']:
                outputs.append(dict(kind='PRE_ARM_SIGNAL_SUPPRESSED',signal_id=signal_id))
            elif now>found['scheduled_ms']+60000:
                outputs.append(dict(kind='LATE_SIGNAL_EXPIRED',signal_id=signal_id,received_ms=now))
            elif not found['side']:
                outputs.append(dict(kind='NEUTRAL_NO_ENTRY',signal_id=signal_id))
            else:
                state['pending']=found|dict(id=signal_id,created_ns=clock['received_ns'],
                                          expires_ms=found['scheduled_ms']+60000)
                outputs.append(dict(kind='ENTRY_PROBE_INTENT',**state['pending']))
        state['signal']=signal.checkpoint()
        outputs.append(dict(kind='BARS_APPLIED',count=consumed,phase=state['phase']))
    elif kind=='QUOTE':
        if not isinstance(body,dict) or body.get('symbol')!='BTCUSDC' or type(body.get('time')) is not int:
            raise ValueError('invalid quote identity')
        bid,ask,bq,aq=(float(body[k]) for k in ('bidPrice','askPrice','bidQty','askQty'))
        if not all(math.isfinite(x) and x>0 for x in (bid,ask,bq,aq)) or bid>ask:
            raise ValueError('invalid quote prices or quantity')
        qt=body['time'];pending=state['pending']
        if state['last_quote_time'] is not None and qt<state['last_quote_time']:
            raise ValueError('quote exchange time regressed')
        state['last_quote_time']=qt
        fresh=-1000<=now-qt<=5000
        outputs.append(dict(kind='QUOTE_OBSERVED',exchange_ms=qt,received_ms=now,fresh=fresh))
        if pending is not None:
            if now>pending['expires_ms']:
                outputs.append(dict(kind='PROBE_EXPIRED',signal_id=pending['id']))
                state['pending']=None
            elif now<pending['earliest_observable_ms']:
                outputs.append(dict(kind='BEFORE_SCHEDULE',signal_id=pending['id']))
            elif clock['request_started_ns']<pending['created_ns']:
                raise ValueError('quote request predates intent')
            elif not fresh or qt<pending['earliest_observable_ms']:
                outputs.append(dict(kind='STALE_OR_PRE_INTENT_QUOTE',signal_id=pending['id']))
            else:
                side=pending['side'];reference=ask if side==1 else bid
                proposal=size_order(reference,pending['close'],pending['atr'],side,risk.initial,False,costs,risk)
                available=aq if side==1 else bq
                if not proposal['approved']:
                    outputs.append(dict(kind='PROBE_SIZE_REJECTED',signal_id=pending['id'],proposal=proposal))
                elif proposal['quantity']>available:
                    outputs.append(dict(kind='INSUFFICIENT_TOP_QUANTITY',signal_id=pending['id'],available=available))
                else:
                    outputs.append(dict(kind='ENTRY_PROBE_QUOTE_ESTIMATE',signal_id=pending['id'],
                        side=side,reference=reference,exchange_ms=qt,received_ms=now,
                        quantity=proposal['quantity'],assumed_price=proposal['entry'],
                        assumed_entry_fee=proposal['quantity']*proposal['entry']*costs.fee_bps/10000,
                        stop=proposal['stop'],planned_loss=proposal['planned_loss'],budget=proposal['budget'],
                        scope='ISOLATED_FLAT_1000_ENTRY_PROBE_NOT_ACCOUNT_FILL'))
                    state['probe_count']+=1
                state['pending']=None
    else:
        raise ValueError('unsupported input kind')
    state['last_received_ns']=clock['received_ns']
    state['last_received_utc_ns']=clock['received_utc_ns']
    return state,outputs


class ProbeStore:
    """Single-writer SQLite transaction for raw receipt, resulting state, and outputs."""
    def __init__(self,path,binding,initial=None):
        exists=Path(path).exists()
        self.db=sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.execute('PRAGMA synchronous=FULL')
        if not exists:
            if initial is None:raise ValueError('initial state required')
            with self.db:
                self.db.execute('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                self.db.execute('CREATE TABLE receipts (id TEXT PRIMARY KEY, seq INTEGER UNIQUE, kind TEXT, raw TEXT, raw_sha256 TEXT, clock TEXT, state TEXT, outputs TEXT)')
                self.db.executemany('INSERT INTO meta VALUES (?,?)', [('binding',encode(binding)),('initial',encode(initial))])
        if self.db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0]!=encode(binding):
            self.db.close();raise ValueError('database implementation/config binding mismatch')

    def state(self):
        row=self.db.execute('SELECT state FROM receipts ORDER BY seq DESC LIMIT 1').fetchone()
        return json.loads(row[0] if row else self.db.execute("SELECT value FROM meta WHERE key='initial'").fetchone()[0])

    def commit(self,request_id,kind,raw,clock,*,before_commit=None):
        # Persist a logical request exactly once. A retry must retain all provenance.
        digest=hashlib.sha256(raw.encode()).hexdigest()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old=self.db.execute('SELECT kind,raw_sha256,clock,outputs FROM receipts WHERE id=?',(request_id,)).fetchone()
            if old:
                if old[:3]!=(kind,digest,encode(clock)):raise ValueError('request id conflicts')
                return json.loads(old[3])
            state,outputs=transition(self.state(),kind,json.loads(raw),clock)
            seq=self.db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM receipts').fetchone()[0]
            self.db.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?,?,?)',
                (request_id,seq,kind,raw,digest,encode(clock),encode(state),encode(outputs)))
            if before_commit is not None:before_commit()
        return outputs

    def close(self):
        self.db.close()
