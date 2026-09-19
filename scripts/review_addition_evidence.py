"""Audit two existing additions without changing signal, sizing or target rules."""
import hashlib,json
from pathlib import Path
from review_market_judgment_regimes import ROOT,load_rows,MINUTE,utc,stamp,jsonable
from review_first_candidate_account import contacts

SOURCE=ROOT/'reports/validation/first_candidate_account_20260919/review.json'
OUT=ROOT/'reports/validation/addition_evidence_20260920'


def main():
    old=json.loads(SOURCE.read_text());sources=dict(old['source_sha256'])
    for p,h in sources.items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h,p
    rows,_=load_rows();aug=[r for r in rows if r['end_ms']>stamp('2026-08-01T00:00:00Z')]
    increases=[f for f in old['ledger'] if f['kind']=='fill' and f['action']=='increase']
    assert len(increases)==3;records=[]
    for fill in increases[1:]:
        t=fill['decision_ms'];decision=next(d for d in old['decisions'] if d['kind']=='increase' and d['time_ms']==t)
        prior=max((f for f in increases if f['time_ms']<t),key=lambda f:f['time_ms']);b=decision['basis'];known=[r for r in aug if r['end_ms']<=t]
        observed=contacts(known,t);assert b in observed[t]
        assert contacts(aug,t)==observed
        assert b['pivot_bar_end_ms']>prior['decision_ms'] and b['available_ms']>prior['decision_ms']
        # Direct raw OHLC audit of strict 15-minute pivot and first post-departure touch.
        def high(end):return max(r['high'] for r in known if end-15*MINUTE<r['end_ms']<=end)
        pivot=b['pivot_bar_end_ms'];price=b['price']
        assert high(pivot)==price and all(high(pivot+i*15*MINUTE)<price for i in (-2,-1,1,2))
        assert b['available_ms']==pivot+30*MINUTE
        post=[r for r in known if b['available_ms']<r['end_ms']<=t]
        departure=next(r for r in post if r['high']<price);assert departure['end_ms']==b['departed_ms']
        touch=next(r for r in post if r['end_ms']>b['departed_ms'] and r['low']<=price<=r['high'])
        assert touch['end_ms']==t and touch['close']<price
        assert all(r['close']<=price for r in post)
        reductions=[f for f in old['ledger'] if f['kind']=='fill' and f['action']!='increase' and prior['time_ms']<f['time_ms']<t]
        root=next(d for d in reversed(old['decisions']) if d['kind']=='direction_review' and d['time_ms']<=t)
        records.append(dict(decision=decision,fill=fill,previous_actual_growth=prior,basis_times_utc={k:utc(b[k]) for k in ('pivot_bar_end_ms','available_ms','departed_ms')},
            first_touch=touch,departure=departure,between_departure_and_touch_min=min(r['low'] for r in post if b['departed_ms']<=r['end_ms']<t),
            intervening_reductions=reductions,latest_reduction_precedes_formation=not reductions or max(f['time_ms'] for f in reductions)<pivot,
            direction_review=root,checks=dict(newer_than_prior_growth='PASS',raw_confirmed_pivot='PASS',first_departure_and_return='PASS',causal_contacts='PASS')))
    current_path=ROOT/'reports/validation/six_case_entry_scan_20260920/review.json';current=json.loads(current_path.read_text())
    for p,h in current['source_sha256'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h,p
    comparison=current['conditional_add_reviews'];assert comparison[0]['result']['reason']=='historical_marker_not_new_after_growth'
    stale=next(d for d in old['decisions'] if d['kind']=='add_rejected' and d['time_ms']==stamp('2026-08-16T16:12:00Z'))
    assert stale['reason']=='historical_landmark_not_new_after_last_growth'
    for p in (SOURCE,current_path,Path(__file__),ROOT/'scripts/review_market_judgment_regimes.py'):
        sources[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
    result=dict(status='temporal_separation_verified_economic_independence_unproven',actual_orders=False,rules_changed=False,
        additions=records,old_account_stale_rejection=stale,current_account_comparison=comparison,
        limitations=['old account uses its 60-minute trial direction, not current general main-direction approval',
            'fresh after last actual growth decision is not fresh after last reduction',
            'separate pivot/departure/first return is not proof of independent market information'],source_sha256=sources)
    OUT.mkdir(exist_ok=True,parents=True);(OUT/'review.json').write_text(json.dumps(jsonable(result),ensure_ascii=False,indent=2)+'\n')
    for r in records:
        print(utc(r['decision']['time_ms']),r['basis_times_utc'],'min',r['between_departure_and_touch_min'],'reductions',[(utc(f['time_ms']),f['after']['quantity']) for f in r['intervening_reductions']],flush=True)

if __name__=='__main__':main()
