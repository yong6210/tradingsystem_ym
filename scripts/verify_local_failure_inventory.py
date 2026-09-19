"""Raw Decimal audit independent of the position arithmetic used by the review."""
import csv, hashlib, io, json
from decimal import Decimal as D, ROUND_CEILING
from pathlib import Path
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/local_failure_inventory_20260919'


def main():
    r=json.loads((OUT/'review.json').read_text())
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in r['source_sha256'].items())
    cfg=json.loads((ROOT/r['registered_config']['account_config']).read_text())
    archive=ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as f:
        raw={int(x['open_time'])+60000:{k:D(x[k]) for k in ('open','close','low')} for x in csv.DictReader(io.TextIOWrapper(f))}
    funding=json.loads((ROOT/'data/historical/btcusdc_public_20260917/funding_history.json').read_text())
    start=r['initial_state']['time_ms'];end=next(iter(r['policies'].values()))['states'][-1]['time_ms']
    assert min(t for t,b in raw.items() if start<t<=end and b['close']>D(r['triggers']['local_level']))==r['triggers']['local_failure_ms']
    assert min(t for t,b in raw.items() if start<t<=end and b['low']<=D(r['registered_config']['target_mark']))==r['triggers']['target_ms']
    market=json.loads((ROOT/'reports/validation/failed_break_label_20260919/review.json').read_text())
    assert min(p['time_ms'] for p in market['points'] if p['time_ms']>start and p['time_ms']%900000==0 and p['support']['side']!=-1)==r['triggers']['support_loss_ms']
    groups=[('base',r['policies'])]+list(r['sensitivities'].items());paths=0
    for label,group in groups:
        slip=D('.0005') if label=='slippage_5bp' else D(cfg['slippage'])
        fee,spread,tick,leverage=[D(cfg[k]) for k in ('fee','half_spread','tick','leverage')]
        ask=lambda mark:(mark*(1+spread)*(1+slip)/tick).to_integral_value(rounding=ROUND_CEILING)*tick
        for name,a in group.items():
            initial=r['initial_position'];q=D(initial['quantity']);avg=D(initial['average']);gross=D(initial['realized_gross']);paid=D(initial['paid_costs']);remaining=D(initial['remaining_costs'])
            peak=D(r['initial_state']['peak_equity']);maximum=D(r['prior_max_drawdown']);extension=D(0);exposure=D(0)
            fills=[e for e in a['ledger'] if e['kind']=='fill']
            events=sorted([(f['fundingTime'],0,f) for f in funding if start<f['fundingTime']<=end]+[(e['time_ms'],1,e) for e in fills],key=lambda x:(x[0],x[1]));idx=0;expected_funding=[]
            for s in a['states']:
                t=s['time_ms']
                while idx<len(events) and (events[idx][0]<t or (events[idx][0]==t and events[idx][1]==0)):
                    et,kind,e=events[idx];idx+=1
                    if kind==0:
                        if q:
                            payment=-q*D(e['markPrice'])*D(e['fundingRate']);paid+=payment;remaining+=payment
                            expected_funding.append((et,str(q),payment))
                    else:
                        amount=D(e['quantity']);price=ask(raw[et+60000]['open']);cost=amount*price*fee
                        assert e['decision_ms']<et and D(e['price'])==price and D(e['fee'])==cost
                        assert 0<amount<=q and amount%D(cfg['step'])==0
                        gross+=amount*(avg-price);paid+=cost;remaining*=((q-amount)/q);q-=amount
                mark=raw[t]['close'];net=gross-paid+q*(avg-mark);equity=D(initial['starting_equity'])+net
                peak=max(peak,equity);dd=peak-equity;maximum=max(maximum,dd);extension=max(extension,dd);exposure+=q/60
                values=dict(total_net=net,net_if_closed=gross-paid+q*(avg-ask(mark))-q*ask(mark)*fee,equity=equity,
                            free_margin_proxy=equity-q*mark/leverage,peak_equity=peak,drawdown=dd)
                assert all(abs(D(s[k])-v)<D('1e-9') for k,v in values.items())
                assert D(s['position']['quantity'])==q and abs(D(s['position']['remaining_costs'])-remaining)<D('1e-9')
                assert (D(s['position']['average'])==avg) if q else s['position']['average'] is None
                assert D(s['position']['realized_gross'])==gross and D(s['position']['paid_costs'])==paid
            actual_funding=[(e['time_ms'],e['quantity'],D(e['payment'])) for e in a['ledger'] if e['kind']=='funding']
            assert actual_funding==expected_funding
            assert D(a['summary']['cumulative_max_close_drawdown'])==maximum and D(a['summary']['extension_max_close_drawdown'])==extension
            assert abs(D(a['summary']['exposure_btc_hours'])-exposure)<D('1e-9')
            for e in a['ledger']:
                if e['kind']=='obligation_activated':
                    ob=e['obligation'];required=(D(ob['base_quantity'])*D('.5')/D(cfg['step'])).to_integral_value(rounding=ROUND_CEILING)*D(cfg['step'])
                    assert D(ob['required'])==required
                    if ob['kind'] in a['obligations']['completed']:
                        assert sum(D(f['quantity']) for f in fills if f['reason']==ob['kind'])>=required
            if label=='no_liquidity':
                assert q==D('.012') and not fills and a['pending'] is not None and 'target' in a['obligations']['waiting']
            else:
                assert q==D('.006' if name=='target_only' else '.003') and a['pending'] is None
            paths+=1
    verification=dict(source_hashes='PASS',raw_triggers='PASS',raw_execution_and_funding='PASS',independent_account='PASS',
                      remaining_quantity_half='PASS',unfilled_obligations_retained='PASS',paths=paths,
                      verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT/'verification.json').write_text(json.dumps(verification,indent=2)+'\n');print(json.dumps(verification))


if __name__=='__main__':main()
