"""Compare role separation against frozen v1 development traces, without tuning."""
import hashlib
import json
from pathlib import Path
from replay_cycling_trial_v1 import ROOT, inputs, replay, audit_ledger
from app.research.recovery.cycling_role_engine import CyclingRoleEngine
from app.research.recovery.thesis_evidence import ThesisEvidenceRegistry
from app.research.recovery.models import jsonable


def run():
    snapshot,start,bars=inputs()
    out=ROOT/'reports/validation/cycling_roles_v2_20260919'
    out.mkdir(parents=True,exist_ok=True)
    policy_path=ROOT/'configs/research/cycling_role_v2.json'
    kwargs=dict(thesis_registry=ThesisEvidenceRegistry([]),role_policy=json.loads(policy_path.read_text()))
    summaries=[]
    for side,name in [(None,'unknown_flat'),(1,'hypothetical_long'),(-1,'hypothetical_short')]:
        baseline,_=replay(snapshot,start,bars,side)
        old_path=ROOT/'reports/validation/cycling_trial_real_v1_20260919'/(name+'.jsonl')
        old=[json.loads(line) for line in old_path.read_text().splitlines()]
        assert jsonable(baseline.journal)==old,'shared engine refactor changed frozen v1 behavior'
        engine,summary=replay(snapshot,start,bars,side,engine_class=CyclingRoleEngine,engine_kwargs=kwargs)
        prefix,_=replay(snapshot,start,bars[:1440],side,engine_class=CyclingRoleEngine,engine_kwargs=kwargs)
        assert prefix.journal==engine.journal[:len(prefix.journal)]
        assert not any(o.kind in ('exit','increase') for o in engine.orders.orders.values())
        summary.update(name=name,main_status=engine.main_status,prefix_invariance='PASS',
            baseline_trace_unchanged='PASS',independent_ledger=audit_ledger(engine,snapshot,side,bars[-1].close))
        summaries.append(summary)
        (out/(name+'.jsonl')).write_text(''.join(json.dumps(jsonable(r),ensure_ascii=False)+'\n' for r in engine.journal))
    files=[Path(__file__),ROOT/'scripts/replay_cycling_trial_v1.py',policy_path,
           *sorted((ROOT/'app/research/recovery').glob('*.py'))]
    result=dict(status='role_separation_regression_not_strategy_performance',
        inherited_run_assumptions='../cycling_trial_real_v1_20260919/summary.json',
        main_evidence_records=[],reason='No reviewed main-trend formation or invalidation evidence exists in this frozen manifest. Do not fabricate it from local contacts.',
        role_policy=json.loads(policy_path.read_text()),scenarios=summaries,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summaries,indent=2))


if __name__=='__main__':run()
