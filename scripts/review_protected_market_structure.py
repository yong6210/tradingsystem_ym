"""As-of structural formation/invalidation evidence; no timeframe voting or orders."""
import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile
from replay_cycling_trial_v1 import ROOT,ARCHIVE,stamp
from app.research.recovery.structure_review import completed_bars,observe_structure
from app.research.recovery.protected_structure import protected_structure


def at(rows,t,history_start,mode='current_cross'):
    known=[r for r in rows if history_start<r['end_ms']<=t]
    scales={}
    for minutes in (15,60,240):
        bars=completed_bars(known,t,minutes)
        trial=protected_structure(bars,confirmation_mode=mode)
        observed=observe_structure(bars)
        close=known[-1]['close']
        # Most recent confirmed candidate on each side; structural prices, not volume bands.
        candidates={}
        for kind in ('high','low'):
            eligible=[p for p in observed['pivots'] if p['state']=='unbroken' and
                      (p['price']>close if kind=='high' else p['price']<close)]
            candidates[kind]=eligible[-1] if eligible else None
        scales[str(minutes)]=dict(last_completed_ms=bars[-1]['end_ms'],trial=trial,
            latest_relations=observed['relations'],local_structural_candidates=candidates)
    return dict(asof_ms=t,history_start_ms=history_start,close=known[-1]['close'],scales=scales,
                main_direction='unassessed; scale roles require review, no majority vote')


def run(mode='current_cross'):
    raw=ARCHIVE.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    assert digest==ARCHIVE.with_name(ARCHIVE.name+'.CHECKSUM').read_text().split()[0]
    rows=[]
    with ZipFile(io.BytesIO(raw)) as archive,archive.open(archive.namelist()[0]) as fp:
        for r in csv.DictReader(io.TextIOWrapper(fp)):
            rows.append(dict(end_ms=int(r['open_time'])+60000,**{k:float(r[k]) for k in ('high','low','close')}))
    dates=['2026-08-15T00:01:00Z','2026-08-16T16:17:00Z','2026-08-16T22:56:00Z','2026-08-17T00:01:00Z']
    cases=[]
    for date in dates:
        t=stamp(date);card=at(rows,t,stamp('2026-08-01T00:00:00Z'),mode)
        assert card==at([r for r in rows if r['end_ms']<=t],t,stamp('2026-08-01T00:00:00Z'),mode)
        shorter=at(rows,t,stamp('2026-08-08T00:00:00Z'),mode)
        sensitivity={}
        for key,scale in card['scales'].items():
            def signature(c):return None if c is None else dict(side=c['side'],status=c['status'],anchor=c['protected']['price'],formed_ms=c['formed_ms'])
            full=signature(scale['trial']['candidate']);short=signature(shorter['scales'][key]['trial']['candidate'])
            sensitivity[key]=dict(full=full,short=short,equal=full==short)
            assert all(e['available_ms']<=t for e in scale['trial']['events'])
        cases.append(dict(utc=date,card=card,history_sensitivity=sensitivity))
    out=ROOT/'reports/validation/protected_market_structure_20260919';out.mkdir(parents=True,exist_ok=True)
    body=dict(confirmation_mode=mode,status='trial_structure_evidence_not_approved_main_direction',source_sha256=digest,cases=cases,
        rule='higher reaction low then prior high break; mirrored short; causal reaction anchor; reanchor mode requires renewed directional extension; adverse close invalidates but does not automatically reverse; all new formation landmarks must follow invalidation',
        limitations='scale choice and importance unverified; strict flank-two pivot proposal; previously inspected data; no trading orders; history-start sensitivity reported',
        code_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path(__file__),ROOT/'app/research/recovery/protected_structure.py',ROOT/'app/research/recovery/structure_review.py']})
    (out/('review.json' if mode=='current_cross' else mode+'_review.json')).write_text(json.dumps(body,indent=2)+'\n')
    for c in cases:
        print(c['utc'],json.dumps(c['history_sensitivity']))
        print('local',json.dumps({k:{side:(None if p is None else p['price']) for side,p in v['local_structural_candidates'].items()} for k,v in c['card']['scales'].items()}))


if __name__=='__main__':run()
