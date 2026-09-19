"""Verify provenance facts against original minute data and saved controls."""
import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/market_startup_provenance_20260919'


def stamp(s):return int(datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()*1000)


def main():
    r=json.loads((OUT/'review.json').read_text())
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in r['source_sha256'].items())
    raw={}
    for month in ('07','08'):
        p=ROOT/f'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-{month}.zip'
        with ZipFile(p) as z,z.open(z.namelist()[0]) as f:
            for row in csv.DictReader(io.TextIOWrapper(f)):
                raw[int(row['open_time'])+60000]={k:float(row[k]) for k in ('high','low','close')}
    f=r['focal'];v=f['variants'];width=240*60000
    p=f['boundary']['landmark'];t=p['pivot_bar_end_ms']
    high=max(raw[x]['high'] for x in range(t-width+60000,t+60000,60000))
    assert high==p['price']==65700
    assert f['boundary']['absent_left_bar_ends']==[stamp('2026-07-27T00:00:00Z')]
    assert v['long_prices_short_landmarks']==v['short_original']
    assert v['long_prices_only_post_boundary_landmarks']==v['short_original']
    assert v['long_without_boundary_high']['candidate']['side']==-1
    assert v['long_without_boundary_high']['candidate']['protected']['price']==65747.2
    assert 64654.9<raw[stamp('2026-07-30T12:00:00Z')]['close']<65700
    assert raw[stamp('2026-07-31T16:00:00Z')]['close']<63174.3
    start=stamp('2026-07-28T00:00:00Z');end=f['end_ms']
    max_close=max(raw[x]['close'] for x in range(start,end+1,width))
    assert max_close<=65700
    counts={k:sum(c['counts'][k] for c in r['existing_case_audit'][:6]) for k in r['existing_case_audit'][0]['counts']}
    assert sum(counts.values())==258
    assert r['existing_case_audit'][-1]['comparisons']==27
    follow=r['agreement_followup'];assert follow['first_visible_agreement_ms']==stamp('2026-08-14T08:00:00Z')
    pair=follow['at_first_agreement']
    assert pair[0]['candidate']==pair[1]['candidate']
    assert [x['retained_last_invalidated_ms'] for x in pair]==[stamp('2026-08-11T16:00:00Z'),None]
    assert follow['full_state_equivalence_verified'] is False
    result=dict(source_hashes='PASS',raw_landmark_and_close_checks='PASS',controls='PASS',
        comparison_counts=counts,original_comparisons=27,
        max_completed_4h_close_after_short_65700=max_close,
        visible_agreement_not_state_equivalence='CONFIRMED',new_exposure_allowed=False)
    (OUT/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
