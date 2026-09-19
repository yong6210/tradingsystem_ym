"""Audit concatenated inventory from raw prices without either replay's arithmetic."""
import csv,hashlib,io,json
from decimal import Decimal as D,ROUND_CEILING
from pathlib import Path
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/local_failure_continuation_20260919'


def main():
    r=json.loads((OUT/'review.json').read_text())
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in r['source_sha256'].items())
    local=json.loads((ROOT/r['config']['local_config']).read_text());cfg=json.loads((ROOT/local['account_config']).read_text())
    archive=ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as f:
        raw={int(b['open_time'])+60000:{k:D(b[k]) for k in ('open','close')} for b in csv.DictReader(io.TextIOWrapper(f))}
    funding=json.loads((ROOT/'data/historical/btcusdc_public_20260917/funding_history.json').read_text())
    paths=[(label,name,a) for label,group in r['groups'].items() for name,a in group.items()]
    paths += [('no_liquidity',name,a) for name,a in r['no_liquidity_segments'].items()]
    for label,name,a in paths:
        p=r['initial_position'];q=D(p['quantity']);avg=D(p['average']);gross=D(p['realized_gross']);paid=D(p['paid_costs']);remain=D(p['remaining_costs'])
        cash=D(p['starting_equity'])+gross-paid+q*avg
        peak=D(r['initial_state']['peak_equity']);maximum=D(r['prior_max_drawdown']);exposure=D(0)
        fee,spread,tick,lev=[D(cfg[k]) for k in ('fee','half_spread','tick','leverage')]
        slip=D('.0005') if label=='slippage_5bp' else D(cfg['slippage'])
        ask=lambda mark:(mark*(1+spread)*(1+slip)/tick).to_integral_value(rounding=ROUND_CEILING)*tick
        start=r['initial_state']['time_ms'];end=a['states'][-1]['time_ms'];fills=[e for e in a['ledger'] if e['kind']=='fill']
        assert [s['time_ms'] for s in a['states']]==list(range(start+60000,end+1,60000))
        events=sorted([(f['fundingTime'],0,f) for f in funding if start<f['fundingTime']<=end]+[(e['time_ms'],1,e) for e in fills],key=lambda x:(x[0],x[1]))
        index=0;fund=[]
        for s in a['states']:
            t=s['time_ms']
            while index<len(events) and (events[index][0]<t or (events[index][0]==t and events[index][1]==0)):
                et,kind,e=events[index];index+=1
                if kind==0:
                    if q:
                        payment=-q*D(e['markPrice'])*D(e['fundingRate']);paid+=payment;remain+=payment;cash-=payment
                        fund.append((et,q,payment))
                else:
                    qty=D(e['quantity']);price=ask(raw[et+60000]['open']);cost=qty*price*fee
                    assert e['decision_ms']<et and D(e['price'])==price and D(e['fee'])==cost
                    assert 0<qty<=q and qty%D(cfg['step'])==0
                    gross+=qty*(avg-price);paid+=cost;cash-=qty*price+cost;remain=remain*(q-qty)/q;q-=qty
            mark=raw[t]['close'];net=gross-paid+q*(avg-mark);equity=D(p['starting_equity'])+net
            assert abs(cash-q*mark-equity)<D('1e-9')
            peak=max(peak,equity);dd=peak-equity;maximum=max(maximum,dd);exposure+=q/60
            expected=dict(total_net=net,equity=equity,net_if_closed=gross-paid+q*(avg-ask(mark))-q*ask(mark)*fee,
                          free_margin_proxy=equity-q*mark/lev,peak_equity=peak,drawdown=dd)
            assert all(abs(D(s[k])-v)<D('1e-9') for k,v in expected.items()),(label,name,t)
            pos=s['position'];assert D(pos['quantity'])==q and D(pos['realized_gross'])==gross and D(pos['paid_costs'])==paid
            assert abs(D(pos['remaining_costs'])-remain)<D('1e-9')
            assert (D(pos['average'])==avg) if q else pos['average'] is None
            if 'join_state' in a and t==a['join_state']['time_ms']:assert s==a['join_state']
        actual_fund=[(e['time_ms'],D(e['quantity']),D(e['payment'])) for e in a['ledger'] if e['kind']=='funding']
        assert fund==actual_fund
        ddkey='cumulative_max_close_drawdown' if label=='no_liquidity' else 'maximum_drawdown'
        assert D(a['summary'][ddkey])==maximum
        assert abs(D(a['summary']['exposure_btc_hours'])-exposure)<D('1e-9')
        if label=='no_liquidity':
            assert not fills and q==D('.012') and a['pending'] is not None
            assert a['summary']['final']==r['blocked_no_liquidity'][name]['final']
        else:assert q==0 and a['pending'] is None
    assert len(r['groups']['no_liquidity'])==0 and len(r['blocked_no_liquidity'])==3
    checks=dict(source_hashes='PASS',continuous_minute_timeline='PASS',raw_execution_and_funding='PASS',
                independent_cash_and_position='PASS',preserved_peak_and_drawdown='PASS',
                no_liquidity_not_reset_or_falsely_closed='PASS',verified_completed_paths=27,verified_blocked_prefixes=3,
                verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT/'verification.json').write_text(json.dumps(checks,indent=2)+'\n');print(json.dumps(checks))


if __name__=='__main__':main()
