"""Instrument existing reducer; alter only one historical value in explicit controls."""
import ast
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

from review_market_judgment_regimes import ROOT,MINUTE,CONFIG,load_rows,stamp,utc
from app.research.recovery.protected_structure import reduce_structure
from app.research.recovery.structure_review import completed_bars,observe_structure

DOC=ROOT/'docs/research/MARKET_INVALIDATION_MEMORY_TRIAL.md'
OUT=ROOT/'reports/validation/market_invalidation_memory_20260919'
MODE='confirmed_path_opposition_retest'
NO_OVERRIDE=object()


class Instrument(ast.NodeTransformer):
    def __init__(self):self.bar_hooks=0;self.branch_hooks=0
    def visit_Assign(self,node):
        node=self.generic_visit(node)
        names=[x.id for x in node.targets if isinstance(x,ast.Name)]
        if names==['t']:
            self.bar_hooks+=1
            hook=ast.parse('invalidated_at = audit_state(t, invalidated_at, current)').body[0]
            return [node,ast.copy_location(hook,node)]
        if names==['inherited']:
            self.branch_hooks+=1
            hook=ast.parse('audit_branch(t, side, invalidated_at, inherited, target, prior, reaction, current)').body[0]
            return [node,ast.copy_location(hook,node)]
        return node


def audit_reduce(bars,pivots,*,after_ms,override=NO_OVERRIDE,mode=MODE):
    """No disk modification. One replacement before the first later bar's checks."""
    states=[];branches=[];applied=[]
    def state_hook(t,invalidated,current):
        if t<=after_ms:return invalidated
        before=invalidated
        if override is not NO_OVERRIDE and not applied:
            invalidated=override
            applied.append(dict(time_ms=t,old=before,new=invalidated))
        states.append(dict(time_ms=t,current=deepcopy(current),invalidated_before=before,invalidated_used=invalidated))
        return invalidated
    def branch_hook(t,side,invalidated,inherited,target,prior,reaction,current):
        if t<=after_ms:return
        evidence=[target,prior,reaction]
        assert all(p['available_ms']<=t for p in evidence)
        earliest=min(p['pivot_bar_end_ms'] for p in evidence)
        assert inherited==(invalidated is not None and earliest<=invalidated)
        branches.append(dict(time_ms=t,side=side,invalidated_at=invalidated,inherited=inherited,
            earliest_landmark_ms=earliest,landmarks=deepcopy(evidence),
            current_side=current['side'] if current else None,current_status=current['status'] if current else None))
    tree=ast.parse(inspect.getsource(reduce_structure));instrument=Instrument();tree=instrument.visit(tree)
    if (instrument.bar_hooks,instrument.branch_hooks)!=(1,1):raise ValueError('unsupported reducer layout')
    ast.fix_missing_locations(tree);namespace=dict(audit_state=state_hook,audit_branch=branch_hook)
    exec(compile(tree,'<audit of protected_structure.reduce_structure>','exec'),namespace)
    result=namespace['reduce_structure'](bars,pivots,confirmation_mode=mode)
    return dict(result=result,states=states,branches=branches,applied=applied)


def suffix(run,t):
    return dict(candidate=run['result']['candidate'],events=[e for e in run['result']['events'] if e['available_ms']>t])


def synthetic_counterexample():
    # Existing opposition-retest regression geometry, with times as synthetic units.
    def p(id,kind,price,formed,available):return dict(id=id,kind=kind,price=price,pivot_bar_end_ms=formed,available_ms=available)
    ps=[p('L0','low',90,1,2),p('H0','high',110,3,4),p('L1','low',100,5,6),
        p('H1','high',120,11,12),p('L2','low',105,13,14),p('H2','high',115,15,16)]
    prices=[(9,109),(10,111),(11,120),(12,118),(13,105),(14,110),(15,115),(16,108),(17,99),(18,104),(19,99)]
    bars=[dict(end_ms=t,close=c,high=c+1,low=c-1) for t,c in prices];bars[-1].update(high=106,low=98)
    baseline=audit_reduce(bars,ps,after_ms=17);erased=audit_reduce(bars,ps,after_ms=17,override=None)
    assert baseline['result']==reduce_structure(bars,ps,confirmation_mode=MODE)
    assert baseline['result']['candidate']['formed_ms']==19
    assert erased['result']['candidate']['formed_ms']==18
    return dict(status='synthetic_counterexample_not_market_data',bars=bars,pivots=ps,baseline=baseline,erased=erased)


def real_case(rows):
    cutoff=stamp('2026-08-14T08:00:00Z');end=stamp('2026-08-17T00:00:00Z')
    old_invalidated=stamp('2026-08-11T16:00:00Z');runs={};inputs={}
    for label,start in (('short_history','2026-07-27T00:00:00Z'),('long_history','2026-07-19T00:00:00Z')):
        bars=completed_bars([r for r in rows if stamp(start)<r['end_ms']<=end],end,240)
        obs=observe_structure(bars);ps=[{k:p[k] for k in ('id','kind','price','pivot_bar_end_ms','available_ms')} for p in obs['pivots']]
        inputs[label]=(bars,ps)
        baseline=audit_reduce(bars,ps,after_ms=cutoff)
        assert baseline['result']==reduce_structure(bars,ps,confirmation_mode=MODE)
        swapped=audit_reduce(bars,ps,after_ms=cutoff,override=None if label=='short_history' else old_invalidated)
        assert suffix(baseline,cutoff)==suffix(swapped,cutoff)
        runs[label]=dict(baseline=baseline,swapped=swapped)
    a=runs['short_history']['baseline'];b=runs['long_history']['baseline']
    assert a['states'][0]['current']==b['states'][0]['current']
    assert [a['states'][0]['invalidated_used'],b['states'][0]['invalidated_used']]==[old_invalidated,None]
    assert suffix(a,cutoff)==suffix(b,cutoff)
    assert a['branches'] and b['branches']
    for run in (a,b):
        assert all(x['earliest_landmark_ms']>old_invalidated and not x['inherited'] for x in run['branches'])
    # Every later complete bar is replayed without later bars or unavailable pivots.
    for label,(bars,ps) in inputs.items():
        for t in (x['time_ms'] for x in runs[label]['baseline']['states']):
            for name,override in (('baseline',NO_OVERRIDE),('swapped',None if label=='short_history' else old_invalidated)):
                prefix=audit_reduce([x for x in bars if x['end_ms']<=t],[p for p in ps if p['available_ms']<=t],after_ms=cutoff,override=override)
                full=runs[label][name]
                assert prefix['result']['events']==[e for e in full['result']['events'] if e['available_ms']<=t]
                assert prefix['branches']==[e for e in full['branches'] if e['time_ms']<=t]
    return dict(cutoff_ms=cutoff,end_ms=end,old_invalidated_ms=old_invalidated,runs=runs,
        equivalent_scope='candidate and later events for these fixed inputs and observed horizon',
        all_future_paths_proven=False,minimum_examined_landmark_ms=min(x['earliest_landmark_ms'] for x in a['branches']+b['branches']),
        baseline_instrumentation_exact=True,one_value_swap_suffix_equal=True,every_bar_prefix_verified=True)


def render(r):
    real=r['real_case'];lines=['# 마지막 무효화 이력의 실제 영향','',
        '원래 판정 코드를 메모리에서 계측했다. 원본 코드 파일·판단 규칙·가격·피벗은 바꾸지 않았다. 명시적 대조군에서만 한 번의 마지막 무효화 값 교환을 시행했다.','',
        '| 입력 | 원래 이력 | 교환값 | 이후 후보·사건 | 심사된 분기 수 |','| --- | --- | --- | --- | ---: |']
    for name,run in real['runs'].items():
        baseline=run['baseline'];swap=run['swapped']['applied'][0]
        fmt=lambda t:utc(t) if t is not None else '없음'
        lines.append(f"| {name} | {fmt(swap['old'])} | {fmt(swap['new'])} | 동일 | {len(baseline['branches'])} |")
    lines+=['','비교 범위: '+utc(real['cutoff_ms'])+' 이후 ~ '+utc(real['end_ms'])+'. 모든 이후 완료 봉에서 미래 자료를 제거해 재생했다.',
        '실제 심사된 세 근거 중 가장 이른 형성 시각: '+utc(real['minimum_examined_landmark_ms'])+'. 두 경로 모두 과거 근거 재사용 분기는 발동하지 않았다.','',
        '## 합성 반례','',
        '기존 회귀 사례에서 마지막 무효화 이력을 지우면, 원래 19번 시점의 반대 후보가 18번에 형성됐다. 18번 종가는 104이며 과거 기준 100 아래로 마감한 재접근을 충족하지 않는다. 이 변수는 일반적으로 삭제할 수 없다.',
        '실제 두 초기화의 전체 상태 동등성이나 모든 미래 경로를 증명한 것은 아니다. 해당 고정 자료·관찰 기간에서 이 값만 바꿔도 이후 후보와 사건이 같음을 확인했다. 신규 노출 승인·주문은 없다.','']
    return '\n'.join(lines)


def main():
    rows,sources=load_rows();result=dict(status='invalidation_memory_causal_audit_not_strategy_validation',
        real_case=real_case(rows),counterexample=synthetic_counterexample(),orders_generated=0,new_exposure_allowed=False)
    sources += [DOC,Path(__file__),Path(inspect.getsourcefile(reduce_structure)),
        ROOT/'app/research/recovery/structure_review.py',ROOT/'scripts/review_market_judgment_regimes.py',CONFIG]
    result['source_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'review.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (OUT/'review.md').write_text(render(result))
    print(json.dumps(dict(branches={k:len(v['baseline']['branches']) for k,v in result['real_case']['runs'].items()},
        earliest_landmark=utc(result['real_case']['minimum_examined_landmark_ms']),every_bar_prefix_verified=True)))


if __name__=='__main__':main()
