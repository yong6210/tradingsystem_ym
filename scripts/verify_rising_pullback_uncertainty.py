"""Independent raw-price and eligibility audit of the fixed diagnostic report."""
import csv
import hashlib
import io
import json
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/rising_pullback_uncertainty_20260920'
MINUTE=60000


def main():
    report_path=OUT/'review.json';d=json.loads(report_path.read_text())
    for p,h in d['source_sha256'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h,p
    raw={}
    for month in ('07','08'):
        p=ROOT/f'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-{month}.zip'
        with ZipFile(p) as z,z.open(z.namelist()[0]) as fp:
            for row in csv.DictReader(io.TextIOWrapper(fp)):
                t=int(row['open_time'])+MINUTE
                assert t not in raw
                raw[t]={k:Decimal(row[k]) for k in ('high','low','close')}
    start,end=d['start_ms'],d['end_ms'];assert all(t in raw for t in range(start-16*1440*MINUTE+MINUTE,end+1,MINUTE))
    cache={}
    def bar(t,m):
        key=(t,m)
        if key not in cache:
            block=[raw[x] for x in range(t-m*MINUTE+MINUTE,t+1,MINUTE)]
            cache[key]={'high':max(r['high'] for r in block),'low':min(r['low'] for r in block)}
        return cache[key]
    all_wait=True;both_long=[]
    for point in d['points']:
        t=point['time_ms'];assert Decimal(str(point['mark']))==raw[t]['close']
        assert abs(Decimal(str(point['known_day_move']))-(raw[t]['close']-raw[start]['close']))<Decimal('.000001')
        all_wait &= point['action']=='wait' and point['action_reason']=='direction_unassessed'
        assert point['state']['root'] is None and point['state']['invalidated_ms'] is None
        for v in point['evidence']:
            active=[]
            for n in v['nodes']:
                c=n['candidate'];m=n['minutes']
                if not c:continue
                for k in ('prior_reaction','broken','protected'):
                    p=c[k];bt=p['pivot_bar_end_ms'];kind=p['kind'];value=Decimal(str(p['price']))
                    assert value==bar(bt,m)[kind]
                    assert p['available_ms']==bt+2*m*MINUTE<=t
                    neighbors=[bar(bt+i*m*MINUTE,m)[kind] for i in (-2,-1,1,2)]
                    assert all(value>x for x in neighbors) if kind=='high' else all(value<x for x in neighbors)
                begin=c['prior_reaction']['pivot_bar_end_ms']-m*MINUTE
                block=[raw[x] for x in range(begin+MINUTE,t+1,MINUTE)]
                assert Decimal(str(n['low']))==min(r['low'] for r in block)
                assert Decimal(str(n['high']))==max(r['high'] for r in block)
                if c['status']=='active':active.append(n)
            # This fixed case has no duplicated price-signature groups.
            signatures=[(n['candidate']['side'],*(n['candidate'][k]['price'] for k in ('prior_reaction','broken','protected'))) for n in active]
            assert len(signatures)==len(set(signatures))
            eligible=[]
            for n in active:
                c=n['candidate'];others=[x for x in active if x is not n]
                contains=lambda x: c['prior_reaction']['pivot_bar_end_ms']<x['candidate']['prior_reaction']['pivot_bar_end_ms'] and all(n['low']<=x['candidate'][k]['price']<=n['high'] for k in ('prior_reaction','broken','protected'))
                has_support=any(x['candidate']['side']==c['side'] and contains(x) and x['candidate']['protected']['pivot_bar_end_ms']>c['protected']['pivot_bar_end_ms'] for x in others)
                if has_support and all(contains(x) for x in others):eligible.append(n)
            expected=eligible[0]['candidate']['side'] if len(eligible)==1 else None
            assert expected==v['context']['side']
        short,long=point['evidence']
        for m in (15,60):
            a=next(n for n in short['nodes'] if n['minutes']==m);b=next(n for n in long['nodes'] if n['minutes']==m)
            assert a==b
        if short['context']['side']==1:
            assert long['context']['side'] is None
            old=next(n['candidate'] for n in long['nodes'] if n['minutes']==240)
            assert old['side']==-1 and old['status']=='active' and old['protected']['price']==65700
            both_long.append(t)
    assert all_wait and both_long
    result=dict(source_hashes='PASS',continuous_raw_minutes='PASS',raw_pivots_and_availability='PASS',
        raw_price_bounds='PASS',independent_root_eligibility='PASS',common_15_60_minute_evidence='PASS',
        same_wait_states='PASS',prefix_checkpoints=d['prefix_checkpoints'],
        prefix_verification='producer rebuilt without future minutes at each phase change and endpoint',
        report_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest(),
        verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        actual_orders=False,interpretation='diagnostic correctness; not correctness of market direction')
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
