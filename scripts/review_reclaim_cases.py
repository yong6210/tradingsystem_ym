"""Compare a frozen volume zone with known structural lows over a fixed next day."""
from pathlib import Path
from datetime import datetime, timezone
from zipfile import ZipFile
import csv, io, json, hashlib, sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.reclaim_review import replay_reclaims


def stamp(value): return int(datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()*1000)
def utc(ms): return datetime.fromtimestamp(ms/1000,timezone.utc).strftime('%m-%d %H:%M')


def run():
    structure=ROOT/'reports/validation/zone_structure_cards_20260919/structure.json'
    cards=ROOT/'reports/validation/zone_decision_cards_20260919/cards.json'
    archive=ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    card=json.loads(cards.read_text())['cards'][0]
    structural=json.loads(structure.read_text())['cards'][0]
    assert card['decision_utc']==structural['decision_utc']
    start=stamp(card['decision_utc']); end=start+24*3600000
    lows=structural['scales']['15']['observation']['latest']['low']
    assert len(lows)==2 and all(p['available_ms']<=start for p in lows)
    specs=[dict(id='Z01',low=62750.,high=62900.,source='previously frozen executed-volume zone'),
           dict(id='S01',low=min(p['price'] for p in lows),high=max(p['price'] for p in lows),
                source='envelope of two known 15m structural lows; not a volume zone',pivot_ids=[p['id'] for p in lows])]
    sha=hashlib.sha256(archive.read_bytes()).hexdigest()
    assert sha==json.loads(cards.read_text())['source_sha256']['candles']
    rows=[]
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as fp:
        for r in csv.DictReader(io.TextIOWrapper(fp)):
            t=int(r['open_time'])+60000
            if start<t<=end:
                rows.append(dict(end_ms=t,**{k:float(r[k]) for k in ('low','high','close')}))
    assert len(rows)==1440
    labels=dict(close_inside_to_above='구간 내부에서 상단 위 마감',close_reclaim_above='下方 체류 후 상단 위 종가 회복'.replace('下方','하단 아래'),
                rebreak_below_after_reclaim='회복 후 하단 재이탈',retest_close_above='별도 재접촉 후 상단 위 마감',
                retest_close_inside='별도 재접촉 후 구간 내부 마감')
    results=[]
    for spec in specs:
        result=replay_reclaims(rows,low=spec['low'],high=spec['high'],available_ms=start,
                               reference_close=float(card['observed_event']['close']))
        results.append(dict(spec=spec,result=result))
    artifact=dict(start_ms=start,end_ms=end,minutes=1440,selection='first existing decision card; fixed next 24h; not a new holdout',
                  assumptions='completed 1m OHLC available at end; no intrabar ordering or execution assumptions',
                  source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (structure,cards,archive)},
                  code_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
                      (Path(__file__),ROOT/'app/research/recovery/reclaim_review.py')},results=results,orders_generated=0)
    lines=['# 매물대 회복과 구조 가격 회복의 차이','',
           f'관찰 시작 {utc(start)} UTC. 당시 알려진 구간만 고정하고 이후 24시간 1,440분을 순서대로 읽었다.',
           'Z01은 실제 체결량 구간, S01은 당시 확인된 두 구조 저점 사이의 범위다. S01을 새 매물대로 해석하지 않는다.',
           '아래 사건은 해당 봉 종료 시점의 관찰이다. 후속 결과를 앞선 행동 근거로 사용하지 않는다.',
           '하단 아래 종가 이력 후 상단 위 종가를 회복으로 기록한다. 회복 봉 자체를 재지지로 세지 않는다.',
           '연속 접촉은 한 번의 접촉 구간으로 취급한다. 재접촉 기록은 적어도 한 봉이 구간과 떨어진 뒤 다시 닿은 경우다. 이 기하학적 정의는 진입 규칙이 아니다.','']
    for item in results:
        spec=item['spec']; result=item['result']
        significant=[e for e in result['events'] if any(k in labels for k in e['labels'])]
        lines += [f"## {spec['id']} {spec['low']:,.1f}–{spec['high']:,.1f}",'',
                  f"회복 횟수 {result['cycle_count']}; 종료 위치 {result['close_position']}. 사건 수는 거래 기회 수가 아니다.",'',
                  '| UTC | 가격 | 당시 관찰 | 회복 차수 |','| --- | ---: | --- | ---: |']
        for e in significant:
            text=' / '.join(labels[k] for k in e['labels'] if k in labels)
            lines.append(f"| {utc(e['available_ms'])} | {e['close']:,.1f} | {text} | {e['cycle']} |")
        if not significant: lines.append('| — | — | 해당 회복·재접근 사건 없음 | — |')
        lines.append('')
    lines += ['## 보유 상태와 연결하는 검토안','',
              '| 관찰 | 추가 물량을 보유한 롱 | 새로운 롱 추가 |','| --- | --- | --- |',
              '| 구간 아래에서 접근 | 반등을 이용한 축소 자리 후보. 본절은 필수 조건이 아님 | 접근만으로 추가 근거 완성 아님 |',
              '| 내부 진입 또는 상단 위 첫 종가 | 되돌림 축소로 판단하면 총수량 최소 절반. 실제 수량·여력 대사 필요 | 구조 회복 관찰일 뿐 후속 지지 유지가 확인된 것은 아님 |',
              '| 떨어졌다 다시 접촉하고 위 마감 | 앞선 축소 물량을 자동으로 되사지 않음 | 주된 방향·새 반응·잔여 여력 확인 후 후보 검토 |',
              '| 회복 후 하단 재이탈 | 해당 회복 근거 재평가. 약손절 수량은 아직 미정 | 이전 회복 근거를 그대로 재사용하지 않음 |','',
              '이는 롱 보유 시 조건부 검토이며 실제 방향은 판정하지 않았다. 숏에 대한 대칭 회복 검토는 이번 산출물에 포함하지 않았다.']
    out=ROOT/'reports/validation/reclaim_cases_20260919'
    out.mkdir(parents=True,exist_ok=False)
    (out/'cases.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2)+'\n')
    (out/'cases.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps([dict(id=r['spec']['id'],cycles=r['result']['cycle_count'],events=len(r['result']['events']),
        first_recovery=next((dict(time=utc(e['available_ms']),close=e['close']) for e in r['result']['events'] if 'close_reclaim_above' in e['labels']),None)) for r in results]))


if __name__=='__main__':run()
