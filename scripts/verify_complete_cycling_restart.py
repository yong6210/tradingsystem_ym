"""Real-data replay equivalence with complete engine restarts and mock venue reconciliation."""
import hashlib
import json
from pathlib import Path
from replay_cycling_trial_v1 import ROOT,inputs,replay,audit_ledger
from app.research.recovery.cycling_plan_recovery import CyclingPlanRecoveryEngine
from app.research.recovery.cycling_reduction_engine import ReductionReference
from app.research.recovery.thesis_evidence import ThesisEvidenceRegistry
from app.research.recovery.cycling_engine_checkpoint import checkpoint,restore,save


def run():
    snapshot,start,bars=inputs()
    path=ROOT/'reports/validation/cycling_reduction_v3_20260919/pre_start_structure.json'
    m=json.loads(path.read_text())
    refs=[ReductionReference(r['id'],r['side'],r['price'],r['available_ms'],m['source_sha256'],
        'pre-start structure; inventory reduction trial') for r in m['candidates']]
    target=min((r for r in refs if r.side==1 and r.price>m['reference_close']),key=lambda r:r.price)
    kwargs=dict(thesis_registry=ThesisEvidenceRegistry([]),reduction_references=refs,
        role_policy=json.loads((ROOT/'configs/research/cycling_role_v2.json').read_text()))
    def initialize(e):
        e.plan_reduction(target.id,observed_ms=start,mark=m['reference_close'],execution_ok=True,funding_known=True)
    baseline,_=replay(snapshot,start,bars,1,engine_class=CyclingPlanRecoveryEngine,engine_kwargs=kwargs,initialize=initialize)
    restarts=[]
    points={bars[i].end_ms for i in (0,719,1439,2415,2417)}
    def resume(e,bar):
        if bar.end_ms not in points:return e
        venue=dict(side=e.model.position_side,quantity=e.model.quantity,average=e.model.average,
            open_orders={o.id:dict(filled=str(o.filled),status=o.status) for o in e.orders.orders.values()
                         if o.status in ('open','cancel_pending')})
        payload=checkpoint(e);r=restore(json.loads(json.dumps(payload)))
        assert r.orders.restart_required
        r.orders.reconcile(**venue)
        assert checkpoint(r)==payload
        restarts.append(dict(time_ms=bar.end_ms,checkpoint_sha256=payload['sha256'],reconciliation='mock venue match'))
        return r
    recovered,summary=replay(snapshot,start,bars,1,engine_class=CyclingPlanRecoveryEngine,
        engine_kwargs=kwargs,initialize=initialize,after_observe=resume)
    assert checkpoint(baseline)==checkpoint(recovered)
    out=ROOT/'reports/validation/cycling_complete_restart_20260919';out.mkdir(parents=True,exist_ok=True)
    save(recovered,out/'final_checkpoint.json')
    result=dict(status='research_engine_restart_equivalence_not_live_recovery',bars=len(bars),restarts=restarts,
        full_state_and_journal_equal=True,independent_ledger=audit_ledger(recovered,snapshot,1,bars[-1].close),
        summary=summary,limits='same implementation only; venue snapshots are independently captured from the uninterrupted simulator, not from an exchange; synthetic tests cover partial fills and cancel races',
        sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path(__file__),path,ROOT/'scripts/replay_cycling_trial_v1.py']})
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(restarts=len(restarts),equal=True,quantity=str(recovered.model.quantity))))


if __name__=='__main__':run()
