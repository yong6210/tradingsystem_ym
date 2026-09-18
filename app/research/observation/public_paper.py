"""Public receipt coordinator around the frozen E020 hypothetical account.

Readiness means consistency of observed announcements and bounded REST scans.
It is deliberately not an exchange funding-completeness certificate.
"""
from copy import deepcopy
import math

from ..baseline.account import Costs
from .causal_intents import check_clock
from .quote_paper_account import initial_state as account_initial
from .quote_paper_account import transition as account_transition, _funding


def initial_state(signal, session, created_ms):
    if type(created_ms) is not int or created_ms < 86400000:
        raise ValueError('valid account creation time required')
    return dict(version=1, account=account_initial(signal, session),
                created_ms=created_ms, scan_start_ms=created_ms-86400000,
                schedule_received_ms=None, history_received_ms=None, server_received_ms=None,
                next_due_ms=None, expected=[], faults={}, review_reasons=[],
                ended=False, guard=None)


def entry_guard(state, now):
    reasons = list(state['review_reasons'])
    reasons += ['RESPONSE_ERROR_'+k for k in sorted(state['faults']) if k!='ARM']
    if state['ended']:
        reasons.append('OBSERVATION_ENDED')
    for key, limit in [('schedule_received_ms',30000), ('history_received_ms',30000),
                       ('server_received_ms',120000)]:
        value = state[key]
        if value is None or not 0 <= now-value <= limit:
            reasons.append('STALE_OR_MISSING_'+key.upper())
    last = state['account']['signal']['state']['last_open_ms']
    if last is None or not 0 <= now-(last+60000) <= 120000:
        reasons.append('STALE_COMPLETED_BAR')
    settled = [int(k) for k in state['account']['settlements']]
    for due in state['expected']:
        if abs(now-due)<=1000:
            reasons.append('FUNDING_BOUNDARY')
        if now >= due-1000 and not any(abs(t-due)<=1000 for t in settled):
            reasons.append('UNRESOLVED_EXPECTED_FUNDING')
            break
    if state['next_due_ms'] is None or state['next_due_ms'] <= now+1000:
        reasons.append('NO_FUTURE_FUNDING_SCHEDULE')
    return dict(status='BLOCK_NEW_ENTRY' if reasons else 'SCOPED_READY', reasons=reasons,
                assessed_ms=now, scope='OBSERVED_SCHEDULE_AND_BOUNDED_SCAN_ONLY')


def _premium(state, body, now):
    if not isinstance(body,dict) or body.get('symbol')!='BTCUSDC':
        raise ValueError('premium symbol/schema')
    event_time, due = body.get('time'), body.get('nextFundingTime')
    if type(event_time) is not int or type(due) is not int:
        raise ValueError('premium integer times required')
    if not -1000 <= now-event_time <= 5000 or due <= now+1000:
        raise ValueError('stale premium or funding boundary')
    if not math.isfinite(float(body['markPrice'])) or float(body['markPrice'])<=0:
        raise ValueError('invalid premium price')
    old = state['next_due_ms']
    if old is not None and old > now+1000 and old != due:
        if 'FUTURE_SCHEDULE_CHANGED' not in state['review_reasons']:
            state['review_reasons'].append('FUTURE_SCHEDULE_CHANGED')
    if due not in state['expected']:
        state['expected'].append(due)
    state['next_due_ms'] = due
    state['schedule_received_ms'] = now


def _history(state, body, query, clock, now, outputs):
    start, end = query.get('startTime'), query.get('endTime')
    request_ms = clock['request_started_utc_ns']//1000000
    if (query.get('symbol')!='BTCUSDC' or query.get('limit')!=100 or
            type(start) is not int or type(end) is not int or start!=state['scan_start_ms'] or
            not start<=end<=request_ms-1000 or request_ms-1000-end>5000):
        raise ValueError('funding query coverage invalid')
    if not isinstance(body,list) or len(body)>=100:
        raise ValueError('funding response may be truncated')
    previous = None
    returned = set()
    for row in body:
        if not isinstance(row,dict) or row.get('symbol')!='BTCUSDC' or row.get('rateType','Regular')!='Regular':
            raise ValueError('funding schema/symbol/type')
        when = row.get('fundingTime')
        if type(when) is not int or not start<=when<=end or (previous is not None and when<=previous):
            raise ValueError('funding range/order/duplicate')
        previous = when; returned.add(when)
    for when in state['account']['settlements']:
        if start<=int(when)<=end and int(when) not in returned:
            raise ValueError('previously received settlement missing from scan')
    for due in state['expected']:
        if sum(abs(t-due)<=1000 for t in returned)>1:
            raise ValueError('ambiguous multiple settlements near expected time')
    for row in body:
        _funding(state['account'],row,now,outputs,Costs(**state['account']['costs']))
    state['history_received_ms'] = now
    outputs.append(dict(kind='FUNDING_SCAN_ACCEPTED',rows=len(body),start_ms=start,end_ms=end,
                        scope='BOUNDED_RESPONSE_NOT_GLOBAL_COMPLETENESS'))


def transition(original, kind, body, clock, session, query=None):
    """Atomically accept or journal a rejected body; bad clocks remain fatal.

    A failed batch restores all financial state while retaining its input and
    diagnostic. No row of an invalid funding batch can leak into the account.
    """
    state = deepcopy(original)
    account = state['account']
    if kind=='BEGIN_SESSION':
        account, outputs = account_transition(account,kind,body,clock,session)
        state.update(account=account,schedule_received_ms=None,history_received_ms=None,
                     server_received_ms=None,ended=False)
        state['guard'] = entry_guard(state,clock['received_utc_ns']//1000000)
        return state,outputs
    if session!=account['session']:
        raise ValueError('wrong public receive session')
    now = check_clock(account,clock)
    if account['last_received_utc_ns'] is not None and clock['request_started_utc_ns']<account['last_received_utc_ns']:
        raise ValueError('UTC receive order regressed')
    previous = state['schedule_received_ms']
    if account['quantity'] and (previous is None or now-previous>30000):
        if 'HELD_POSITION_SCHEDULE_GAP' not in state['review_reasons']:
            state['review_reasons'].append('HELD_POSITION_SCHEDULE_GAP')
    baseline = deepcopy(state)
    outputs = []
    try:
        if kind=='PREMIUM':
            _premium(state,body,now)
            outputs.append(dict(kind='FUNDING_SCHEDULE_OBSERVED',next_due_ms=state['next_due_ms']))
        elif kind=='FUNDING_HISTORY':
            _history(state,body,query or {},clock,now,outputs)
        elif kind=='SERVER_TIME':
            if not isinstance(body,dict):raise ValueError('invalid server time body')
            server = body.get('serverTime')
            if type(server) is not int or not clock['request_started_utc_ns']//1000000-1000<=server<=now+1000:
                raise ValueError('server/local time bracket')
            state['server_received_ms'] = now
            outputs.append(dict(kind='SERVER_TIME_CHECKED'))
        elif kind=='FEED_ERROR':
            channel = body['channel']
            if channel not in ('KLINES','QUOTE','PREMIUM','FUNDING_HISTORY','SERVER_TIME'):
                raise ValueError('unknown failed channel')
            state['faults'][channel] = str(body['error'])[:200]
            outputs.append(dict(kind='PUBLIC_REQUEST_FAILED',channel=channel,error=state['faults'][channel]))
        elif kind=='END':
            if body!={}:raise ValueError('invalid END body')
            state['ended'] = True
            account.update(pending=None,phase='STOPPED')
            if account['quantity']:account['exit_required']='observation_end_exit'
            outputs.append(dict(kind='OBSERVATION_ENDED',residual_quantity=account['quantity']))
        elif kind in ('ARM','KLINES','QUOTE'):
            guard = entry_guard(state,now)
            if kind=='ARM' and guard['reasons']:
                raise ValueError('cannot arm before public readiness: '+','.join(guard['reasons']))
            if kind=='QUOTE' and guard['reasons'] and not account['quantity']:
                if account['pending'] is not None:
                    outputs.append(dict(kind='ENTRY_CANCELLED_DATA_GUARD',reasons=guard['reasons']))
                account['pending'] = None
            account, emitted = account_transition(account,kind,body,clock,session)
            state['account'] = account
            outputs += emitted
        else:
            raise ValueError('unsupported public input')
        state['faults'].pop(kind,None)
    except (ValueError,KeyError,TypeError,OverflowError) as exc:
        state = baseline
        state['faults'][kind] = str(exc)[:200]
        outputs = [dict(kind='PUBLIC_INPUT_REJECTED',channel=kind,reason=state['faults'][kind])]
    account = state['account']
    account['last_received_ns'] = clock['received_ns']
    account['last_received_utc_ns'] = clock['received_utc_ns']
    state['guard'] = entry_guard(state,now)
    outputs.append(dict(kind='ENTRY_GUARD',**state['guard']))
    return state,outputs
