"""Freeze available structural prices first, then replay the same development data."""
import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile
from replay_cycling_trial_v1 import ROOT,ARCHIVE,inputs,replay,audit_ledger,stamp
from app.research.recovery.structure_review import completed_bars,observe_structure
from app.research.recovery.cycling_reduction_engine import CyclingReductionEngine,ReductionReference
from app.research.recovery.thesis_evidence import ThesisEvidenceRegistry
from app.research.recovery.models import jsonable


def freeze_references(rows,asof,digest):
    known=[r for r in rows if r['end_ms']<=asof]
    mark=known[-1]['close'];scales={};candidates=[];excluded=[]
    for minutes in (15,60,240):
        observed=observe_structure(completed_bars(known,asof,minutes),2)
        scales[str(minutes)]=dict(relations=observed['relations'],latest=observed['latest'])
        for kind,side in [('high',1),('low',-1)]:
            for pivot in observed['latest'][kind]:
                item=dict(pivot,scale_minutes=minutes,side=side,id=f"{minutes}:{pivot['id']}")
                if pivot['state']!='unbroken' or side*(pivot['price']-mark)<=0:
                    excluded.append(dict(item,reason='not unbroken or not ahead of the inventory reduction direction'))
                else:candidates.append(item)
    return dict(asof_ms=asof,reference_close=mark,scales=scales,candidates=candidates,excluded=excluded,
        main_direction='unassessed',source_sha256=digest,
        selection='latest two confirmed strict high/low pivots per 15/60/240-minute comparison scale; flank 2; unbroken and on relevant side of as-of close; all fixed before replay; not volume bands')


def run():
    snapshot,start,bars=inputs();digest=hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    rows=[]
    with ZipFile(ARCHIVE) as archive,archive.open(archive.namelist()[0]) as fp:
        for row in csv.DictReader(io.TextIOWrapper(fp)):
            end=int(row['open_time'])+60000
            if stamp('2026-08-08T00:00:00Z')<end:
                rows.append(dict(end_ms=end,**{k:float(row[k]) for k in ('high','low','close')}))
    manifest=freeze_references(rows,start,digest)
    assert manifest==freeze_references([r for r in rows if r['end_ms']<=start],start,digest)
    refs=[ReductionReference(r['id'],r['side'],r['price'],r['available_ms'],digest,
        f"Pre-start confirmed {r['scale_minutes']}-minute {r['kind']}; structural price only; trial inventory reduction reference") for r in manifest['candidates']]
    kwargs=dict(thesis_registry=ThesisEvidenceRegistry([]),
        role_policy=json.loads((ROOT/'configs/research/cycling_role_v2.json').read_text()),reduction_references=refs)
    out=ROOT/'reports/validation/cycling_reduction_v3_20260919';out.mkdir(parents=True,exist_ok=True)
    (out/'pre_start_structure.json').write_text(json.dumps(manifest,indent=2)+'\n')
    summaries=[]
    for side,name in [(None,'unknown_flat'),(1,'hypothetical_long'),(-1,'hypothetical_short')]:
        e,summary=replay(snapshot,start,bars,side,engine_class=CyclingReductionEngine,engine_kwargs=kwargs)
        prefix,_=replay(snapshot,start,bars[:1440],side,engine_class=CyclingReductionEngine,engine_kwargs=kwargs)
        assert prefix.journal==e.journal[:len(prefix.journal)]
        assert not any(o.kind in ('exit','increase') for o in e.orders.orders.values())
        summary.update(name=name,prefix_invariance='PASS',independent_ledger=audit_ledger(e,snapshot,side,bars[-1].close))
        summaries.append(summary)
        (out/(name+'.jsonl')).write_text(''.join(json.dumps(jsonable(r))+'\n' for r in e.journal))
    files=[Path(__file__),ROOT/'scripts/replay_cycling_trial_v1.py',ARCHIVE,
        ROOT/'configs/research/cycling_role_v2.json',ROOT/'configs/research/cycling_decision_trial_v1.json',
        *sorted((ROOT/'app/research/recovery').glob('*.py'))]
    result=dict(status='structural_reduction_trial_not_strategy_validation',scenarios=summaries,
        inherited_assumptions='../cycling_trial_real_v1_20260919/summary.json',
        manifest_sha256=hashlib.sha256((out/'pre_start_structure.json').read_bytes()).hexdigest(),
        rule='previous close on approach side; touch and close back on approach side; favorable close retires reference; minimum half total inventory per growth cycle; nearer active reference also constrains nearby-cycle entry cost gate',
        limitations='selection is a new trial on previously inspected data; no automatic main trend, no historical liquidity/funding, no dynamic renewal or role reversal',
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(summaries,indent=2))


if __name__=='__main__':run()
