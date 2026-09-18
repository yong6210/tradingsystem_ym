"""Independent raw Fraction checkpoints around E032's delayed second snapshot."""
from datetime import datetime,timezone
from fractions import Fraction as F
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.audit_microstructure_fitness import load,save,sha,check,lines
from scripts.audit_microstructure_raw_sample import timestamp_ns


def main():
    base=ROOT/'reports/validation';old=base/'e032_flow_absorption_20260919'
    replay=base/'e032_flow_snapshot_repair_20260919';out=base/'e032_snapshot_independent_audit_20260919';out.mkdir(exist_ok=False)
    raw=old/'2026-04-01/raw.ndjson';gridpath=replay/'2026-04-01/grid.jsonl'
    inputs={str(p.relative_to(ROOT)):sha(p) for p in (raw,gridpath)}
    sources={str(Path(__file__).resolve().relative_to(ROOT)):sha(Path(__file__))}
    save(out/'registration.json',dict(registered_at=datetime.now(timezone.utc).isoformat(),input_hashes=inputs,source_hashes=sources,
        scope='Independent raw Fraction top-five checkpoints at seconds 40,41,42,102; not full raw audit or performance selection',public_requests=0))
    start=timestamp_ns('2026-04-01T00:00:00Z');records=[]
    for line in raw.read_text().splitlines():
        if not line.strip():raise ValueError('unhandled disconnect in scoped audit')
        stamp,body=line.split(' ',1);t=timestamp_ns(stamp)
        if t>start+102*10**9:break
        message=json.loads(body);d=message['data']
        if d.get('e')=='depthUpdate' or message['stream'].endswith('@depthSnapshot'):records.append((t,d))
    grid={p['time_ns']:p for p in lines(gridpath)};index=0;history=[];bids=asks=None;last=None;snapshot_id=None;snapshots=[];applied=0
    def apply(d):
        nonlocal last,applied
        if d['u']<snapshot_id:return
        if last is None:
            if not d['U']<=snapshot_id<=d['u']:raise ValueError('Fraction first bridge missing')
        elif d['pu']!=last or d['u']<=last:raise ValueError('Fraction update chain missing')
        for key,side in [('b',bids),('a',asks)]:
            for p,q in d[key]:
                p,q=F(p),F(q)
                if q:side[p]=q
                else:side.pop(p,None)
        last=d['u'];applied+=1
    checked=[]
    for second in [40,41,42,102]:
        deadline=start+second*10**9
        while index<len(records) and records[index][0]<=deadline:
            t,d=records[index];index+=1
            if d.get('e')=='depthUpdate':
                history.append((t,d))
                if bids is not None:apply(d)
            else:
                snapshot_id=d['lastUpdateId'];last=None
                bids={F(p):F(q) for p,q in d['bids']};asks={F(p):F(q) for p,q in d['asks']}
                covering=[(when,x) for when,x in history if x['U']<=snapshot_id<=x['u']]
                if not covering:raise ValueError('expected already received covering update')
                for when,x in history:apply(x)
                snapshots.append(dict(received_ns=t,last_update_id=snapshot_id,covering_received_ns=covering[0][0],covering_U=covering[0][1]['U'],covering_u=covering[0][1]['u'],received_before_snapshot=covering[0][0]<=t))
            if t>deadline:raise ValueError('future record')
        p=grid[deadline]
        for key,side,reverse in [('bids',bids,True),('asks',asks,False)]:
            expected=sorted(side.items(),reverse=reverse)[:5]
            if [(F(a),F(b)) for a,b in p[key]]!=expected:raise ValueError('independent top-five mismatch')
        checked.append(dict(second=second,valid=p['valid'],last_u=last,top_five_both_sides_equal=True))
    if len(snapshots)!=2 or not all(x['received_before_snapshot'] for x in snapshots):raise ValueError('snapshot boundary assertion')
    save(out/'result.json',dict(status='PASS_INDEPENDENT_RAW_FRACTION_CHECKPOINTS',checkpoints=checked,snapshots=snapshots,applied_updates_including_replay=applied,public_requests=0))
    check(inputs);check(sources)
    save(out/'verification.json',dict(status='PASS',artifacts={p.name:sha(p) for p in out.iterdir() if p.is_file()}))
    print(json.dumps(load(out/'result.json'),indent=2))


if __name__=='__main__':main()
