"""Verify the narrowly stated equivalence and the non-equivalence counterexample."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/market_invalidation_memory_20260919'


def main():
    r=json.loads((OUT/'review.json').read_text());real=r['real_case'];cut=real['cutoff_ms']
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in r['source_sha256'].items())
    prior=json.loads((ROOT/'reports/validation/market_startup_provenance_20260919/review.json').read_text())
    path='app/research/recovery/protected_structure.py'
    assert prior['source_sha256'][path]==r['source_sha256'][path]
    suffixes=[];branch_views=[]
    for name,pair in real['runs'].items():
        original=real['old_invalidated_ms'] if name=='short_history' else None
        swapped=None if name=='short_history' else real['old_invalidated_ms']
        assert pair['baseline']['applied']==[]
        assert pair['swapped']['applied']==[dict(time_ms=cut+240*60000,old=original,new=swapped)]
        for version,run in pair.items():
            expected=original if version=='baseline' else swapped
            assert all(x['invalidated_used']==expected for x in run['states'])
            assert len(run['states'])==16
            for b in run['branches']:
                earliest=min(p['pivot_bar_end_ms'] for p in b['landmarks'])
                assert earliest==b['earliest_landmark_ms']>real['old_invalidated_ms']
                assert b['inherited'] is False
                assert all(p['pivot_bar_end_ms']<=p['available_ms']<=b['time_ms'] for p in b['landmarks'])
            suffixes.append(dict(candidate=run['result']['candidate'],events=[e for e in run['result']['events'] if e['available_ms']>cut]))
            branch_views.append([{k:v for k,v in b.items() if k!='invalidated_at'} for b in run['branches']])
        assert [x['current'] for x in pair['baseline']['states']]==[x['current'] for x in pair['swapped']['states']]
    assert all(s==suffixes[0] for s in suffixes)
    assert all(b==branch_views[0] for b in branch_views)
    example=r['counterexample'];base=example['baseline']['result']['candidate'];erased=example['erased']['result']['candidate']
    assert (base['side'],base['formed_ms'],erased['side'],erased['formed_ms'])==(-1,19,-1,18)
    assert base['opposition_review']['retest_ms']==19 and 'opposition_review' not in erased
    assert next(b for b in example['bars'] if b['end_ms']==18)['close']==104
    assert not real['all_future_paths_proven'] and not r['new_exposure_allowed']
    result=dict(source_hashes='PASS',original_reducer_unchanged='PASS',
        four_suffixes_equal=True,branch_inputs_except_memory_equal=True,
        bars_per_path=16,branches_per_path=len(branch_views[0]),
        synthetic_erasure_changes_candidate_timing=True,
        scope='specified inputs through 2026-08-17 00:00 UTC only',new_exposure_allowed=False)
    (OUT/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
