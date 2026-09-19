"""Fixed August 11 state/admission audit. No revised rules or assumed position."""
import csv,hashlib,io,json
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile
from review_market_judgment_regimes import ROOT,CONFIG,DAY,MINUTE,load_rows,prepare,snapshot,utc,stamp,jsonable
from review_six_case_entry_scan import scan_case

OUT=ROOT/'reports/validation/rebound_state_sequence_20260920'
SCAN=ROOT/'reports/validation/six_case_entry_scan_20260920/review.json'
PRIOR=ROOT/'reports/validation/market_basis_revision_20260919/review.json'


def main():
    source=json.loads(SCAN.read_text());old_source=json.loads(PRIOR.read_text())
    for data in (source,old_source):
        for p,h in data['source_sha256'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h,p
    case=next(c for c in source['cases'] if c['label']=='falling_rebound')
    old=next(c for c in old_source['cases'] if c['label']=='falling_rebound')
    cfg=json.loads(CONFIG.read_text());account=json.loads((ROOT/cfg['account_config']).read_text())
    start,end=stamp('2026-08-11T03:15:00Z'),stamp('2026-08-11T16:00:00Z')
    rows,_=load_rows();rebuilt=jsonable(scan_case([r for r in rows if r['end_ms']<=end],cfg,account,old,end))
    assert rebuilt['points']==[p for p in case['points'] if p['time_ms']<=end]
    points=[p for p in rebuilt['points'] if start<=p['time_ms']<=end]
    prepared=[prepare(rows,case['start_ms']-d*DAY,end,cfg) for d in cfg['history_days']]
    events=[];last=None
    for p in points:
        supports=tuple((n['minutes'],n['candidate']['formed_ms'],n['candidate']['protected']['price']) for n in p['support']['support'])
        key=(p['state']['reason'],p['support']['reason'],p['result']['reason'],supports)
        if key!=last or any(p['reactions'].values()) or p['time_ms']==end:
            t=p['time_ms'];events.append(dict(point=p,views=[snapshot(x,t) for x in prepared]))
        last=key
    for event in events:
        t=event['point']['time_ms'];prefix=jsonable(scan_case([r for r in rows if r['end_ms']<=t],cfg,account,old,t))
        assert prefix['points']==[p for p in rebuilt['points'] if p['time_ms']<=t]
        print('prefix',utc(t),'PASS',flush=True)
    # Read the original archives independently for close boundaries and preserved old prices.
    raw={}
    for month in ('07','08'):
        with ZipFile(ROOT/f'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-{month}.zip') as z,z.open(z.namelist()[0]) as fp:
            for r in csv.DictReader(io.TextIOWrapper(fp)):
                t=int(r['open_time'])+MINUTE;assert t not in raw;raw[t]=Decimal(r['close'])
    assert all(t in raw for t in range(case['start_ms'],end+1,MINUTE))
    probes=[]
    for begin,minutes,price in [('03:15',240,'63788.1'),('03:15',15,'63949.3'),('09:00',15,'63958'),('11:15',15,'64120.3')]:
        t=stamp('2026-08-11T'+begin+':00Z');step=minutes*MINUTE
        fail=next((x for x in range((t//step+1)*step,end+1,step) if raw[x]<Decimal(price)),None)
        probes.append(dict(first_observed_utc=utc(t),minutes=minutes,protected=price,
            retrospective_first_close_failure_ms=fail,retrospective_first_close_failure_utc=None if fail is None else utc(fail),
            close=None if fail is None else str(raw[fail])))
    expected=['16:00','05:00','14:30','13:45']
    for p,s in zip(probes,expected):assert p['retrospective_first_close_failure_ms']==stamp('2026-08-11T'+s+':00Z')
    for p in points:
        assert Decimal(str(p['mark']))==raw[p['time_ms']]
        assert p['result']['action']=='wait' and p['result']['quantity']=='0'
        if p['support']['side'] is not None:
            assert p['support']['side']==1 and not p['reactions']['1']
            assert p['result']['reason']=='no_fresh_reaction_at_this_checkpoint'
        else:assert p['result']['reason']=='direction_unassessed'
    after=next(p for p in points if p['time_ms']==stamp('2026-08-11T13:45:00Z'))
    assert after['support']['side'] is None and raw[after['time_ms']]>Decimal('63958')
    assert points[-1]['state']['root'] is None and points[-1]['state']['invalidated_ms']==end
    sources=dict(source['source_sha256'])
    for p in (SCAN,PRIOR,CONFIG,Path(__file__),ROOT/'scripts/review_six_case_entry_scan.py'):
        sources[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
    result=dict(status='fixed_case_audit_not_strategy_approval',start_ms=start,end_ms=end,actual_orders=False,
        initial_context=case['points'][0],points=points,events=events,retrospective_price_probes=probes,
        checks=dict(original_points='PASS',every_event_prefix='PASS',raw_continuity_and_closes='PASS',
            no_direction_reaction_overlap='PASS',superseded_support_price_survival='PASS',main_invalidation_not_opposite_entry='PASS'),
        source_sha256=sources)
    OUT.mkdir(exist_ok=True,parents=True);(OUT/'review.json').write_text(json.dumps(jsonable(result),ensure_ascii=False,indent=2)+'\n')
    lines=['# 8월 11일 상태와 신규 진입 심사','','무포지션 심사이며 방향 지지는 보유 지시가 아니다. 시각 UTC.','',
        '| 시각 | 종가 | 기준 상태 | 현재 방향 | 현재 지지 가격 | 롱/숏 반응 | 대기 이유 |','| --- | ---: | --- | --- | --- | --- | --- |']
    for e in events:
        p=e['point'];levels=[n['candidate']['protected']['price'] for n in p['support']['support']]
        reactions={s:[r['price'] for r in rs] for s,rs in p['reactions'].items() if rs}
        lines.append(f"| {p['utc']} | {p['mark']} | {p['state']['reason']} | {p['support']['side']} | {levels} | {reactions} | {p['result']['reason']} |")
    (OUT/'review.md').write_text('\n'.join(lines)+'\n');print(json.dumps(result['checks']))

if __name__=='__main__':main()
