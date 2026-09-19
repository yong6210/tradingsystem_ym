"""Independent Decimal audit of carried inventory, raw fills, funding and equity."""
import csv,hashlib,io,json
from decimal import Decimal,ROUND_CEILING
from pathlib import Path
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/market_transition_inventory_20260919'
D=lambda x:Decimal(str(x))
TOL=D('0.000000001')


def main():
    r=json.loads((OUT/'review.json').read_text())
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in r['source_sha256'].items())
    cfg=json.loads((ROOT/r['config']['account_config']).read_text())
    previous=json.loads((ROOT/'reports/validation/first_candidate_account_20260919/review.json').read_text())
    start=previous['summary']['final']['time_ms'];end=next(iter(r['policies'].values()))['states'][-1]['time_ms']
    archive=ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    raw={}
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as f:
        for row in csv.DictReader(io.TextIOWrapper(f)):
            raw[int(row['open_time'])+60000]={k:D(row[k]) for k in ('open','high','close')}
    funding=json.loads((ROOT/'data/historical/btcusdc_public_20260917/funding_history.json').read_text())
    funding=[f for f in funding if start<f['fundingTime']<=end]
    groups=[('base',r['policies'],cfg)]+[(name,group,dict(cfg,**({'slippage':'0.0005'} if name=='slippage_5bp' else {}))) for name,group in r['sensitivities'].items()]
    verified=0
    for label,group,cost in groups:
        fee,spread,slip,tick,leverage=[D(cost[k]) for k in ('fee','half_spread','slippage','tick','leverage')]
        ask=lambda mark:(mark*(1+spread)*(1+slip)/tick).to_integral_value(rounding=ROUND_CEILING)*tick
        for name,a in group.items():
            p=r['initial_position'];q=D(p['quantity']);avg=D(p['average']);gross=D(p['realized_gross']);paid=D(p['paid_costs']);remain=D(p['remaining_costs'])
            peak=D(previous['summary']['final']['peak_equity']);extension_dd=D(0);fees=D(0);fund=D(0);expected_funding=[]
            fills=[e for e in a['ledger'] if e['kind']=='fill']
            events=sorted([(f['fundingTime'],0,f) for f in funding]+[(e['time_ms'],1,e) for e in fills],key=lambda e:(e[0],e[1]));index=0
            for s in a['states']:
                t=s['time_ms']
                while index<len(events) and (events[index][0]<t or (events[index][0]==t and events[index][1]==0)):
                    et,kind,e=events[index];index+=1
                    if kind==0:
                        if q:
                            payment=-q*D(e['markPrice'])*D(e['fundingRate']);paid+=payment;remain+=payment;fund+=payment
                            expected_funding.append((et,q,payment))
                    else:
                        assert e['decision_ms']<et
                        mark=raw[et+60000]['open'];price=ask(mark);qty=D(e['quantity']);f=qty*price*fee
                        assert D(e['mark'])==mark and D(e['price'])==price and D(e['fee'])==f
                        assert 0<qty<=q and qty%D(cfg['step'])==0
                        gross+=qty*(avg-price);paid+=f;fees+=f;remain=remain*(q-qty)/q;q-=qty
                mark=raw[t]['close'];net=gross-paid+(q*(avg-mark) if q else 0);equity=D(p['starting_equity'])+net
                peak=max(peak,equity);dd=peak-equity;extension_dd=max(extension_dd,dd)
                close_net=gross-paid+(q*(avg-ask(mark))-q*ask(mark)*fee if q else 0)
                expected={'total_net':net,'equity':equity,'free_margin_proxy':equity-q*mark/leverage,'net_if_closed':close_net,'peak_equity':peak,'drawdown':dd}
                assert all(abs(D(s[k])-v)<TOL for k,v in expected.items())
                assert D(s['position']['quantity'])==q and abs(D(s['position']['remaining_costs'])-remain)<TOL
            actual_funding=[(e['time_ms'],D(e['quantity']),D(e['payment'])) for e in a['ledger'] if e['kind']=='funding']
            assert actual_funding==expected_funding
            assert D(a['summary']['extension_fees'])==fees and D(a['summary']['extension_funding_paid'])==fund
            assert abs(D(a['summary']['extension_max_close_drawdown'])-extension_dd)<TOL
            assert abs(D(a['summary']['extension_net_change'])-(net-D(previous['summary']['final']['total_net'])))<TOL
            if label=='no_liquidity':assert q==D('.006') and not fills and a['pending'] is not None
            else:assert q==0 and a['pending'] is None
            assert a['new_exposure_allowed'] is False;verified+=1
    market=r['market'];failed=market['failure_ms'];opposed=market['opposition_ms']
    event=next(e for e in market['events'] if e['kind']=='basis_invalidated')
    root=event['root']['candidate']
    assert root['side']*(raw[failed]['close']-D(root['protected']['price']))<0
    point=next(p for p in market['points'] if p['time_ms']==opposed)
    assert point['state']['root']['candidate']['formed_ms']>failed and point['support']['side']==1 and point['support']['support']
    result=dict(source_hashes='PASS',prior_inventory_and_peak_preserved='PASS',raw_open_execution='PASS',
        funding_order_and_inventory='PASS',independent_decimal_equity='PASS',verified_paths=verified,
        unfilled_exit_retains_position='PASS',market_failure_precedes_opposition=True,actual_orders=0)
    (OUT/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
