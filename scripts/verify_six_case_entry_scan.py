"""Independent raw-price and Decimal checks for the selected candidate."""
import csv,hashlib,io,json
from decimal import Decimal as D,ROUND_CEILING,ROUND_FLOOR
from pathlib import Path
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/six_case_entry_scan_20260920'


def main():
    r=json.loads((OUT/'review.json').read_text())
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in r['source_sha256'].items())
    account=json.loads((ROOT/'configs/research/first_candidate_case_trial.json').read_text())
    archive=ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as f:
        raw={int(b['open_time'])+60000:{k:D(b[k]) for k in ('open','high','low','close')} for b in csv.DictReader(io.TextIOWrapper(f))}
    candidates=[]
    for c in r['cases']:
        times=[p['time_ms'] for p in c['points']]
        assert times==sorted(set(times)) and set(range(c['start_ms'],c['end_ms']+1,900000))<=set(times)
        for p in c['points']:
            t=p['time_ms'];assert raw[t]['close']==D(str(p['mark']))
            assert D(p['result']['position']['quantity'])==0
            if p['result']['action']=='entry_candidate':candidates.append(dict(label=c['label'],**p))
    candidates.sort(key=lambda p:(p['time_ms'],p['label']))
    assert r['selection']['first']==(candidates[0] if candidates else None)
    assert r['selection']['candidate_count']==len(candidates)
    fee,spread,slip,tick,step,leverage=[D(account[k]) for k in ('fee','half_spread','slippage','tick','step','leverage')]
    def fill(mark,side):
        return (mark*(1+side*spread)*(1+side*slip)/tick).to_integral_value(rounding=ROUND_CEILING if side==1 else ROUND_FLOOR)*tick
    for p in candidates:
        t=p['time_ms'];side=p['support']['side'];assert side in (-1,1)
        root=p['state']['root']['candidate'];assert root['formed_ms']<=t and p['support']['support']
        rx=p['reaction'];target=p['target'];level=D(str(rx['price']))
        assert rx['available_ms']<rx['departed_ms']<t and rx['pivot_bar_end_ms']<=rx['available_ms']
        assert raw[t]['low']<=level<=raw[t]['high'] and side*(raw[t]['close']-level)>0
        assert target['available_ms']<=t and target['type']=='structural_price_not_volume_zone'
        mark=raw[t]['close'];entry=fill(mark,side);exit_price=fill(D(str(target['price'])),-side)
        probe=D('.006');net=side*probe*(exit_price-entry)-probe*(entry+exit_price)*fee
        assert net==D(p['result']['marginal_round_trip']['net']) and net>0
        # Enumerate executable quantities rather than repeat the capacity formula.
        allowed=[]
        for units in range(1,int(D(account['maximum_total_quantity'])/step)+1):
            q=units*step
            if q<D(account['minimum_quantity']) or q*entry<D(account['minimum_notional']) or q>D(account['assumed_liquidity_quantity']):continue
            if D(account['starting_equity'])-q*(mark/leverage+entry*fee)<D(account['reserve_margin']):continue
            stress=[side*q*(fill(mark-side*D(move),-side)-entry)-q*(entry+fill(mark-side*D(move),-side))*fee for move in account['stress_moves']]
            if min(stress)>=-D(account['initial_stress_budget']):allowed.append(q)
        assert max(allowed,default=D(0))==D(p['result']['quantity'])
    for x in r['conditional_add_reviews']:
        rx=x['reaction'];assert min(rx['available_ms'],rx['pivot_bar_end_ms'])<=candidates[0]['time_ms']
        assert x['result']['action']=='wait' and x['result']['reason']=='historical_marker_not_new_after_growth'
    checks=dict(source_hashes='PASS',chronological_selection='PASS',raw_reaction_and_quotes='PASS',
                independent_round_trip='PASS',enumerated_capacity='PASS',flat_candidate_not_automatic_addition='PASS',
                prior_and_prefix_checks=r['checks'],orders_generated=0,
                verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT/'verification.json').write_text(json.dumps(checks,indent=2)+'\n');print(json.dumps(checks))


if __name__=='__main__':main()
