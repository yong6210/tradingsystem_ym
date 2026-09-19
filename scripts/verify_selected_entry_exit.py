"""Audit entry-to-exit continuity with independent raw Decimal arithmetic."""
import csv,hashlib,io,json
from decimal import Decimal as D,ROUND_CEILING,ROUND_FLOOR
from pathlib import Path
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/validation/selected_entry_exit_20260920'


def main():
    r=json.loads((OUT/'review.json').read_text());old=json.loads((ROOT/r['config']['source']).read_text())
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in r['source_sha256'].items())
    archive=ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as f:
        raw={int(b['open_time'])+60000:{k:D(b[k]) for k in ('open','close')} for b in csv.DictReader(io.TextIOWrapper(f))}
    funding=json.loads((ROOT/'data/historical/btcusdc_public_20260917/funding_history.json').read_text())
    verified=0
    for label,group in r['paths'].items():
        original=old['paths'][label];cfg=original['account'];entry=original['entry']['fill'];start=original['entry_time_ms']
        fee,spread,slip,tick,lev=[D(cfg[k]) for k in ('fee','half_spread','slippage','tick','leverage')]
        sell=(raw[start+60000]['open']*(1-spread)*(1-slip)/tick).to_integral_value(rounding=ROUND_FLOOR)*tick
        assert D(entry['execution_price'])==sell and D(entry['action_fee'])==D(entry['after']['quantity'])*sell*fee
        ask=lambda mark:(mark*(1+spread)*(1+slip)/tick).to_integral_value(rounding=ROUND_CEILING)*tick
        for policy,p in group.items():
            previous=original['continuation'];assert p['initial']==previous['summary']['final']['position']
            assert p['initial_state']==previous['summary']['final']
            assert p['full_states'][:len(previous['states'])]==previous['states']
            q=D(entry['after']['quantity']);avg=D(entry['execution_price']);gross=D(0);paid=D(entry['action_fee']);remain=paid
            capital=D(cfg['starting_equity']);cash=capital+q*avg-paid;peak=capital;maximum=D(0);exposure=D(0)
            states=p['full_states'];end=states[-1]['time_ms'];ledger=p['full_ledger']
            assert [s['time_ms'] for s in states]==list(range(start+60000,end+1,60000))
            fills=[e for e in ledger if e['kind']=='fill']
            events=sorted([(f['fundingTime'],0,f) for f in funding if start<f['fundingTime']<=end]+[(e['time_ms'],1,e) for e in fills],key=lambda x:(x[0],x[1]))
            index=0;expected_funding=[]
            for s in states:
                t=s['time_ms']
                while index<len(events) and (events[index][0]<t or (events[index][0]==t and events[index][1]==0)):
                    et,kind,e=events[index];index+=1
                    if kind==0:
                        if q:
                            payment=-q*D(e['markPrice'])*D(e['fundingRate']);paid+=payment;remain+=payment;cash-=payment
                            expected_funding.append((et,q,payment))
                    else:
                        amount=D(e['quantity']);price=ask(raw[et+60000]['open']);cost=amount*price*fee
                        assert e['decision_ms']<et and D(e['price'])==price and D(e['fee'])==cost and 0<amount<=q
                        gross+=amount*(avg-price);paid+=cost;cash-=amount*price+cost;remain=remain*(q-amount)/q;q-=amount
                mark=raw[t]['close'];net=gross-paid+q*(avg-mark);equity=capital+net
                assert abs(cash-q*mark-equity)<D('1e-9')
                peak=max(peak,equity);dd=peak-equity;maximum=max(maximum,dd);exposure+=q/60
                expected=dict(total_net=net,net_if_closed=gross-paid+q*(avg-ask(mark))-q*ask(mark)*fee,
                              equity=equity,free_margin_proxy=equity-q*mark/lev,peak_equity=peak,drawdown=dd)
                assert all(abs(D(s[k])-v)<D('1e-9') for k,v in expected.items())
                pos=s['position'];assert D(pos['quantity'])==q and D(pos['realized_gross'])==gross and D(pos['paid_costs'])==paid
                assert abs(D(pos['remaining_costs'])-remain)<D('1e-9')
                assert (D(pos['average'])==avg) if q else pos['average'] is None
            assert [(e['time_ms'],D(e['quantity']),D(e['payment'])) for e in ledger if e['kind']=='funding']==expected_funding
            assert p['continuation']['pending'] is None and q==0
            assert D(p['continuation']['summary']['cumulative_max_close_drawdown'])==maximum
            assert abs(D(p['full_exposure_btc_hours'])-exposure)<D('1e-9')
            verified+=1
    for label,p in r['cancelled_entries'].items():
        assert old['paths'][label]['entry']['fill'] is None and old['paths'][label]['continuation'] is None
        assert not p['inventory_created'] and not p['exit_simulated'] and label not in r['paths']
    low=r['paths']['liquidity_003']
    def fills(policy):return [(e['time_ms'],e['quantity'],e['price']) for e in low[policy]['continuation']['ledger'] if e['kind']=='fill']
    assert D(low['exit_on_basis_failure']['initial']['quantity'])==D('.001')
    assert fills('exit_on_basis_failure')==fills('half_on_failure_rest_on_opposition')
    market=r['market'];e=next(e for e in market['events'] if e['kind']=='basis_invalidated')
    assert e['root']['candidate']['side']*(raw[e['time_ms']]['close']-D(str(e['root']['candidate']['protected']['price'])))<0
    opposite=next(p for p in market['points'] if p['time_ms']==market['opposition_ms'])
    assert opposite['support']['side']==1 and opposite['state']['root']['candidate']['formed_ms']>market['failure_ms']
    checks=dict(source_hashes='PASS',entire_original_prefix='PASS',continuous_timeline='PASS',independent_full_cash_and_ledger='PASS',
                exact_funding_timestamps='PASS',carry_peak_and_drawdown='PASS',cancelled_entries_stay_no_trade='PASS',
                minimum_step_half_becomes_full_exit='PASS',market_failure_then_opposition='PASS',paths=verified,
                verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT/'verification.json').write_text(json.dumps(checks,indent=2)+'\n');print(json.dumps(checks))


if __name__=='__main__':main()
