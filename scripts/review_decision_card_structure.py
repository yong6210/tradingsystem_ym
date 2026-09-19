"""Attach as-of structural observations and extraction sensitivity to frozen cards."""
from pathlib import Path
from datetime import datetime, timezone
from zipfile import ZipFile
import csv
import io
import json
import hashlib
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.structure_review import completed_bars, observe_structure, MINUTE


def stamp(value): return int(datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()*1000)
def utc(ms): return datetime.fromtimestamp(ms/1000,timezone.utc).strftime('%m-%d %H:%M')


def run():
    source=ROOT/'reports/validation/zone_decision_cards_20260919/cards.json'
    archive=ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    original=json.loads(source.read_text())
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    assert digest==original['source_sha256']['candles']
    start=stamp('2026-08-08T00:00:00Z')
    rows=[]
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as fp:
        for r in csv.DictReader(io.TextIOWrapper(fp)):
            t=int(r['open_time'])
            if t>=start:
                rows.append(dict(end_ms=t+MINUTE,**{k:float(r[k]) for k in ('high','low','close')}))
    cards=[]
    lines=['# 판단 카드의 고점·저점과 돌파 이력','','모든 시각 UTC. 8월 8일부터 각 판단 시점까지의 완성 봉만 사용한다.',
           '15분·1시간·4시간은 비교용 관찰 창이다. 어느 창도 필수 방향 기준이나 투표권이 아니다.',
           '시험 추출: 좌우 각각 2개 봉보다 엄격하게 높은 고점/낮은 저점. 오른쪽 2개 봉이 끝난 뒤 확인된다. 동률은 제외한다.',
           '좌우 1·2·3개 비교도 기록했다. 이 추출법과 확인 지연은 사용자 확정 매매 규칙이 아니다.',
           '상태는 최초 돌파 주기의 기록이다: unbroken=아직 종가 돌파 없음, broken=돌파 후 반대편 종가 복귀 없음, failed=최초 돌파 후 반대편 종가 복귀 기록. failed 이후 재돌파 주기는 이 버전에서 추적하지 않으며 현재 위치를 별도 표시한다.',
           '돌파는 확인된 가격을 종가가 넘은 관찰이다. 이후 별도 봉의 접촉·종가 위치를 기록하며 지지 성공이나 실제 체결을 보장하지 않는다.','']
    relations={'higher':'높아짐','lower':'낮아짐','equal':'같음','insufficient':'부족'}
    for old in original['cards']:
        t=stamp(old['decision_utc']); scales={}
        lines+=['## '+old['decision_utc'],'',old['contemporaneous_reading'],'']
        for minutes in (15,60,240):
            completed=completed_bars(rows,t,minutes)
            observed=observe_structure(completed,2)
            sensitivity={str(f):observe_structure(completed,f)['relations'] for f in (1,2,3)}
            assert all(p['available_ms']<=t for p in observed['pivots'])
            recent=[e for e in observed['events'] if e['available_ms']>t-24*60*MINUTE]
            scales[str(minutes)]=dict(last_completed_ms=completed[-1]['end_ms'],observation=observed,
                                      sensitivity=sensitivity,recent_events_24h=recent)
            lines += [f'### {minutes}분 관찰 — 마지막 완성 {utc(completed[-1]["end_ms"])}','',
                      '| 종류 | 최근 두 가격 | 고점·저점 봉 종료 | 실제 확인 시각 | 최초 돌파 주기 / 현재 종가 위치 |',
                      '| --- | --- | --- | --- | --- |']
            for kind,label in [('high','고점'),('low','저점')]:
                pair=observed['latest'][kind]
                lines.append('| '+' | '.join([label, ' → '.join(f"{p['price']:,.1f}" for p in pair),
                    ' → '.join(utc(p['pivot_bar_end_ms']) for p in pair),
                    ' → '.join(utc(p['available_ms']) for p in pair),
                    ' → '.join(p['state']+'/'+p['latest_close_position'] for p in pair)])+' |')
            lines+=['','확인 봉 수별 최근 구조: '+ '; '.join(f"{f}개: 고점 {relations[r['high']]}, 저점 {relations[r['low']]}" for f,r in sensitivity.items())+'.',
                    '',f'최근 24시간 사건 {len(recent)}개 중 마지막 5개(전체는 JSON):','',
                    '| 확인 시각 | 기준 가격 | 관찰 | 원본 고점·저점 ID |','| --- | ---: | --- | --- |']
            for e in recent[-5:]:
                lines.append(f"| {utc(e['available_ms'])} | {e['price']:,.1f} | {e['kind']} | {e['pivot_id']} |")
            if not recent: lines.append('| — | — | 없음 | — |')
            lines.append('')
        cards.append(dict(decision_utc=old['decision_utc'],scales=scales,direction='unassessed',action=None))
        lines+=['행동 연결: 이 구조와 기존 매물대 반응을 함께 검토한다. 고점·저점 한 쌍 또는 경계 이탈만으로 전량 종료·반대 방향 진입을 확정하지 않는다. 같은 방향의 새 추가 근거와 되돌림 축소 근거도 별도로 필요하다.','']
    output=dict(status='exploratory_structural_evidence_not_direction_rule',orders_generated=0,
                source_sha256={str(source.relative_to(ROOT)):hashlib.sha256(source.read_bytes()).hexdigest(),
                               str(archive.relative_to(ROOT)):digest},
                code_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
                    [Path(__file__),ROOT/'app/research/recovery/structure_review.py']},
                method=dict(history_start_utc='2026-08-08T00:00:00Z',flank=2,sensitivity_flanks=[1,2,3],
                            availability='at completed candle end, no additional feed delay modelled',
                            state='failed is a historical close recrossing, not a current directional label'),cards=cards)
    out=ROOT/'reports/validation/zone_structure_cards_20260919'
    out.mkdir(parents=True,exist_ok=False)
    (out/'structure.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    (out/'structure.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps([dict(time=c['decision_utc'],scales={k:v['sensitivity'] for k,v in c['scales'].items()}) for c in cards],ensure_ascii=False))


if __name__=='__main__':run()
