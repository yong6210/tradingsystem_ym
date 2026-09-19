"""Independent Decimal ledger reconciliation and raw daily signal reconstruction."""
from pathlib import Path
import json, hashlib, io, zipfile, csv
from decimal import Decimal as D, ROUND_FLOOR, ROUND_CEILING
ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'reports/validation/e049_weekly_rotation_20260919'
def rows(p): return [json.loads(x) for x in p.read_text().splitlines()]
def near(a,b):
    if abs(D(str(a))-D(str(b)))>D('0.0000001'): raise AssertionError((a,b))
def main():
    reg=json.loads((P/'registration.json').read_text()); c=reg['config']; inp=json.loads((P/'inputs.json').read_text())
    for p,h in reg['sources'].items(): assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h
    daily={s:{} for s in c['symbols']}
    for entry in inp['archives']:
        p=ROOT/entry['file']; assert hashlib.sha256(p.read_bytes()).hexdigest()==entry['sha256']
        sym=p.name.split('-')[0]
        with zipfile.ZipFile(p) as z:
            with io.TextIOWrapper(z.open(z.namelist()[0])) as stream:
                for r in csv.DictReader(stream):
                    t=int(r['open_time']); key=t//86400000
                    d=daily[sym].setdefault(key,{'high':D(r['high']),'low':D(r['low']),'close':D(r['close']),'count':0})
                    d['high']=max(d['high'],D(r['high'])); d['low']=min(d['low'],D(r['low'])); d['close']=D(r['close']); d['count']+=1
    sig=json.loads((P/'signals.json').read_text()); checks=0
    for stamp,assets in sig.items():
        day=(int(stamp)-3600000)//86400000-1
        for sym,x in assets.items():
            d=daily[sym]; assert d[day]['count']==24
            near(x['momentum'],d[day]['close']/d[day-28]['close']-1)
            ranges=[max(d[k]['high']-d[k]['low'],abs(d[k]['high']-d[k-1]['close']),abs(d[k]['low']-d[k-1]['close'])) for k in range(day-19,day+1)]
            near(x['atr'],sum(ranges)/20); assert x['last_input_close_ms']<int(stamp)-3600000
            checks+=1
    summaries=json.loads((P/'summary.json').read_text()); cases=[]
    for r in summaries:
        ledger=rows(P/(r['case']+'_ledger.jsonl')); trades=rows(P/(r['case']+'_trades.jsonl')); d=rows(P/(r['case']+'_daily.jsonl'))
        cash=D(1000); fees=D(0); funding=D(0); operating=D(0); active={}; slip=D(str(c['cost_cases'][r['cost']]['slippage_bps']))/10000; fee=D('0.00025')
        for e in ledger:
            delta=D(str(e['cash_delta'])); kind=e['kind']
            if kind in ['entry','exit']:
                sym=e['symbol']; rule=inp['rules'][sym]; q=D(str(e['qty'])); price=D(str(e['price'])); ref=D(str(e['reference'])); tick=D(str(rule['tickSize']))
                expected=((ref*(1+slip if kind=='entry' else 1-slip))/tick).to_integral_value(rounding=ROUND_CEILING if kind=='entry' else ROUND_FLOOR)*tick
                near(price,expected); near(e['fee'],q*price*fee); fees+=q*price*fee
                if kind=='entry':
                    assert not active; active={'symbol':sym,'qty':q,'price':price}
                    assert q%D(str(rule['stepSize']))==0 and q>=D(str(rule['minQty']))
                    assert q*ref>=D(str(rule['minNotional'])) and q*price<=cash*D('.5')+D('1e-7')
                    assert D(str(e['planned_stop_risk']))<=cash*D('.005')+D('1e-7')
                    near(delta,-q*price*fee)
                else:
                    assert active['symbol']==sym and active['qty']==q
                    near(delta,q*(price-active['price'])-q*price*fee); active={}
            elif kind=='funding':
                assert active['symbol']==e['symbol']; expected=-active['qty']*D(str(e['mark']))*(D(str(e['rate']))+D(str(e['extra_rate'])))
                near(delta,expected); funding+=delta
            elif kind=='operating_cost': near(delta,-r['operating_cost_monthly']); operating-=delta
            else: raise AssertionError(kind)
            cash+=delta; near(cash,e['cash'])
        assert not active; near(cash-1000,r['net_usdc']); near(fees,r['fees_usdc']); near(funding,r['funding_net_usdc']); near(operating,r['operating_cost_usdc'])
        near(sum(D(str(x['net'])) for x in trades)-operating,cash-1000)
        assert len(d)==730; near(d[-1]['equity'],cash)
        cases.append({'case':r['case'],'ledger_rows':len(ledger),'trades':len(trades),'reconciled':True})
    result={'signal_asset_checks':checks,'archive_checks':len(inp['archives']),'account_cases':cases,'scope':'Independent raw daily aggregation and Decimal ledger/sizing arithmetic; not independent full path simulator, exchange fill or production verification'}
    (P/'verification.json').write_text(json.dumps(result,indent=2)+'\n'); print(json.dumps(result,indent=2))
if __name__=='__main__': main()
