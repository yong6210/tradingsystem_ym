"""Attach first post-confirmation interactions to existing frozen candidates."""
from pathlib import Path
from zipfile import ZipFile
import csv,io,json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.post_confirmation_review import first_interactions
from scripts.review_decision_card_structure import utc


def run():
    source=ROOT/'reports/validation/structure_lineage_20260919/lineage.json'
    archive=ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    old=json.loads(source.read_text())
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==old['source_sha256'][str(archive.relative_to(ROOT))]
    candidates=[c for c in old['records'] if old['start_ms']<c['available_ms']<=old['end_ms']]
    rows=[]
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as fp:
        for r in csv.DictReader(io.TextIOWrapper(fp)):
            t=int(r['open_time'])+60000
            if old['start_ms']<=t<=old['end_ms']:
                rows.append(dict(end_ms=t,**{k:float(r[k]) for k in ('low','high','close')}))
    results=[]
    for c in candidates:
        r=first_interactions(c,rows,asof_ms=old['end_ms'])
        for key in ('first_touch','first_new_contact','first_close_side_change'):
            event=r[key]
            if event:
                t=event['available_ms']
                assert first_interactions(c,[b for b in rows if b['end_ms']<=t],asof_ms=t)[key]==event
        results.append(dict(candidate=c,review=r))
    new=[r['review']['first_new_contact'] for r in results if r['review']['first_new_contact']]
    summary=dict(candidates=len(results),new_contacts=len(new),
        favorable_close=sum(e['close_relative_to_marker_role']=='favorable' for e in new),
        adverse_close=sum(e['close_relative_to_marker_role']=='adverse' for e in new),
        on_close=sum(e['close_relative_to_marker_role']=='on' for e in new),
        no_new_contact=len(results)-len(new),orders_generated=0)
    lines=['# 구조 확인 이후 최초 재접근','',
        '기존 후보 36개에 확인 시점의 가격과 이후 첫 접촉을 연결했다. 관찰 종료는 기존 구간의 08-16 08:55 UTC로 고정했다.',
        '집계 단위는 후보별 기록이다. 같은 가격·같은 시각의 접촉이 여러 시간봉 후보에 중복 기록될 수 있다.',
        '후보별 남은 관찰 시간이 다르다. 미접촉은 관찰 종료까지 미관찰이라는 뜻이며 실패·무효화가 아니다.',
        '정확한 구조 가격을 진단용 기준점으로 사용한다. 임의 폭의 매물대나 지정가 주문으로 바꾸지 않았다.',
        '별도 재접근은 직전 1분봉이 기준점에 닿지 않은 뒤 접촉한 경우다. 접촉 봉 종가 위치는 관찰이며 지지·저항 성공 판정이 아니다.',
        '봉 종료 즉시 자료 확보를 가정한다. 한 봉 안에서 닿은 순서나 체결 가능성은 판단하지 않는다.','',
        f"후보 {summary['candidates']}개 중 별도 접촉 {summary['new_contacts']}개: 역할 기준 유리한 쪽 종가 {summary['favorable_close']}, 불리한 쪽 {summary['adverse_close']}, 기준점과 동일 {summary['on_close']}. 미관찰 {summary['no_new_contact']}개.",
        '저점 후보는 위 마감, 고점 후보는 아래 마감을 역할 기준 유리한 쪽이라고 표기했다. 보유 방향이나 계좌 수익을 뜻하지 않는다.','',
        '| 후보 창·종류 | 가격 | 확인 UTC | 확인 종가 | 별도 접촉 UTC | 접촉 종가 | 기준점 역할 대비 | 관찰 분 |',
        '| --- | ---: | --- | ---: | --- | ---: | --- | ---: |']
    for item in results:
        c=item['candidate'];r=item['review'];e=r['first_new_contact']
        when=utc(e['available_ms']) if e else '미관찰'
        close=f"{e['close']:,.1f}" if e else '—'
        role=e['close_relative_to_marker_role'] if e else '—'
        lines.append(f"| {c['timeframe_minutes']}분 {c['kind']} | {c['price']:,.1f} | {utc(c['available_ms'])} | {r['confirmation_close']:,.1f} | {when} | {close} | {role} | {r['observation_minutes']} |")
    lines+=['','## 판단에 연결할 때','',
        '- 확인 이전에 있었던 반등을 새 후보 확인 후의 재지지로 재사용하지 않는다.',
        '- 첫 접촉 봉이 유리한 쪽에서 마감해도 그 이후 유지 여부는 아직 알 수 없다. 나중의 결과로 당시 판단을 정당화하지 않는다.',
        '- 동일 가격의 서로 다른 시간봉 후보가 같은 후속 봉에 닿았다면 접촉 두 번이나 독립 근거 두 개로 합산하지 않는다.',
        '- 추가 후보와 되돌림 축소 후보는 실제 주된 방향·보유량·여력을 붙여 따로 판단해야 한다. 이번 결과는 주문을 승인하지 않는다.']
    output=dict(summary=summary,start_ms=old['start_ms'],end_ms=old['end_ms'],results=results,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,archive)},
        code_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__),ROOT/'app/research/recovery/post_confirmation_review.py')})
    out=ROOT/'reports/validation/post_confirmation_cases_20260919';out.mkdir(parents=True,exist_ok=False)
    (out/'cases.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    (out/'cases.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(summary))


if __name__=='__main__':run()
