"""Explain the fixed August 4 case; no rule changes or hypothetical fills."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from review_market_judgment_regimes import ROOT, CONFIG, DAY, MINUTE, load_rows, prepare, snapshot, stable_context, utc, signature
from review_market_basis_revision import revise_basis, current_support, with_bounds
from review_market_direction_continuity import advance, anchor_bars

SOURCE = ROOT/'reports/validation/six_case_entry_scan_20260920/review.json'
OUT = ROOT/'reports/validation/rising_pullback_uncertainty_20260920'


def relationships(view):
    # Expose every predicate rather than treating the aggregate "uncertain" as evidence.
    groups={}
    for n in view['nodes']:
        c=n['candidate']
        if c and c['status']=='active':groups.setdefault(signature(c),[]).append(n)
    nodes=[max(g,key=lambda n:n['candidate']['formed_ms']) for g in groups.values()]
    pairs=[]
    for a in nodes:
        for b in nodes:
            if a is b:continue
            ca,cb=a['candidate'],b['candidate']
            pairs.append(dict(root_minutes=a['minutes'],other_minutes=b['minutes'],
                earlier_origin=ca['prior_reaction']['pivot_bar_end_ms']<cb['prior_reaction']['pivot_bar_end_ms'],
                outside_prices={k:cb[k]['price'] for k in ('prior_reaction','broken','protected') if not a['low']<=cb[k]['price']<=a['high']},
                same_side=ca['side']==cb['side'],
                later_protected=cb['protected']['pivot_bar_end_ms']>ca['protected']['pivot_bar_end_ms']))
    return pairs


def build(rows,cfg,old,end):
    start=old['start_ms'];known=[r for r in rows if r['end_ms']<=end]
    prepared=[prepare(known,start-d*DAY,end,cfg) for d in cfg['history_days']]
    state=deepcopy(old['points'][0]['state']);points=[]
    prices={r['end_ms']:r['close'] for r in known}
    for prior in old['points']:
        t=prior['time_ms']
        if t>end:break
        views=[snapshot(p,t) for p in prepared];context=stable_context(views)
        if t>start:
            state,_=advance(state,t=t,context=context,bars=anchor_bars(prepared[-1],state,t))
            state,_=revise_basis(state,views,t)
        support=current_support(state,with_bounds(views,prepared,state,t),t)
        assert state==prior['state'] and support==prior['support']
        block=[r for r in known if start<r['end_ms']<=t]
        evidence=[]
        for days,v in zip(cfg['history_days'],views):
            evidence.append(dict(history_days=days,context=v['context'],nodes=v['nodes'],pairs=relationships(v)))
            for n in v['nodes']:
                c=n['candidate']
                if c:
                    assert c['formed_ms']<=t
                    assert all(c[k]['available_ms']<=t for k in ('prior_reaction','broken','protected'))
        points.append(dict(time_ms=t,utc=utc(t),mark=prices[t],known_day_move=prices[t]-prices[start],
            known_day_high=max((r['high'] for r in block),default=prices[start]),
            known_day_low=min((r['low'] for r in block),default=prices[start]),
            state=deepcopy(state),support=support,context=context,evidence=evidence,
            action=prior['result']['action'],action_reason=prior['result']['reason']))
    return points


def phase_key(p):
    return (p['state']['reason'],p['support']['reason'],p['context'].get('blocker'),
            tuple((v['context'].get('blocker'),tuple((n['minutes'],None if n['candidate'] is None else (n['candidate']['side'],n['candidate']['status'],n['candidate']['formed_ms'])) for n in v['nodes'])) for v in p['evidence']))


def main():
    source=json.loads(SOURCE.read_text())
    for path,h in source['source_sha256'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==h,path
    cfg=json.loads(CONFIG.read_text());rows,raw=load_rows()
    old=next(c for c in source['cases'] if c['label']=='rising_pullback')
    assert utc(old['start_ms']).startswith('2026-08-04')
    points=build(rows,cfg,old,old['end_ms'])
    changes=[p for i,p in enumerate(points) if i==0 or phase_key(p)!=phase_key(points[i-1])]
    checkpoints=sorted({p['time_ms'] for p in changes}|{old['end_ms']})
    for t in checkpoints:
        prefix=build([r for r in rows if r['end_ms']<=t],cfg,old,t)
        assert prefix==[p for p in points if p['time_ms']<=t]
        print('prefix',utc(t),'PASS',flush=True)
    paths=[SOURCE,CONFIG,Path(__file__)]+[ROOT/p for p in source['source_sha256']]
    report=dict(case='rising_pullback',start_ms=old['start_ms'],end_ms=old['end_ms'],
        status='diagnostic_not_strategy_approval',actual_orders=False,rule_changes=False,holdout=False,
        points=points,change_times=[p['time_ms'] for p in changes],prefix_checkpoints=checkpoints,
        checks=dict(previous_states_and_support='PASS',available_evidence='PASS',truncated_rebuild='PASS'),
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    OUT.mkdir(exist_ok=True,parents=True);(OUT/'review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    lines=['# 8월 4일 방향 미판정의 원인','', '기존 심사 시점에서 구조 사건 또는 미판정 원인이 바뀐 시점을 표시한다. 형성 시각과 관측 시각은 원문에서 구분한다. 가격 움직임은 해당 시점까지의 값이다.','', '| UTC | 종가 | 당일 변화 | 8일 / 16일 장애 | 상태 / 현재 지지 |','| --- | ---: | ---: | --- | --- |']
    for p in changes:
        reasons=' / '.join(v['context'].get('blocker','supported') for v in p['evidence'])
        lines.append(f"| {p['utc']} | {p['mark']} | {p['known_day_move']:.1f} | {reasons} | {p['state']['reason']} / {p['support']['reason']} |")
    (OUT/'review.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines),flush=True)

if __name__=='__main__':main()
