"""Fixed pre-entry target provenance; no target replacement or future PnL."""
import hashlib,json
from pathlib import Path
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
import numpy as np
from review_market_judgment_regimes import ROOT,CONFIG,DAY,MINUTE,load_rows,prepare,target_at,utc,stamp,jsonable,ExampleCosts
from build_zone_decision_cards import profile_context
from app.research.recovery.zone_excursions import observe_excursions
from app.research.recovery.round_trip_review import round_trip

OUT=ROOT/'reports/validation/target_provenance_20260920'
SCAN=ROOT/'reports/validation/six_case_entry_scan_20260920/review.json'
ZONE=ROOT/'reports/validation/volume_zone_review_v02_20260919/frozen_zones.json'
CACHE=ROOT/'data/historical/btcusdc_aggprofiles_20260919/histogram_50usdc_15min.npz'


def inspect(rows,cfg,t,case_start,zone):
    known=[r for r in rows if r['end_ms']<=t]
    p=prepare(known,case_start-16*DAY,t,cfg);mark=known[-1]['close'];target=target_at(p,t,-1,mark)
    candidates=[]
    for m,s in p['scales'].items():
        broken={e['pivot_id'] for e in s['observations']['events'] if e['kind']=='close_break' and e['available_ms']<=t}
        for pivot in s['observations']['pivots']:
            if pivot['kind']=='low' and pivot['available_ms']<=t and pivot['id'] not in broken and pivot['price']<mark:
                candidates.append(dict(minutes=m,**pivot,distance=mark-pivot['price']))
    candidates.sort(key=lambda p:p['distance'])
    assert candidates[0]['price']==target['price']==62966.6
    z=next(z for z in zone['zones'] if z['id']=='Z01');registered=stamp(zone['decision_utc'])
    block=[r for r in known if registered<=r['end_ms']<=t]
    path=observe_excursions(block,low=z['low'],high=z['high'])
    return dict(decision_ms=t,mark=mark,target=target,eligible_structural_targets=candidates,
        zone=z,zone_registration_ms=registered,zone_path=path,
        touches=[dict(time_ms=r['end_ms'],close=r['close']) for r in block if r['low']<=z['high'] and r['high']>=z['low']])


def main():
    scan=json.loads(SCAN.read_text());zone=json.loads(ZONE.read_text());cfg=json.loads(CONFIG.read_text())
    for p,h in scan['source_sha256'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h,p
    assert hashlib.sha256(CACHE.read_bytes()).hexdigest()==zone['source_sha256'][str(CACHE.relative_to(ROOT))]
    candidate=scan['selection']['first'];t=candidate['time_ms'];assert t==stamp('2026-08-16T16:09:00Z')
    case=next(c for c in scan['cases'] if c['label']==candidate['label']);rows,_=load_rows()
    evidence=inspect(rows,cfg,t,case['start_ms'],zone)
    assert evidence==inspect([r for r in rows if r['end_ms']<=t],cfg,t,case['start_ms'],zone)
    assert evidence['target']==candidate['target']
    target=evidence['eligible_structural_targets'][0];m=target['minutes'];end=target['pivot_bar_end_ms']
    # Check raw pivot and right-side confirmation independently of structural observer.
    def bar_low(end):return min(r['low'] for r in rows if end-m*MINUTE<r['end_ms']<=end)
    assert bar_low(end)==target['price'] and all(bar_low(end+i*m*MINUTE)>target['price'] for i in (-2,-1,1,2))
    assert target['available_ms']==end+2*m*MINUTE<=t
    lows=[r for r in rows if target['available_ms']<r['end_ms']<=t and r['low']<=target['price']]
    evidence['structural_target_retouches_since_confirmation']=lows
    cache_start=stamp('2026-06-01T00:00:00Z')
    with np.load(CACHE) as packed:
        hist=packed['hist'];offset=int(packed['offset'])
        profile=profile_context(hist,offset,cache_start,t,62750,62900)
        stop=(profile['cutoff_exclusive_ms']-cache_start)//(15*MINUTE)
        assert profile==profile_context(hist[:stop],offset,cache_start,t,62750,62900)
        for hours,v in profile['windows_hours'].items():
            window=hist[stop-int(hours)*4:stop]
            # Distinct column-first summation order over the declared interval.
            numerator=float(sum(window[:,i].sum() for i in range(62750//50-offset,62900//50-offset)))
            denominator=float(window.sum())
            assert np.isclose(100*numerator/denominator,v['share_pct'],rtol=1e-12)
    account_path=ROOT/cfg['account_config'];account=json.loads(account_path.read_text())
    costs=ExampleCosts(*(account[k] for k in ('fee','half_spread','slippage','tick','step','leverage')))
    quotes={str(price):round_trip(costs,side=-1,quantity='.006',entry_mark=evidence['mark'],exit_mark=price) for price in (62966.6,62900)}
    D=Decimal
    tick=D(account['tick']);spread=D(account['half_spread']);slip=D(account['slippage']);fee=D(account['fee'])
    def execution(mark,side):
        value=D(str(mark))*(1+side*spread)*(1+side*slip)
        return (value/tick).to_integral_value(rounding=ROUND_CEILING if side==1 else ROUND_FLOOR)*tick
    for price,quote in quotes.items():
        entry=execution(evidence['mark'],-1);exit_price=execution(price,1)
        net=(entry-exit_price)*D('.006')-(entry+exit_price)*D('.006')*fee
        assert net==quote['net']
    sources=dict(scan['source_sha256'])
    for p in (SCAN,ZONE,CACHE,CONFIG,account_path,Path(__file__),ROOT/'scripts/build_zone_decision_cards.py',ROOT/'app/research/recovery/zone_excursions.py'):
        sources[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
    result=dict(status='target_provenance_audit_not_target_approval',actual_orders=False,target_replaced=False,
        evidence=evidence,current_frozen_zone_profile=profile,conditional_quotes_not_fills=quotes,
        limitations=['profile cache checked by recorded hash; raw aggTrades not re-streamed in this audit',
            'fixed zone boundaries retained; no fresh zone ranking or strength approval',
            'price-only pivot does not establish traded-volume significance',
            'zone first formation timestamp unknown; registration time is not first formation'],
        checks=dict(source_integrity='PASS',price_prefix='PASS',profile_prefix='PASS',raw_pivot_and_confirmation='PASS',profile_arithmetic='PASS',independent_decimal_quotes='PASS'),source_sha256=sources)
    OUT.mkdir(exist_ok=True,parents=True);(OUT/'review.json').write_text(json.dumps(jsonable(result),ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(jsonable(dict(target=target,alternatives=evidence['eligible_structural_targets'][:5],profile=profile,quotes=quotes,zone_last_legs=evidence['zone_path']['completed_legs'][-3:],zone_open=evidence['zone_path']['open_leg'],last_touch=evidence['touches'][-1:])),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
