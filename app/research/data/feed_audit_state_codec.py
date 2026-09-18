"""Bounded JSON codec for OFFLINE replay state; no pickle or dynamic classes."""
from collections import Counter
from decimal import Decimal

from .compact_feed_intervals import CompactIntervals
from .durable_capture_log import JournalError, integer, keys
from .durable_market_feed import MarketFeedProcessor
from .local_order_book import LocalOrderBook
from ..foundation.forward_data_contract import REQUIREMENTS

MAX_NODES = 250000
MAX_CONTAINER = 20000
PROCESSOR_FIELDS = set(MarketFeedProcessor().__dict__)-{'book'}
BOOK_BASE = set(LocalOrderBook().__dict__)
BOOK_SESSION = set('started_ns last_receive_ns available_ns snapshot_ns snapshot_id last_u last_event_hash bid_floor ask_ceiling buffer'.split())
REDUCER_FIELDS = set(CompactIntervals(0,1).__dict__)


def convert(value, *, restore=False):
    nodes = 0
    def visit(v, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NODES or depth > 32: raise JournalError('audit state structure bound')
        if v is None or type(v) in (bool,int,str):
            if type(v) is str and len(v) > 4*1024**2: raise JournalError('audit state string bound')
            if type(v) is int and abs(v) > 10**100: raise JournalError('audit state integer bound')
            return v
        if restore:
            keys(v,'t v')
            tag, items = v['t'], v['v']
            if tag == 'decimal':
                if type(items) is not str or len(items)>64: raise JournalError('state decimal string')
                decimal = Decimal(items)
                if not decimal.is_finite() or abs(decimal.as_tuple().exponent)>18 or len(decimal.as_tuple().digits)>40:
                    raise JournalError('state decimal bounds')
                return decimal
            if type(items) is not list or len(items)>MAX_CONTAINER: raise JournalError('audit state container bound')
            if tag in ('dict','counter'):
                result = {}
                for pair in items:
                    if type(pair) is not list or len(pair)!=2: raise JournalError('state map pair')
                    k, val = visit(pair[0],depth+1),visit(pair[1],depth+1)
                    if k in result: raise JournalError('state map duplicate')
                    result[k] = val
                return Counter(result) if tag=='counter' else result
            result = [visit(item,depth+1) for item in items]
            if tag=='tuple': return tuple(result)
            if tag=='list': return result
            if tag=='set':
                if len(set(result))!=len(result): raise JournalError('state set duplicate')
                return set(result)
            raise JournalError('unknown state type')
        if type(v) is Decimal:
            return dict(t='decimal',v=str(v))
        if type(v) in (dict,Counter):
            if len(v)>MAX_CONTAINER: raise JournalError('audit state map bound')
            return dict(t='counter' if type(v) is Counter else 'dict',
                        v=[[visit(k,depth+1),visit(item,depth+1)] for k,item in v.items()])
        if type(v) in (list,tuple,set):
            if len(v)>MAX_CONTAINER: raise JournalError('audit state container bound')
            items=sorted(v) if type(v) is set else v
            return dict(t={list:'list',tuple:'tuple',set:'set'}[type(v)],v=[visit(item,depth+1) for item in items])
        raise JournalError('unsupported audit state value')
    return visit(value)


def validate(processor, reducer):
    p,b,r = processor.__dict__,processor.book.__dict__,reducer.__dict__
    if set(p)!=(PROCESSOR_FIELDS|{'book'}) or set(r)!=REDUCER_FIELDS:
        raise JournalError('audit state field schema differs')
    if set(b) != BOOK_BASE | (BOOK_SESSION if b['session'] is not None else set()):
        raise JournalError('book state field schema differs')
    integer(processor.sequence)
    if type(processor.processed_ns) is not int or processor.processed_ns < -1: raise JournalError('state processing clock')
    if type(processor.closed) is not bool or type(reducer.failed) is not bool: raise JournalError('state boolean')
    if type(processor.errors) is not list or len(processor.errors)>128 or any(type(x) is not str for x in processor.errors):
        raise JournalError('state errors bound')
    if type(processor.counts) is not Counter or len(processor.counts)>64: raise JournalError('state counters')
    for k,v in processor.counts.items():
        if type(k) is not str: raise JournalError('state counter name')
        integer(v)
    for value in (processor.used_sessions,processor.ended_sessions,processor.book.sessions):
        if type(value) is not set or len(value)>128: raise JournalError('state session bound')
    if type(processor.sessions) is not dict or not set(processor.sessions).issubset({'public','market'}):
        raise JournalError('state sessions')
    if type(processor.last_receive) is not dict or not set(processor.last_receive).issubset({'public','market','system'}):
        raise JournalError('state receive clocks')
    for v in processor.last_receive.values(): integer(v)
    for name in ('deadline_ns','mark_received_ns','depth_received_ns','market_received_ns','watchdog_ns','request_ns'):
        if p[name] is not None: integer(p[name])
    if b['symbol']!='BTCUSDC' or b['state'] not in ('EMPTY','BUFFERING','AWAIT_BRIDGE','LIVE','INVALID'):
        raise JournalError('book state identity')
    if type(b['audit']) is not list or len(b['audit'])>4096: raise JournalError('book audit bound')
    if b['session'] is not None:
        if type(b['buffer']) is not list or len(b['buffer'])>4096: raise JournalError('book buffer bound')
    for side in (b['bids'],b['asks']):
        if type(side) is not dict or len(side)>10000: raise JournalError('book levels bound')
        if any(type(k) is not Decimal or type(v) is not Decimal or not k.is_finite() or not v.is_finite() or k<=0 or v<0
               for k,v in side.items()): raise JournalError('book level value')
    integer(r['start']);integer(r['end'],r['start']+1);integer(r['limit'],1)
    if r['limit']>10000: raise JournalError('interval state bound')
    keys(r['intervals'],' '.join(REQUIREMENTS))
    count=0
    for rows in [*r['intervals'].values(),r['exclusions']]:
        if type(rows) is not list: raise JournalError('interval state array')
        previous=-1
        for pair in rows:
            if type(pair) is not tuple or len(pair)!=2: raise JournalError('interval state pair')
            left,right=pair;integer(left,r['start']);integer(right,left+1)
            if right>r['end'] or left<=previous: raise JournalError('interval state order')
            previous=right;count+=1
    if count!=r['count'] or count>r['limit'] or not count<=r['peak']<=r['limit']:
        raise JournalError('interval state count')
    integer(r['points'])
    if r['previous'] is not None:
        if type(r['previous']) is not tuple or len(r['previous'])!=2: raise JournalError('interval previous lease')
        stamp,expiries=r['previous'];integer(stamp)
        if type(expiries) is not dict or not set(expiries).issubset(REQUIREMENTS): raise JournalError('interval lease names')
        for v in expiries.values(): integer(v)
    if r['first'] is not None: integer(r['first'])


def pack(processor,reducer):
    validate(processor,reducer)
    return convert(dict(processor={k:v for k,v in processor.__dict__.items() if k!='book'},
                        book=processor.book.__dict__,reducer=reducer.__dict__))


def unpack(payload):
    row=convert(payload,restore=True)
    keys(row,'processor book reducer')
    processor=MarketFeedProcessor();book=LocalOrderBook();reducer=CompactIntervals(0,1)
    if any(type(row[k]) is not dict for k in row): raise JournalError('state objects required')
    processor.__dict__=row['processor'];book.__dict__=row['book'];processor.book=book
    reducer.__dict__=row['reducer']
    validate(processor,reducer)
    return processor,reducer
