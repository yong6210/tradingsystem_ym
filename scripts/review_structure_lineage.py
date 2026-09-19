"""Register delayed pivot candidates without retroactive entry justification."""
from pathlib import Path
from zipfile import ZipFile
import csv,io,json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.structure_review import completed_bars,observe_structure
from app.research.recovery.structure_lineage import candidate_lineage
from scripts.review_decision_card_structure import stamp,utc


def run():
    previous=ROOT/'reports/validation/directional_reclaim_cases_20260919/cases.json'
    archive=ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    old=json.loads(previous.read_text());start=old['start_ms'];end=old['end_ms']
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==old['source_sha256'][str(archive.relative_to(ROOT))]
    rows=[]
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as fp:
        for r in csv.DictReader(io.TextIOWrapper(fp)):
            t=int(r['open_time'])+60000
            if stamp('2026-08-08T00:00:00Z')<t<=end:
                rows.append(dict(end_ms=t,**{k:float(r[k]) for k in ('low','high','close')}))
    candidates=[]
    for minutes in (15,60,240):
        pivots=observe_structure(completed_bars(rows,end,minutes),2)['pivots']
        for p in pivots:
            # Copy only fields available at confirmation, never later state/break_ms.
            candidates.append(dict(id=f'{minutes}m:'+p['id'],timeframe_minutes=minutes,
                kind=p['kind'],price=p['price'],pivot_bar_end_ms=p['pivot_bar_end_ms'],
                available_ms=p['available_ms'],evidence_start_ms=p['pivot_bar_end_ms']-3*minutes*60000,
                extraction='strict left/right 2 completed bars; trial method'))
    specs={r['spec']['id']:r['spec'] for r in old['results']}
    bands=[dict(id=k+':frozen-v1',low=v['low'],high=v['high'],available_ms=start) for k,v in specs.items()]
    lineage=candidate_lineage(candidates,bands,asof_ms=end)
    assert candidate_lineage(candidates,bands,asof_ms=start)==[r for r in lineage if r['available_ms']<=start]
    fresh=[r for r in lineage if r['available_ms']>start]
    # Recalculate from truncated candles at each new confirmation to verify extraction causality.
    for t in sorted({r['available_ms'] for r in fresh}):
        for minutes in (15,60,240):
            actual=observe_structure(completed_bars(rows,t,minutes),2)['pivots']
            expected=[c for c in candidates if c['timeframe_minutes']==minutes and c['available_ms']<=t]
            assert [(p['id'],p['price'],p['available_ms']) for p in actual]==[(p['id'].split('m:',1)[1],p['price'],p['available_ms']) for p in expected]
    summary=dict(new_candidate_records=len(fresh),same_price_records=sum(bool(r['same_price_known_ids']) for r in fresh),
        overlapping_evidence_records=sum(bool(r['overlapping_evidence_ids']) for r in fresh),
        inside_any_frozen_band=sum(any(b['location']=='inside' for b in r['band_relations']) for r in fresh),
        independently_approved=0,orders_generated=0)
    artifact=dict(start_ms=start,end_ms=end,summary=summary,records=lineage,
        method='trial 2/2 pivots; evidence intervals are [start,available); overlap is possible dependence, not proof of identical reaction',
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (previous,archive)},
        code_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__),ROOT/'app/research/recovery/structure_lineage.py',ROOT/'app/research/recovery/structure_review.py')})
    lines=['# 新구조 후보의 출처와 확인 시점'.replace('新','새 '),'',
        f'{utc(start)}–{utc(end)} UTC에 새로 확인된 구조 후보를 기존 구간 Z01·S01·S02와 연결했다.',
        '15분·1시간·4시간은 시험 관찰 창이다. 좌우 두 봉 추출법은 사용자 확정 규칙이 아니다.',
        '같은 가격 여부는 정확한 가격 일치다. 근접 가격 병합 기준은 아직 도입하지 않았다.',
        '시간 구간 중첩은 같은 원자료를 공유할 가능성 표시이며, 같은 반응이라는 확정 판정도 독립성 부정도 아니다.','',
        f"새 후보 {summary['new_candidate_records']}개; 과거/동시 확인 후보와 같은 가격 {summary['same_price_records']}개; 자료 구간 중첩 {summary['overlapping_evidence_records']}개; 기존 범위 내부 {summary['inside_any_frozen_band']}개. 항목들은 중복될 수 있다.",
        '주문 승인 0건. 구간 밖에 새 가격이 생겼다는 사실만으로 독립적인 추가 근거로 인정하지 않는다.','',
        '| 확인 UTC | 봉 종료 UTC | 창 | 종류 | 가격 | 같은 가격 후보 수 | 자료 중첩 수 | 기존 범위와 관계 |',
        '| --- | --- | --- | --- | ---: | ---: | ---: | --- |']
    for r in fresh:
        relations=', '.join(b['basis_id'].split(':')[0]+':'+b['location'] for b in r['band_relations'])
        lines.append(f"| {utc(r['available_ms'])} | {utc(r['pivot_bar_end_ms'])} | {r['timeframe_minutes']}분 | {r['kind']} | {r['price']:,.1f} | {len(r['same_price_known_ids'])} | {len(r['overlapping_evidence_ids'])} | {relations} |")
    lines+=['','각 확인 시점마다 이후 봉을 잘라 고점·저점을 다시 계산한 결과와 일치했다. 뒤에 확인된 후보를 앞선 사건에 소급 연결하지 않는다.',
        'JSON에는 전체 원본 후보 ID와 참조 관계를 남겼다. 최신 후보로 기존 구간을 덮어쓰거나 무효화 이력을 지우지 않는다.',
        '다음 판단에는 이 후보가 어떤 회복·재접근에 해당하는지, 주된 방향과 여력에 어떤 새 정보를 주는지 검토가 필요하다.']
    out=ROOT/'reports/validation/structure_lineage_20260919';out.mkdir(parents=True,exist_ok=False)
    (out/'lineage.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2)+'\n')
    (out/'lineage.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(summary))


if __name__=='__main__':run()
