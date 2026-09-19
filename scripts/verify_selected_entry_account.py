"""Independent raw-open, capacity and complete Decimal ledger audit."""
import csv,hashlib,io,json
from decimal import Decimal as D,ROUND_CEILING,ROUND_FLOOR
from pathlib import Path
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/validation/selected_entry_account_20260920'


def main():
    r=json.loads((OUT/'review.json').read_text())
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in r['source_sha256'].items())
    archive=ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as f:
        raw={int(b['open_time'])+60000:{k:D(b[k]) for k in ('open','close','low')} for b in csv.DictReader(io.TextIOWrapper(f))}
    funding=json.loads((ROOT/'data/historical/btcusdc_public_20260917/funding_history.json').read_text())
    decision=r['candidate']['time_ms'];opening=r['opening']['time_ms'];mark=raw[opening+60000]['open']
    assert opening==decision+60000 and D(str(r['opening']['mark']))==mark
    assert r['opening']['support']['side']==-1 and mark<=D(str(r['candidate']['reaction']['price']))
    target=D(r['config']['target_mark']);assert D(str(r['candidate']['target']['price']))==target
    assert min(t for t,b in raw.items() if opening<t and b['low']<=target)==r['target_hit_ms']
    completed=cancelled=0
    for label,path in r['paths'].items():
        cfg=path['account'];fee,spread,slip,tick,step,lev=[D(cfg[k]) for k in ('fee','half_spread','slippage','tick','step','leverage')]
        def fill(price,side):return (price*(1+side*spread)*(1+side*slip)/tick).to_integral_value(rounding=ROUND_CEILING if side==1 else ROUND_FLOOR)*tick
        sell=fill(mark,-1);buy=fill(target,1);maximum=D(r['candidate']['result']['quantity']);allowed=[]
        for i in range(1,int(maximum/step)+1):
            q=i*step
            if q>D(cfg['assumed_liquidity_quantity']) or q<D(cfg['minimum_quantity']) or q*sell<D(cfg['minimum_notional']):continue
            if D(cfg['starting_equity'])-q*(mark/lev+sell*fee)<D(cfg['reserve_margin']):continue
            stress=[q*(sell-fill(mark+D(d),1))-q*(sell+fill(mark+D(d),1))*fee for d in cfg['stress_moves']]
            if min(stress)>=-D(cfg['initial_stress_budget']):allowed.append(q)
        q=max(allowed,default=D(0));net=q*(sell-buy)-q*(sell+buy)*fee
        assert D(path['entry']['capacity']['capacity_quantity'])==q
        if not q or net<=0:
            assert path['entry']['fill'] is None and path['continuation'] is None
            assert path['entry']['reason']==('opening_no_capacity' if not q else 'opening_no_positive_net_room')
            assert D(path['entry']['unfilled_cancelled'])==maximum;cancelled+=1;continue
        entry=path['entry']['fill'];assert D(entry['execution_price'])==sell and D(entry['action_fee'])==q*sell*fee
        assert D(entry['after']['quantity'])==q and D(path['entry']['unfilled_cancelled'])==maximum-q
        avg=sell;gross=D(0);paid=q*sell*fee;remaining=paid;cash=D(cfg['starting_equity'])+q*sell-paid;peak=D(cfg['starting_equity']);ddmax=D(0);exposure=D(0)
        a=path['continuation'];end=a['states'][-1]['time_ms'];fills=[e for e in a['ledger'] if e['kind']=='fill']
        assert [s['time_ms'] for s in a['states']]==list(range(opening+60000,end+1,60000))
        events=sorted([(f['fundingTime'],0,f) for f in funding if opening<f['fundingTime']<=end]+[(e['time_ms'],1,e) for e in fills],key=lambda x:(x[0],x[1]))
        idx=0;expected_funding=[]
        for s in a['states']:
            t=s['time_ms']
            while idx<len(events) and (events[idx][0]<t or (events[idx][0]==t and events[idx][1]==0)):
                et,kind,e=events[idx];idx+=1
                if kind==0:
                    payment=-q*D(e['markPrice'])*D(e['fundingRate']);paid+=payment;remaining+=payment;cash-=payment
                    if q:expected_funding.append((et,q,payment))
                else:
                    amount=D(e['quantity']);price=fill(raw[et+60000]['open'],1);cost=amount*price*fee
                    assert e['decision_ms']<et and D(e['price'])==price and D(e['fee'])==cost and 0<amount<=q
                    gross+=amount*(avg-price);paid+=cost;remaining=remaining*(q-amount)/q;q-=amount;cash-=amount*price+cost
            close=raw[t]['close'];net=gross-paid+q*(avg-close);equity=D(cfg['starting_equity'])+net
            assert abs(cash-q*close-equity)<D('1e-9')
            peak=max(peak,equity);dd=peak-equity;ddmax=max(ddmax,dd);exposure+=q/60
            expected=dict(total_net=net,net_if_closed=gross-paid+q*(avg-fill(close,1))-q*fill(close,1)*fee,
                          equity=equity,free_margin_proxy=equity-q*close/lev,peak_equity=peak,drawdown=dd)
            assert all(abs(D(s[k])-v)<D('1e-9') for k,v in expected.items())
            p=s['position'];assert D(p['quantity'])==q and D(p['average'])==avg and D(p['realized_gross'])==gross and D(p['paid_costs'])==paid
            assert abs(D(p['remaining_costs'])-remaining)<D('1e-9')
        assert [(e['time_ms'],D(e['quantity']),D(e['payment'])) for e in a['ledger'] if e['kind']=='funding']==expected_funding
        assert D(a['summary']['cumulative_max_close_drawdown'])==ddmax and abs(D(a['summary']['exposure_btc_hours'])-exposure)<D('1e-9')
        plans=[e['obligation'] for e in a['ledger'] if e['kind']=='obligation_activated']
        assert len(plans)==1 and plans[0]['kind']=='target'
        required=(D(plans[0]['base_quantity'])/2/step).to_integral_value(rounding=ROUND_CEILING)*step
        assert D(plans[0]['required'])==required and sum(D(e['quantity']) for e in fills if e['reason']=='target')==required
        assert a['pending'] is None and all(x['result']['action']!='add_candidate' for x in path['addition_reviews'])
        completed+=1
    checks=dict(source_hashes='PASS',later_raw_open='PASS',independent_capacity_and_cost_gate='PASS',
                independent_cash_and_position='PASS',half_actual_quantity='PASS',no_addition_or_retry='PASS',
                completed_paths=completed,cancelled_entries=cancelled,prior_and_prefix_checks=r['checks'],
                verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT/'verification.json').write_text(json.dumps(checks,indent=2)+'\n');print(json.dumps(checks))


if __name__=='__main__':main()
