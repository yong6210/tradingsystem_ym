"""Read-only paired-structure diagnostic; preserves every baseline direction."""
import hashlib,json
from pathlib import Path
from review_market_judgment_regimes import ROOT,CONFIG,DAY,MINUTE,load_rows,prepare,snapshot,signature,utc
from review_market_basis_revision import identity

DOC=ROOT/'docs/research/STRUCTURE_ROLE_DIAGNOSTIC_TRIAL.md'
OUT=ROOT/'reports/validation/structure_role_diagnostic_20260920'
SCAN=ROOT/'reports/validation/six_case_entry_scan_20260920/review.json'
PRIOR=ROOT/'reports/validation/market_basis_revision_20260919/review.json'


def contains(a,b):
    return (a['candidate']['prior_reaction']['pivot_bar_end_ms']<b['candidate']['prior_reaction']['pivot_bar_end_ms'] and
        all(a['low']<=b['candidate'][k]['price']<=a['high'] for k in ('prior_reaction','broken','protected')))


def diagnostic(views):
    observed=[]
    for v in views:
        groups={}
        for n in v['nodes']:
            c=n['candidate']
            if c and c['status']=='active':groups.setdefault(signature(c),[]).append(n)
        active=[max(g,key=lambda n:n['candidate']['formed_ms']) for g in groups.values()]
        pairs={}
        for a in active:
            for b in active:
                if a['minutes']==b['minutes'] or a['candidate']['side']!=b['candidate']['side']:continue
                if contains(a,b) and b['candidate']['protected']['pivot_bar_end_ms']>a['candidate']['protected']['pivot_bar_end_ms']:
                    pairs[(identity(a),identity(b))]=dict(root=a,support=b)
        observed.append((pairs,active))
    common=set(observed[0][0]).intersection(observed[1][0]);result=[]
    for key in sorted(common):
        p=observed[0][0][key];side=p['root']['candidate']['side'];opposition=[]
        for i,(pairs,active) in enumerate(observed):
            a=pairs[key]['root']
            opposition.append([dict(node=n,outer=contains(n,a)) for n in active if n['candidate']['side']!=side])
        result.append(dict(pair_id=hashlib.sha256(repr(key).encode()).hexdigest()[:16],side=side,**p,opposition_by_history=opposition))
    return dict(common_pairs=result,history_pair_counts=[len(x[0]) for x in observed],
        interpretation='observed_structure_connection_not_main_direction_or_entry_permission')


def main():
    cfg=json.loads(CONFIG.read_text());scan=json.loads(SCAN.read_text());prior=json.loads(PRIOR.read_text())
    sources={}
    for source in (scan,prior):
        for path,h in source['source_sha256'].items():
            actual=hashlib.sha256((ROOT/path).read_bytes()).hexdigest();assert actual==h,path;sources[path]=h
    originals=[next(c for c in prior['cases'] if c['label']=='original_nine')]+scan['cases']
    rows,_=load_rows();results=[]
    for c in originals:
        start,end=c['start_ms'],c['end_ms'];prepared=[prepare(rows,start-d*DAY,end,cfg) for d in cfg['history_days']]
        points=[];first={}
        for old in c['points']:
            t=old['time_ms'];views=[snapshot(p,t) for p in prepared];diag=diagnostic(views)
            state=old.get('state',old.get('updated_only'));support=old.get('support',old.get('guarded'))
            for v in views:
                for n in v['nodes']:
                    if n['candidate']:
                        assert n['candidate']['formed_ms']<=t
                        assert all(n['candidate'][k]['available_ms']<=t for k in ('prior_reaction','broken','protected'))
            point=dict(time_ms=t,utc=utc(t),baseline_state=state,baseline_support=support,views=views,diagnostic=diag)
            points.append(point)
            for pair in diag['common_pairs']:first.setdefault(pair['pair_id'],dict(time_ms=t,pair=pair))
        episodes=[]
        for pid,item in first.items():
            t=item['time_ms'];pair=item['pair'];failures={}
            for role in ('root','support'):
                n=pair[role];cand=n['candidate']
                bars=prepared[-1]['scales'][n['minutes']]['bars']
                fail=next((b for b in bars if t<b['end_ms']<=end and cand['side']*(b['close']-cand['protected']['price'])<0),None)
                failures[role]=None if fail is None else dict(time_ms=fail['end_ms'],utc=utc(fail['end_ms']),close=fail['close'],protected=cand['protected']['price'])
            episodes.append(dict(pair_id=pid,first_observed_ms=t,first_observed_utc=utc(t),pair=pair,
                retrospective_followup=failures,followup_end_ms=end,not_an_independent_trade=True))
        chosen={points[0]['time_ms'],points[-1]['time_ms']}
        for predicate in (lambda p:bool(p['diagnostic']['common_pairs']),lambda p:any(o['outer'] for pair in p['diagnostic']['common_pairs'] for group in pair['opposition_by_history'] for o in group)):
            p=next((p for p in points if predicate(p)),None)
            if p:chosen.add(p['time_ms'])
        for t in sorted(chosen):
            known=[r for r in rows if r['end_ms']<=t]
            truncated=[snapshot(prepare(known,start-d*DAY,t,cfg),t) for d in cfg['history_days']]
            expected=next(p for p in points if p['time_ms']==t)
            assert truncated==expected['views'] and diagnostic(truncated)==expected['diagnostic']
        summary=dict(points=len(points),connected_points=sum(bool(p['diagnostic']['common_pairs']) for p in points),
            opposed_points=sum(any(o['outer'] for pair in p['diagnostic']['common_pairs'] for group in pair['opposition_by_history'] for o in group) for p in points),
            connections_while_baseline_uncertain=sum(p['baseline_support']['side'] is None and bool(p['diagnostic']['common_pairs']) for p in points),
            distinct_pairs=len(episodes),pairs_with_support_failure=sum(e['retrospective_followup']['support'] is not None for e in episodes))
        results.append(dict(label=c['label'],start_ms=start,end_ms=end,points=points,episodes=episodes,summary=summary,prefix_checkpoints=sorted(chosen)))
        print(c['label'],summary,flush=True)
    for p in (DOC,CONFIG,Path(__file__),SCAN,PRIOR):sources[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
    report=dict(status='diagnostic_not_approved',actual_orders=False,new_exposure_allowed=False,holdout=False,
        checks=dict(available_evidence='PASS',truncated_snapshots='PASS'),cases=results,source_sha256=sources)
    OUT.mkdir(exist_ok=True,parents=True);(OUT/'review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lines=['# 構造 역할 진단 결과'.replace('構造','구조'),'','연결은 방향·진입 승인이 아니다. 사후 국소 실패를 당시 판정에 넣지 않는다.','',
        '| 사례 | 관측 시점 | 연결 있음 | 외곽 충돌 | 기존 미판정 중 연결 | 서로 다른 연결 / 후속 지지 실패 |','| --- | ---: | ---: | ---: | ---: | --- |']
    for c in results:
        s=c['summary'];lines.append(f"| {c['label']} | {s['points']} | {s['connected_points']} | {s['opposed_points']} | {s['connections_while_baseline_uncertain']} | {s['distinct_pairs']} / {s['pairs_with_support_failure']} |")
    (OUT/'review.md').write_text('\n'.join(lines)+'\n')

if __name__=='__main__':main()
