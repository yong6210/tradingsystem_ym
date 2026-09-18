"""Offline, one-cycle spot/perpetual coordinator. No exchange client or network."""
from contextlib import contextmanager
from decimal import Decimal as D, ROUND_FLOOR
import json
import sqlite3

TERMINAL={'FILLED','CANCELED','EXPIRED','REJECTED'}
LIVE={'NEW','PARTIALLY_FILLED'}


def dec(value):
    v=D(str(value))
    if not v.is_finite():raise ValueError('nonfinite value')
    return v


def encode(value):return json.dumps(value,sort_keys=True,separators=(',',':'),default=str)


def validate_context(c):
    for k in ('spot_bid','spot_ask','future_bid','future_ask','mark'):
        if dec(c[k])<=0:raise ValueError('bad quote')
    if any(dec(c[m+'_bid'])>dec(c[m+'_ask']) for m in ('spot','future')):raise ValueError('crossed quote')
    for k in ('now_ms','observed_ms'):
        if type(c[k])is not int or c[k]<0:raise ValueError('clock type')


class CarryPair:
    """Persisted plan -> claimed send -> authoritative full-fill receipt.

    A claimed but uncertain request is never resubmitted automatically. Every
    receipt must include the complete trade set for that order. This is an
    offline adapter contract, not a claim that REST order responses contain it.
    """
    def __init__(self,path,*,scope='paper/BTCUSDC/carry1'):
        self.db=sqlite3.connect(str(path),isolation_level=None,timeout=5)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL);''')
        with self.tx():
            r=self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()
            if r:
                if json.loads(r[0])['scope']!=scope:raise ValueError('scope mismatch')
            else:
                self.put(dict(scope=scope,spot_cash='500',future_cash='500',spot_qty='0',future_qty='0',future_average='0',
                    orders=[],fills={},funding={},operating={},last_now=-1,peak='1000',day=None,day_start='1000',
                    requested_exit=False,emergency=False,fault=None,entry_started=False,phase='IDLE',target='.006'))

    @contextmanager
    def tx(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:yield;self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise

    def close(self):self.db.close()
    def state(self):return json.loads(self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
    def put(self,s):self.db.execute('INSERT OR REPLACE INTO state VALUES (1,?)',(encode(s),))
    def log(self,kind,payload):self.db.execute('INSERT INTO audit(kind,payload) VALUES (?,?)',(kind,encode(payload)))

    def fault(self,reason,evidence):
        with self.tx():
            s=self.state();s['fault']=reason;s['requested_exit']=True;s['emergency']=True;s['phase']='RECONCILIATION_REQUIRED'
            self.put(s);self.log('QUARANTINED',dict(reason=reason,evidence=evidence))

    @staticmethod
    def valuation(s,c):
        sq,fq=dec(s['spot_qty']),dec(s['future_qty'])
        equity=dec(s['spot_cash'])+sq*dec(c['spot_bid'])+dec(s['future_cash'])+fq*(dec(c['future_ask'])-dec(s['future_average']))
        margin=dec(s['future_cash'])+fq*(dec(c['mark'])-dec(s['future_average']))
        return equity,margin

    def request_exit(self,reason='operator',*,emergency=False):
        with self.tx():
            s=self.state();s['requested_exit']=True;s['emergency']|=emergency
            self.put(s);self.log('EXIT_REQUIRED',dict(reason=reason,emergency=emergency))

    def funding(self,event_id,settlement_ms,mark,rate):
        data=dict(settlement_ms=settlement_ms,mark=str(dec(mark)),rate=str(dec(rate)))
        if type(settlement_ms)is not int or settlement_ms<0 or dec(mark)<=0:raise ValueError('funding input')
        with self.tx():
            s=self.state()
            if settlement_ms>s['last_now']:raise ValueError('future funding settlement')
            if any(o['market']=='future' and o['created_ms']<settlement_ms and o['status'] not in TERMINAL for o in s['orders']):
                raise ValueError('funding position unresolved')
            if event_id in s['funding']:
                if s['funding'][event_id]['input']!=data:raise ValueError('funding ID conflict')
                return s['funding'][event_id]
            signed=sum((dec(f['qty'])*f['side'] for f in s['fills'].values()
                if f['market']=='future' and f['time_ms']<settlement_ms),D(0))
            amount=-signed*dec(mark)*dec(rate)
            s['future_cash']=str(dec(s['future_cash'])+amount)
            r=dict(input=data,quantity=str(signed),receipt=str(amount));s['funding'][event_id]=r
            self.put(s);self.log('FUNDING',dict(id=event_id,**r));return r

    def operating_cost(self,event_id,amount):
        amount=dec(amount)
        if amount<0:raise ValueError('negative operating cost')
        with self.tx():
            s=self.state()
            if event_id in s['operating']:
                if dec(s['operating'][event_id])!=amount:raise ValueError('cost ID conflict')
                return
            s['spot_cash']=str(dec(s['spot_cash'])-amount);s['operating'][event_id]=str(amount)
            self.put(s);self.log('OPERATING_COST',dict(id=event_id,amount=amount))

    def _new(self,s,role,qty,c,kind):
        market='spot' if role.startswith('SPOT') else 'future'
        side=1 if role in ('SPOT_ENTRY','FUTURE_EXIT') else -1
        step=D('.00001') if market=='spot' else D('.001')
        qty=(dec(qty)/step).to_integral_value(rounding=ROUND_FLOOR)*step
        price=dec(c[market+('_ask' if side==1 else '_bid')])
        minimum=D(5) if market=='spot' else D(50)
        if qty<=0 or qty*price<minimum:
            s['phase']='DUST_REVIEW';return dict(kind='DUST_REVIEW',spot_qty=s['spot_qty'],future_qty=s['future_qty'])
        fee=D('.001') if market=='spot' else D('.00025')
        remaining_spot_budget=D(400)-max(D(0),D(500)-dec(s['spot_cash']))
        if role=='SPOT_ENTRY' and qty*price*D('1.0005')*(1+fee)>min(remaining_spot_budget,dec(s['spot_cash'])):
            s['requested_exit']=s['emergency']=True;return dict(kind='ENTRY_REJECTED',reason='cash_budget')
        if role=='FUTURE_ENTRY' and qty>dec(s['spot_qty'])+dec(s['future_qty']):raise ValueError('overhedge')
        if role=='FUTURE_ENTRY':
            _,margin=self.valuation(s,c)
            if margin-qty*price*fee<(abs(dec(s['future_qty']))+qty)*max(price,dec(c['mark'])):
                s['requested_exit']=s['emergency']=True;return dict(kind='ENTRY_REJECTED',reason='one_times_initial_margin')
        if role=='FUTURE_EXIT' and qty>-dec(s['future_qty']):raise ValueError('overclose future')
        if role=='SPOT_EXIT' and qty>dec(s['spot_qty']):raise ValueError('oversell spot')
        order=dict(id=s['scope']+'/'+str(len(s['orders'])+1),scope=s['scope'],symbol='BTCUSDC',market=market,
            role=role,side=side,qty=str(qty),kind=kind,price=str(price),reduce_only=role=='FUTURE_EXIT',
            created_ms=c['now_ms'],deadline_ms=c['now_ms']+3000,status='LOCAL',delivery='READY',cancel='NONE',
            version=-1,cumulative='0',receipt=None)
        s['orders'].append(order);self.log('ORDER_RESERVED',order)
        return dict(kind='SUBMIT',order_id=order['id'])

    def next(self,c):
        """Quote prices are bid/ask proxies, not an execution guarantee."""
        validate_context(c)
        with self.tx():
            s=self.state()
            if c['now_ms']<s['last_now']:
                s['fault']='CLOCK_REGRESSION';self.put(s);return dict(kind='RECONCILIATION_REQUIRED')
            s['last_now']=c['now_ms']
            if s['fault']:self.put(s);return dict(kind='RECONCILIATION_REQUIRED',reason=s['fault'])
            fresh=0<=c['now_ms']-c['observed_ms']<=1000
            if fresh:
                equity,margin=self.valuation(s,c);day=c['now_ms']//86400000
                if s['day']!=day:s['day']=day;s['day_start']=str(equity)
                s['peak']=str(max(dec(s['peak']),equity))
                reserve=abs(dec(s['future_qty']))*dec(c['mark'])*D('.01075')
                if equity<=D(995) or equity<=dec(s['day_start'])*D('.98') or equity<=dec(s['peak'])*D('.92') or margin<=reserve or dec(s['spot_cash'])<0:
                    s['requested_exit']=s['emergency']=True;self.log('RISK_EXIT',dict(equity=equity,margin=margin,reserve=reserve))
            active=[o for o in s['orders'] if o['status'] not in TERMINAL]
            if active:
                o=active[0]
                if o['delivery']=='READY':
                    if s['requested_exit'] and o['role'].endswith('ENTRY'):
                        o['status']='CANCELED';o['delivery']='PROVEN_UNSENT';self.put(s);return dict(kind='LOCAL_UNSENT_CANCELED')
                    a=dict(kind='SUBMIT',order_id=o['id']) if fresh else dict(kind='WAIT_FRESH_QUOTES')
                elif o['status']=='LOCAL' or o['cancel']!='NONE':a=dict(kind='QUERY',order_id=o['id'])
                elif (s['requested_exit'] and o['role'].endswith('ENTRY')) or c['now_ms']>=o['deadline_ms']:
                    o['cancel']='READY';a=dict(kind='CANCEL',order_id=o['id'])
                else:a=dict(kind='WAIT_ORDER',order_id=o['id'])
                self.put(s);return a
            if not fresh:self.put(s);return dict(kind='WAIT_FRESH_QUOTES')
            sq,fq=dec(s['spot_qty']),dec(s['future_qty'])
            if s['requested_exit']:
                role='FUTURE_EXIT' if fq<0 else 'SPOT_EXIT' if sq>0 else None
                if role is None:s['phase']='FLAT_HALTED';self.put(s);return dict(kind='FLAT_HALTED')
                previous=[o for o in s['orders'] if o['role']==role]
                if any(o['kind']=='MARKET' and o['delivery']!='PROVEN_UNSENT' for o in previous):
                    s['phase']='RESIDUAL_REVIEW';self.put(s);return dict(kind='RESIDUAL_REVIEW',spot_qty=str(sq),future_qty=str(fq))
                kind='MARKET' if s['emergency'] or previous else 'LIMIT'
                a=self._new(s,role,-fq if fq<0 else sq,c,kind);self.put(s);return a
            if not c.get('funding_confirmed',False):
                if sq+fq:
                    s['requested_exit']=s['emergency']=True;self.put(s);return dict(kind='ABORT_ENTRY',reason='funding_unknown_with_unhedged_inventory')
                self.put(s);return dict(kind='WAIT_FUNDING')
            spot=[o for o in s['orders'] if o['role']=='SPOT_ENTRY']
            if not spot:
                q=dec(s['target']);price=dec(c['spot_ask'])
                prepared=q*price*(D('.01')+2*(D('.001')+D('.00025')))
                if prepared>D(5):self.put(s);return dict(kind='ENTRY_REJECTED',reason='unhedged_stress_budget',prepared=str(prepared))
                a=self._new(s,'SPOT_ENTRY',q,c,'LIMIT');s['entry_started']=True;s['phase']='ENTERING';self.put(s);return a
            if sq<dec(s['target']) and len(spot)==1 and spot[0]['status'] in ('CANCELED','EXPIRED'):
                # Gross fill residual, not target minus net inventory (BTC fees).
                remainder=dec(s['target'])-dec(spot[0]['cumulative'])
                if remainder>0:
                    a=self._new(s,'SPOT_ENTRY',remainder,c,'MARKET');self.put(s);return a
            if sq<=0 or sq%D('.001'):
                s['requested_exit']=s['emergency']=True;self.put(s)
                return dict(kind='ABORT_ENTRY',reason='no_spot_or_unhedgeable_net_quantity',net_spot=str(sq))
            future=[o for o in s['orders'] if o['role']=='FUTURE_ENTRY']
            remainder=sq+fq
            if remainder==0:s['phase']='OPEN';self.put(s);return dict(kind='OPEN')
            if not future:a=self._new(s,'FUTURE_ENTRY',remainder,c,'LIMIT')
            elif len(future)==1 and future[0]['status'] in ('CANCELED','EXPIRED'):
                a=self._new(s,'FUTURE_ENTRY',remainder,c,'MARKET')
            else:
                s['requested_exit']=s['emergency']=True;a=dict(kind='ABORT_ENTRY',reason='hedge_incomplete')
            self.put(s);return a

    def receive(self,receipt):
        """Apply complete normalized order+trade evidence atomically."""
        try:
            with self.tx():
                s=self.state();o=next(x for x in s['orders'] if x['id']==receipt['order_id'])
                if receipt['scope']!=s['scope'] or receipt['symbol']!='BTCUSDC' or receipt['market']!=o['market']:raise ValueError('receipt identity')
                if receipt['status'] not in TERMINAL|LIVE:raise ValueError('receipt status')
                if type(receipt['observed_ms'])is not int or receipt['observed_ms']<o['created_ms']:raise ValueError('receipt time')
                if o['delivery'] in ('READY','PROVEN_UNSENT'):raise ValueError('receipt without claimed submission')
                version=receipt['version']
                if type(version)is not int or version<0:raise ValueError('receipt version')
                if version==o['version']:
                    if encode(receipt)!=o['receipt']:raise ValueError('conflicting duplicate')
                    return
                if version<o['version'] or o['status'] in TERMINAL:raise ValueError('regressed/changed terminal receipt')
                fills=receipt['fills'];ids=[f['id'] for f in fills]
                if len(ids)!=len(set(ids)):raise ValueError('duplicate fill in receipt')
                total=sum((dec(f['qty']) for f in fills),D(0))
                if total!=dec(receipt['cumulative']) or not dec(o['cumulative'])<=total<=dec(o['qty']):raise ValueError('cumulative mismatch')
                if receipt['status']=='FILLED' and total!=dec(o['qty']):raise ValueError('false FILLED')
                if receipt['status'] in ('NEW','REJECTED') and total:raise ValueError('status contradicts fills')
                if receipt['status']=='PARTIALLY_FILLED' and not D(0)<total<dec(o['qty']):raise ValueError('invalid partial status')
                existing={f['id'] for f in s['fills'].values() if f['order_id']==o['id']}
                if not existing<=set(ids):raise ValueError('missing prior fills')
                for f in sorted(fills,key=lambda f:(f['time_ms'],f['id'])):
                    normalized=dict(**f,order_id=o['id'],market=o['market'],side=o['side'])
                    key=o['market']+'/'+f['id']
                    if key in s['fills']:
                        if encode(normalized)!=encode(s['fills'][key]):raise ValueError('fill ID conflict')
                        continue
                    qty,quote,fu,fb=(dec(f[k]) for k in ('qty','quote','fee_usdc','fee_btc'))
                    if min(qty,quote)<=0 or min(fu,fb)<0 or type(f['time_ms'])is not int or not o['created_ms']<=f['time_ms']<=receipt['observed_ms']:raise ValueError('invalid fill')
                    # Previously applied funding would require a correction if a
                    # newly discovered trade predates it. Do not silently revise.
                    if o['market']=='future' and any(f['time_ms']<v['input']['settlement_ms'] for v in s['funding'].values()):raise ValueError('late fill requires funding reconciliation')
                    if o['market']=='spot':
                        sq=dec(s['spot_qty'])+o['side']*qty-fb
                        if sq<0:raise ValueError('spot oversell')
                        s['spot_qty']=str(sq);s['spot_cash']=str(dec(s['spot_cash'])-o['side']*quote-fu)
                    else:
                        if fb:raise ValueError('unsupported futures fee asset')
                        fq=dec(s['future_qty']);avg=dec(s['future_average']);price=quote/qty
                        if o['side']==-1:
                            new=fq-qty;avg=(abs(fq)*avg+quote)/abs(new)
                            if abs(new)>dec(s['spot_qty']):raise ValueError('future exceeds net spot')
                            s['future_qty']=str(new);s['future_average']=str(avg)
                            s['future_cash']=str(dec(s['future_cash'])-fu)
                        else:
                            if qty>-fq:raise ValueError('future overclose')
                            s['future_qty']=str(fq+qty);s['future_average']=str(avg if fq+qty else D(0))
                            s['future_cash']=str(dec(s['future_cash'])+qty*(avg-price)-fu)
                    s['fills'][key]=normalized;self.log('FILL',normalized)
                o['version']=version;o['status']=receipt['status'];o['cumulative']=str(total);o['receipt']=encode(receipt);o['delivery']='OBSERVED'
                s['last_now']=max(s['last_now'],receipt['observed_ms'])
                self.put(s);self.log('RECEIPT',receipt)
        except Exception as exc:
            self.fault(str(exc),receipt);raise

    def dispatch(self,action,transport,context):
        """A crash after the durable claim permits lookup only, including no-hit."""
        kind=action['kind']
        if kind not in ('SUBMIT','CANCEL','QUERY'):return kind
        if kind=='SUBMIT':validate_context(context)
        with self.tx():
            s=self.state();o=next(x for x in s['orders'] if x['id']==action['order_id'])
            if s['fault']:return 'RECONCILIATION_REQUIRED'
            if kind=='SUBMIT':
                if o['delivery']!='READY':return 'QUERY_REQUIRED'
                if not 0<=context['now_ms']-context['observed_ms']<=1000:return 'STALE_CONTEXT'
                if context['now_ms']<max(s['last_now'],o['created_ms']):return 'CLOCK_REGRESSION'
                if o['role'].endswith('ENTRY') and s['requested_exit']:return 'ENTRY_HALTED'
                if o['role'].endswith('ENTRY'):
                    equity,margin=self.valuation(s,context)
                    if not context.get('funding_confirmed',False):return 'FUNDING_UNCONFIRMED'
                    if equity<=D(995) or equity<=dec(s['day_start'])*D('.98') or equity<=dec(s['peak'])*D('.92'):
                        s['requested_exit']=s['emergency']=True;self.put(s);return 'ENTRY_HALTED'
                    q=dec(o['qty']);p=dec(context[o['market']+('_ask' if o['side']==1 else '_bid')])
                    if o['role']=='SPOT_ENTRY':
                        remaining=D(400)-max(D(0),D(500)-dec(s['spot_cash']))
                        if q*p*D('1.0005')*D('1.001')>min(remaining,dec(s['spot_cash'])) or q*p*D('.0125')>5:
                            s['requested_exit']=s['emergency']=True;self.put(s);return 'ENTRY_REPRICE_REJECTED'
                    if o['role']=='FUTURE_ENTRY' and q>dec(s['spot_qty'])+dec(s['future_qty']):return 'OVERHEDGE_REJECTED'
                    if o['role']=='FUTURE_ENTRY' and margin-q*p*D('.00025')<(abs(dec(s['future_qty']))+q)*max(p,dec(context['mark'])):
                        s['requested_exit']=s['emergency']=True;self.put(s);return 'MARGIN_REJECTED'
                o['delivery']='CLAIMED';self.put(s);self.log('SEND_CLAIM',o)
            elif kind=='CANCEL':
                if o['cancel']!='READY':return 'QUERY_REQUIRED'
                o['cancel']='CLAIMED';self.put(s);self.log('CANCEL_CLAIM',o)
            request=dict(o,request_ms=context['now_ms'])
        try:
            receipt=transport.submit(request) if kind=='SUBMIT' else transport.cancel(request) if kind=='CANCEL' else transport.lookup(request)
        except Exception as exc:
            with self.tx():self.log('TRANSPORT_UNCERTAIN',dict(action=action,error=str(exc)))
            return 'UNCERTAIN'
        if receipt is None:return 'UNRESOLVED'
        self.receive(receipt);return 'OBSERVED'
