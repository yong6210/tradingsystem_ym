"""Fixed, contemporaneously known anchors; independent long/short hypotheses."""
from pathlib import Path
from zipfile import ZipFile
import csv,io,json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.thesis_anchor_trial import review_anchor
from scripts.review_decision_card_structure import utc


def run():
    structure=ROOT/'reports/validation/zone_structure_cards_20260919/structure.json'
    window=ROOT/'reports/validation/reclaim_cases_20260919/cases.json'
    archive=ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    frozen=json.loads(structure.read_text());card=frozen['cards'][0];w=json.loads(window.read_text())
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==w['source_sha256'][str(archive.relative_to(ROOT))]
    rows=[]
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as fp:
        for r in csv.DictReader(io.TextIOWrapper(fp)):
            t=int(r['open_time'])+60000
            if w['start_ms']<=t<=w['end_ms']:
                rows.append(dict(end_ms=t,**{k:float(r[k]) for k in ('low','high','close')}))
    assert len(rows)==1441
    reference=rows[0]['close'];results=[]
    for minutes in ('15','60','240'):
        for side,kind in ((1,'low'),(-1,'high')):
            pivot=card['scales'][minutes]['observation']['latest'][kind][-1]
            assert pivot['available_ms']<=w['start_ms']
            args=dict(side=side,anchor=pivot['price'],available_ms=w['start_ms'],reference_close=reference)
            result=review_anchor(rows,asof_ms=w['end_ms'],**args)
            for event in result['events']:
                t=event['available_ms']
                prefix=review_anchor([r for r in rows if r['end_ms']<=t],asof_ms=t,**args)
                assert prefix['events']==[e for e in result['events'] if e['available_ms']<=t]
            results.append(dict(timeframe_minutes=int(minutes),anchor_candidate_id=pivot['id'],
                anchor_confirmed_ms=pivot['available_ms'],review=result))
    output=dict(results=results,source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (structure,window,archive)},
        code_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__),ROOT/'app/research/recovery/thesis_anchor_trial.py')},
        assumptions='trial latest confirmed low for long, high for short; fixed marker, 1m observations; no averaging or vote across windows',
        orders_generated=0,direction_confirmations=0)
    names=dict(not_challenged='해당 기준 미이탈',challenged='해당 기준 이탈',failed_retest='별도 재접근 후 반대편 마감',recovered='해당 기준 회복')
    lines=['# 주된 방향 판단을 위한 고정 구조 기준 시험','',
        f"{utc(w['start_ms'])}–{utc(w['end_ms'])} UTC, 기존 24시간 자료. 시작 시점에 확인된 각 창의 최근 저점(롱 가정)·고점(숏 가정)을 고정했다.",
        '이 기준 선택과 1분 종가 판정은 미승인 시험 규칙이다. 시간봉 투표·4시간봉 필수 조건은 없다.',
        '상태는 개별 기준 가격의 반응이며 주된 방향의 정답이 아니다. 미이탈을 추세 유지 확정으로, 재접근 실패를 추세 전환 확정으로 바꾸지 않는다.',
        '시험에서 이탈 후 재접근 실패는 앞선 별도 분봉 전체가 불리한 쪽에 있었고 다음 접촉이 불리한 쪽 종가로 끝난 경우다. 이탈 봉 자체에서 재접근 실패를 동시에 판정하지 않는다.',
        '롱·숏 가정은 독립적인 비교이며 같은 계좌에서 방향을 번갈아 바꾼 기록이 아니다.','',
        '| 구조 창 | 방향 가정 | 기준 가격 | 시작 상태 | 이탈 사건 | 재접근 실패 | 회복 | 끝 상태 |',
        '| --- | --- | ---: | --- | ---: | ---: | ---: | --- |']
    summary=[]
    for item in results:
        r=item['review'];count=lambda state:sum(e['state']==state for e in r['events'])
        summary.append(dict(minutes=item['timeframe_minutes'],side=r['side'],anchor=r['anchor'],initial=r['initial_state'],
                            challenges=count('challenged'),failed_retests=count('failed_retest'),recoveries=count('recovered'),final=r['state']))
        lines.append(f"| {item['timeframe_minutes']}분 | {'롱' if r['side']==1 else '숏'} | {r['anchor']:,.1f} | {names[r['initial_state']]} | {count('challenged')} | {count('failed_retest')} | {count('recovered')} | {names[r['state']]} |")
    for item in results:
        r=item['review']
        lines+=['',f"## {item['timeframe_minutes']}분 · {'롱' if r['side']==1 else '숏'} 가정",'',
                '| UTC | 종가 | 당시 기록 |','| --- | ---: | --- |']
        for e in r['events']:lines.append(f"| {utc(e['available_ms'])} | {e['close']:,.1f} | {names[e['state']]} |")
        if not r['events']:lines.append('| — | — | 해당 시험 기준의 새 상태 변화 없음 |')
    lines+=['','기준 가격을 최신 후보로 계속 바꾸지는 않았다. 동적으로 바꾸는 기준은 별도 미확정이다. 고점·저점 추출 자체의 확인 봉 수 민감도는 앞선 구조 검토에 남아 있다.',
        '모든 상태 변화는 그 시점까지의 봉만 다시 입력한 결과와 대조했다. 미래 회복을 과거 이탈 판단에 넣지 않았다. 자동 방향 선언·주문은 0건이다.']
    out=ROOT/'reports/validation/thesis_anchor_trials_20260919';out.mkdir(parents=True,exist_ok=False)
    (out/'trials.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    (out/'trials.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':run()
