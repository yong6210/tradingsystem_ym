"""Explicit before-arrival limit plan on used data, with opening-only mock fills."""
import json
import hashlib
from pathlib import Path
from replay_cycling_trial_v1 import ROOT,inputs,replay,audit_ledger,ARCHIVE
from app.research.recovery.cycling_planned_reduction import CyclingPlannedReductionEngine
from app.research.recovery.cycling_reduction_engine import ReductionReference
from app.research.recovery.thesis_evidence import ThesisEvidenceRegistry
from app.research.recovery.models import jsonable


def run(engine_class=CyclingPlannedReductionEngine, output_name='cycling_planned_reduction_20260919'):
    snapshot,start,bars=inputs()
    manifest_path=ROOT/'reports/validation/cycling_reduction_v3_20260919/pre_start_structure.json'
    manifest=json.loads(manifest_path.read_text())
    assert manifest['asof_ms']==start
    assert manifest['source_sha256']==hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    refs=[ReductionReference(r['id'],r['side'],r['price'],r['available_ms'],manifest['source_sha256'],
        'pre-start structural price; explicit planned inventory reduction trial') for r in manifest['candidates']]
    kwargs=dict(thesis_registry=ThesisEvidenceRegistry([]),reduction_references=refs,
        role_policy=json.loads((ROOT/'configs/research/cycling_role_v2.json').read_text()))
    target=min((r for r in refs if r.side==1 and r.price>manifest['reference_close']),key=lambda r:r.price)
    def initialize(e):
        e.plan_reduction(target.id,observed_ms=start,mark=manifest['reference_close'],execution_ok=True,funding_known=True)
    engine,summary=replay(snapshot,start,bars,1,engine_class=engine_class,
        engine_kwargs=kwargs,initialize=initialize)
    prefix,_=replay(snapshot,start,bars[:1440],1,engine_class=engine_class,
        engine_kwargs=kwargs,initialize=initialize)
    assert prefix.journal==engine.journal[:len(prefix.journal)]
    summary.update(prefix_invariance='PASS',independent_ledger=audit_ledger(engine,snapshot,1,bars[-1].close))
    assert engine.model.quantity==engine.model.step*50
    assert all(o.kind=='limit_reduce' for o in engine.orders.orders.values())
    out=ROOT/'reports/validation'/output_name;out.mkdir(parents=True,exist_ok=True)
    (out/'events.jsonl').write_text(''.join(json.dumps(jsonable(r))+'\n' for r in engine.journal))
    fills=[r for r in engine.journal if r['action']=='fill']
    files=[Path(__file__),ROOT/'scripts/replay_cycling_trial_v1.py',manifest_path,ARCHIVE,
           *sorted((ROOT/'app/research/recovery').glob('*.py'))]
    result=dict(status='explicit_plan_execution_trial_not_strategy_validation',engine_class=engine_class.__name__,summary=summary,
        plan=dict(submitted_ms=start,reference=jsonable(target),quantity='0.05',basis_quantity='0.1',
            purpose='preplaced reduction on arrival, independent of reaction-confirmed reduction'),fills=fills,
        assumptions='same v1 hypothetical long inventory, costs, zero funding and account limits; earliest eligible opening strictly after order submission, adverse spread/slippage included; only fill if price respects limit; full-fill liquidity assumption; no high/low touch-based fill; serial active order must settle before any addition',
        limitations='used development data; intent is a trial choice, not confirmed user rule; partial/cancel races tested synthetically only; no complete engine restart or live venue transport; no automatic main-direction classifier',
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(summary=summary,plan=result['plan'],fills=fills),indent=2))


if __name__=='__main__':run()
