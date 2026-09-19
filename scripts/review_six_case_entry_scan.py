"""Chronological admission scan over the already selected development cases."""
import hashlib,json
from collections import Counter
from copy import deepcopy
from pathlib import Path

from review_oneway_admission import reactions_for
from review_market_judgment_regimes import (
    ROOT,CONFIG,MINUTE,DAY,load_rows,prepare,snapshot,stable_context,target_at,
    action_review,utc,PositionExample,ExampleCosts,jsonable,
)
from review_market_basis_revision import revise_basis,current_support,with_bounds
from review_market_direction_continuity import advance,anchor_bars

SCAN=ROOT/'configs/research/six_case_entry_scan.json'
OUT=ROOT/'reports/validation/six_case_entry_scan_20260920'


def scan_case(rows,cfg,account,old,cutoff):
    start=old['start_ms'];known=[r for r in rows if r['end_ms']<=cutoff]
    prepared=[prepare(known,start-d*DAY,cutoff,cfg) for d in cfg['history_days']]
    reactions=reactions_for(prepared[-1]['rows'],cutoff)
    times=sorted(set(range(start,cutoff+1,15*MINUTE))|
                 {t for group in reactions.values() for t in group if start<=t<=cutoff}|
                 {p['time_ms'] for p in old['points'] if p['time_ms']<=cutoff})
    state=deepcopy(old['points'][0]['updated_only']);assert state['last_ms']==start
    prices={r['end_ms']:r['close'] for r in known}
    position=PositionExample(1,0,None,0,0,0,account['starting_equity'])
    costs=ExampleCosts(*(account[k] for k in ('fee','half_spread','slippage','tick','step','leverage')))
    points=[];events=[]
    for t in times:
        views=[snapshot(p,t) for p in prepared]
        if t>start:
            state,e=advance(state,t=t,context=stable_context(views),bars=anchor_bars(prepared[-1],state,t))
            if e:events.append(e)
            state,e=revise_basis(state,views,t)
            if e:events.append(e)
        support=current_support(state,with_bounds(views,prepared,state,t),t)
        direction=support['side'] or 1
        candidates=reactions[direction].get(t,[])
        fresh=[p for p in candidates if min(p['pivot_bar_end_ms'],p['available_ms'])>start]
        reaction=(fresh or candidates or [None])[0]
        target=target_at(prepared[-1],t,direction,prices[t])
        result=action_review(context=dict(side=support['side'],root=state['root']),position=position,costs=costs,
            mark=prices[t],t=t,account=account,reaction=reaction,target=target,last_growth=start)
        points.append(dict(time_ms=t,utc=utc(t),mark=prices[t],state=deepcopy(state),support=support,
                           reactions={str(s):v.get(t,[]) for s,v in reactions.items()},reaction=reaction,target=target,result=result))
    return dict(label=old['label'],start_ms=start,end_ms=cutoff,points=points,events=events)


def main():
    spec=json.loads(SCAN.read_text());cfg=json.loads(CONFIG.read_text());account_path=ROOT/cfg['account_config'];account=json.loads(account_path.read_text())
    old_path=ROOT/spec['case_source'];prior=json.loads(old_path.read_text())
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in prior['source_sha256'].items())
    rows,sources=load_rows();cases=[];candidates=[]
    originals=sorted([c for c in prior['cases'] if c['label'] in spec['labels']],key=lambda c:c['start_ms'])
    assert len(originals)==len(spec['labels'])==6
    for old in originals:
        case=scan_case(rows,cfg,account,old,old['end_ms'])
        bytime={p['time_ms']:p for p in case['points']}
        for p in old['points']:
            assert bytime[p['time_ms']]['state']==p['updated_only']
            assert bytime[p['time_ms']]['support']==p['guarded']
        hits=[p for p in case['points'] if p['result']['action']=='entry_candidate']
        for t in sorted({old['start_ms'],old['end_ms']}|{p['time_ms'] for p in hits}):
            prefix=scan_case([b for b in rows if b['end_ms']<=t],cfg,account,old,t)
            assert prefix['points']==[p for p in case['points'] if p['time_ms']<=t]
            assert prefix['events']==[e for e in case['events'] if e['time_ms']<=t]
        case['reason_counts']=dict(Counter(p['result']['reason'] for p in case['points']))
        case['candidate_times']=[p['time_ms'] for p in hits]
        candidates.extend(dict(label=old['label'],**p) for p in hits);cases.append(case)
        print(old['label'],case['candidate_times'],case['reason_counts'],flush=True)
    candidates.sort(key=lambda p:(p['time_ms'],p['label']))
    conditional_add_reviews=[]
    if candidates:
        first=candidates[0]
        # A quote-based position scenario only: no assumed execution, PnL path or new fill.
        hypothetical=first['result']['capacity']['review']['after']
        costs=ExampleCosts(*(account[k] for k in ('fee','half_spread','slippage','tick','step','leverage')))
        for p in candidates[1:]:
            if p['label']!=first['label']:continue
            review=action_review(context=dict(side=p['support']['side'],root=p['state']['root']),
                position=hypothetical,costs=costs,mark=p['mark'],t=p['time_ms'],account=account,
                reaction=p['reaction'],target=first['target'],last_growth=first['time_ms'])
            conditional_add_reviews.append(dict(time_ms=p['time_ms'],utc=p['utc'],reaction=p['reaction'],result=review,
                interpretation='conditional_position_at_first_decision_quote_not_an_executed_trade'))
    selection=dict(criterion=spec['selection'],candidate_count=len(candidates),first=candidates[0] if candidates else None,
                   no_outcome_filter=True,actual_orders=0,new_exposure_allowed=False)
    sources += [SCAN,CONFIG,account_path,old_path,Path(__file__),ROOT/'scripts/review_oneway_admission.py',
                ROOT/'scripts/review_market_judgment_regimes.py',ROOT/'scripts/review_market_basis_revision.py',
                ROOT/'scripts/review_market_direction_continuity.py',ROOT/'scripts/review_first_candidate_account.py']
    sources += [ROOT/'app/research/recovery'/p for p in ('protected_structure.py','structure_review.py','position_alternatives.py',
               'recovery_capacity_review.py','round_trip_review.py','campaign_recovery_review.py','models.py')]
    report=dict(config=spec,cases=cases,selection=selection,conditional_add_reviews=conditional_add_reviews,
                checks=dict(previous_points='PASS',truncated_rebuild='PASS'),
                source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'review.json').write_text(json.dumps(jsonable(report),ensure_ascii=False,indent=2)+'\n')
    (OUT/'selection.json').write_text(json.dumps(jsonable(selection),ensure_ascii=False,indent=2)+'\n')
    lines=['# 여섯 선정 날짜의 진입 후보 심사','','각 날짜의 시작 상태를 그대로 이월한 무포지션 심사다. 날짜 사이 거래·손익을 연결하지 않았다.','',
           '| 날짜 UTC | 기존 라벨 | 후보 시각 UTC | 보류 이유 집계 |','| --- | --- | --- | --- |']
    for c in cases:lines.append(f"| {utc(c['start_ms'])} | {c['label']} | {', '.join(utc(t) for t in c['candidate_times']) or '없음'} | {c['reason_counts']} |")
    lines+=['','최초 후보: '+(candidates[0]['utc'] if candidates else '없음'),'','후보는 시험 심사 결과이며 체결·운영 승인·전략 채택이 아니다.','']
    (OUT/'review.md').write_text('\n'.join(lines))
    print(json.dumps(jsonable(selection),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
