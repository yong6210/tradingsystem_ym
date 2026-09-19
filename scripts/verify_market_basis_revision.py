"""Audit saved trial against raw minute closes, independently of its reducer."""
import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/market_basis_revision_20260919'


def main():
    r=json.loads((OUT/'review.json').read_text())
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in r['source_sha256'].items())
    raw={}
    for month in ('07','08'):
        path=ROOT/f'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-{month}.zip'
        with ZipFile(path) as z,z.open(z.namelist()[0]) as f:
            for row in csv.DictReader(io.TextIOWrapper(f)):
                raw[int(row['open_time'])+60000]={k:float(row[k]) for k in ('high','low','close')}
    intervals=revisions=supported=0
    for case in r['cases']:
        for stream in ('events','reset_events'):
            root=None;since=None;last_invalidated=None
            for e in case[stream]+[dict(kind='end',time_ms=case['end_ms'])]:
                t=e['time_ms']
                if root is not None:
                    c=root['candidate'];step=root['minutes']*60000
                    broken=next((x for x in range((since//step+1)*step,t+1,step)
                                 if c['side']*(raw[x]['close']-c['protected']['price'])<0),None)
                    assert broken==(t if e['kind']=='basis_invalidated' else None)
                    intervals+=1
                if e['kind']=='basis_invalidated':
                    assert root==e['root'];last_invalidated=t;root=None
                elif e['kind']=='basis_adopted':
                    assert root is None
                    root=e['root']
                    if last_invalidated is not None:
                        assert t>last_invalidated and root['candidate']['formed_ms']>last_invalidated
                elif e['kind']=='basis_revised':
                    assert root==e['old_root']
                    old=root['candidate'];new=e['new_root']['candidate']
                    assert root['minutes']==e['new_root']['minutes'] and old['side']==new['side']
                    assert all(old['side']*(new[k]['price']-old[k]['price'])>0 for k in ('broken','protected'))
                    assert min(new[k]['pivot_bar_end_ms'] for k in ('broken','protected'))>old['formed_ms']
                    root=e['new_root'];revisions+=1
                if root:
                    c=root['candidate'];assert c['formed_ms']<=t
                    assert all(c[k]['pivot_bar_end_ms']<=c[k]['available_ms']<=t for k in ('prior_reaction','broken','protected'))
                since=t
        for p in case['points']:
            assert not p['guarded']['new_exposure_allowed']
            assert not p['reset_guarded']['new_exposure_allowed']
            if p['guarded']['side'] is None:continue
            supported+=1;root=p['updated_only']['root'];c=root['candidate'];t=p['time_ms']
            assert p['guarded']['support'] and p['guarded']['side']==c['side']
            start=c['prior_reaction']['pivot_bar_end_ms']-root['minutes']*60000
            known=[b for x,b in raw.items() if start<x<=t]
            low=min(b['low'] for b in known);high=max(b['high'] for b in known)
            for n in p['guarded']['support']:
                d=n['candidate'];assert n['minutes']!=root['minutes']
                assert d['side']==c['side'] and d['status']=='active' and d['formed_ms']<=t
                assert d['prior_reaction']['pivot_bar_end_ms']>c['prior_reaction']['pivot_bar_end_ms']
                assert d['protected']['pivot_bar_end_ms']>c['protected']['pivot_bar_end_ms']
                assert all(low<=d[k]['price']<=high and d[k]['available_ms']<=t for k in ('prior_reaction','broken','protected'))
    six=r['cases'][:6]
    v=dict(source_hashes='PASS',raw_close_intervals='PASS',intervals=intervals,revisions=revisions,
           supported_points=supported,new_exposure_allowed=False,
           checkpoints=sum(c['counts']['points'] for c in six),
           guarded_unknown=sum(c['counts']['guarded_unknown'] for c in six),
           snapshot_direction_changes=sum(c['counts']['snapshot_changed'] for c in six),
           initial_direction_difference=sum(c['counts']['initial_direction_difference'] for c in six),
           initial_basis_difference=sum(c['counts']['initial_basis_difference'] for c in six))
    (OUT/'verification.json').write_text(json.dumps(v,indent=2)+'\n');print(json.dumps(v))


if __name__=='__main__':main()
