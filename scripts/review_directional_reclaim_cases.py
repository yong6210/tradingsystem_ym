"""Same fixed day, independent long/short hypotheses and provenance counts."""
from pathlib import Path
from zipfile import ZipFile
import csv,io,json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.directional_reclaim_review import review_directional_reclaims
from scripts.review_reclaim_cases import utc


def run():
    previous=ROOT/'reports/validation/reclaim_cases_20260919/cases.json'
    structure=ROOT/'reports/validation/zone_structure_cards_20260919/structure.json'
    cards=ROOT/'reports/validation/zone_decision_cards_20260919/cards.json'
    archive=ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    old=json.loads(previous.read_text()); card=json.loads(cards.read_text())['cards'][0]
    high=json.loads(structure.read_text())['cards'][0]['scales']['15']['observation']['latest']['high']
    assert len(high)==2 and all(p['available_ms']<=old['start_ms'] for p in high)
    specs=[r['spec'] for r in old['results']]+[dict(id='S02',low=min(p['price'] for p in high),
        high=max(p['price'] for p in high),source='envelope of two already known structural highs; not volume zone',
        pivot_ids=[p['id'] for p in high])]
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==old['source_sha256'][str(archive.relative_to(ROOT))]
    rows=[]
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as fp:
        for r in csv.DictReader(io.TextIOWrapper(fp)):
            t=int(r['open_time'])+60000
            if old['start_ms']<t<=old['end_ms']:
                rows.append(dict(end_ms=t,**{k:float(r[k]) for k in ('low','high','close')}))
    assert len(rows)==1440
    results=[]
    for spec in specs:
        for side in (1,-1):
            result=review_directional_reclaims(rows,side=side,low=spec['low'],high=spec['high'],
                available_ms=old['start_ms'],reference_close=float(card['observed_event']['close']),basis_id=spec['id']+':frozen-v1')
            results.append(dict(spec=spec,result=result))
            if side==1 and spec['id'] in ('Z01','S01'):
                prior=next(r['result'] for r in old['results'] if r['spec']['id']==spec['id'])
                assert result['cycle_count']==prior['cycle_count'] and len(result['events'])==len(prior['events'])
                for a,b in zip(result['events'],prior['events']):
                    assert all(a[k]==b[k] for k in ('available_ms','close','cycle','close_position','touched','recovery_active'))
    output=dict(status='independent_direction_hypotheses_not_direction_switching',orders_generated=0,
        start_ms=old['start_ms'],end_ms=old['end_ms'],results=results,
        method='Long recovery closes above after below; short recovery closes below after above. No fills, direction selection or new-basis detection.',
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (previous,structure,cards,archive)},
        code_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__),ROOT/'app/research/recovery/directional_reclaim_review.py')})
    lines=['# 같은 구간의 롱·숏 관찰과 근거 중복','',
        f"{utc(old['start_ms'])}–{utc(old['end_ms'])} UTC, 동일한 실제 1분봉 1,440개. 기존에 사용한 자료다.",
        '롱·숏은 별도의 가정이다. 같은 계좌에서 방향을 번갈아 바꿨다는 뜻이 아니다.',
        '롱은 하단 아래 이력 후 상단 위 마감, 숏은 상단 위 이력 후 하단 아래 마감을 회복으로 기록한다.',
        '구간 등록 이전의 미관찰 이력은 추정하지 않는다. 시작 가격이 반대편이면 그 위치만 초기 상태에 반영한다.',
        'S01·S02는 두 구조 저점·고점 사이 범위이며 체결량 매물대가 아니다. 좁은 경계에 따른 반복 관찰 가능성을 포함한다.','',
        '| 구간 | 범위 | 방향 가정 | 회복 횟수 | 회복 상실 | 유리한 쪽 재접촉 마감 | 참조한 근거 ID 수 |',
        '| --- | --- | --- | ---: | ---: | ---: | ---: |']
    for item in results:
        spec=item['spec']; r=item['result']; events=r['events']
        count=lambda name:sum(name in e['labels'] for e in events)
        lines.append(f"| {spec['id']} | {spec['low']:,.1f}–{spec['high']:,.1f} | {'롱' if r['side']==1 else '숏'} | {r['cycle_count']} | {count('recovery_lost')} | {count('retest_close_favorable')} | 1 |")
    lines+=['','근거 ID 1개는 매매 근거가 충분하다는 뜻이 아니다. 모든 사건이 같은 동결 구간을 참조한다는 출처 표시다. 독립적인 새 근거 판정과 주문 승인은 모두 비활성이다.','',
        '## 숏 관찰의 첫 주기','',
        '| 구간 | UTC | 종가 | 당시 관찰 |','| --- | --- | ---: | --- |']
    for item in results:
        r=item['result']
        if r['side']!=-1: continue
        for e in r['events']:
            names=[k for k in e['labels'] if k in ('close_recovery','recovery_lost','retest_close_favorable','retest_close_inside')]
            if e['cycle']==1 and names:
                lines.append(f"| {item['spec']['id']} | {utc(e['available_ms'])} | {e['close']:,.1f} | {', '.join(names)} |")
    lines+=['','## 새 관찰과 새 근거의 차이','',
        '- 같은 구간의 새 접촉: 관찰 ID만 새로 기록한다. 시간 경과·축소 체결 자체가 시장 근거를 새로 만들지는 않는다.',
        '- 회복 후 다시 무효화: 앞선 회복 판단을 그대로 재사용하지 않는다. 이후 회복도 같은 구간의 새 주기로 기록한다.',
        '- 새로 확인된 구조·체결량 구간: 기존 버전을 바꾸지 않고 확인 시점과 출처를 갖춘 새 후보로 검토해야 한다. 이번 코드가 이를 자동 발견하거나 승인하지는 않는다.',
        '- 새 후보라도 기존 구간과 같은 반응을 재표현한 것인지 확인해야 한다. ID가 다르다고 독립 근거로 합산하지 않는다.',
        '- 숏 추가 물량의 되돌림 축소는 가격 하락 시 검토한다. 결정하면 총수량 최소 절반을 덜며, 새 숏 추가와는 근거를 분리한다.','',
        '이는 중복 근거를 드러내는 관찰 기록이다. 재접촉 거래를 전면 금지하거나 한 구간당 한 번만 거래하도록 제한하는 규칙은 아니다.']
    out=ROOT/'reports/validation/directional_reclaim_cases_20260919';out.mkdir(parents=True,exist_ok=False)
    (out/'cases.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    (out/'cases.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines[:18]))


if __name__=='__main__':run()
