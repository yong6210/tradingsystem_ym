"""Fixed 48-hour observation of already frozen levels, with conditional actions."""
from pathlib import Path
import sys
import csv
import io
import json
import hashlib
from zipfile import ZipFile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.recovery.models import Bar, jsonable
from app.research.recovery.zone_review import ReviewZone, ZoneReview


def stamp(iso):
    return int(datetime.fromisoformat(iso.replace('Z','+00:00')).timestamp()*1000)


def utc(ms):
    return datetime.fromtimestamp(ms/1000, timezone.utc).strftime('%m-%d %H:%M')


def interpretation(event):
    position, prior = event['close_position'], event['previous_position']
    if 'both_boundaries_in_range_sequence_unknown' in event['labels']:
        return '봉 안에서 양 경계 통과: 접촉 순서 불명. 방향·진입·축소를 이 봉만으로 확정하지 않음.'
    if 'gap_over_zone_without_observed_trade' in event['labels']:
        return '구간을 건너뜀: 해당 구간에서 체결·반응했다고 가정하지 않음.'
    if position == 'inside':
        return '구간 내부: 방향 미확정이면 신규 보류. 보유 중이면 반응·여력 관찰, 가격 도달만으로 추가하지 않음.'
    if position == 'below' and prior != 'below':
        return '아래 마감: 롱 추가 근거 재평가·확대 보류 후보. 기존 물량 약손절 여부는 별도 근거 필요. 숏 자동 전환 아님.'
    if position == 'above' and prior != 'above':
        return '위 마감: 롱은 회복/돌파 관찰 후보, 숏은 추가 근거 재평가 후보. 이전 이탈 이력은 지우지 않음.'
    if event['touched'] and position == 'above':
        return '접촉 후 위 마감: 롱 방향이 별도로 유효하면 지지 반응 검토. 숏 보유는 덜어낼 자리 검토, 실제 평단·비용·여력 필요.'
    if event['touched'] and position == 'below':
        return '접촉 후 아래 마감: 숏 방향이 별도로 유효하면 저항 반응 검토. 롱 보유는 덜어낼 자리 검토, 실제 평단·비용·여력 필요.'
    return '새 방향 근거 없음. 기존 판단과 보유 상태를 확인하며 관찰.'


def run():
    source = ROOT/'reports/validation/volume_zone_review_v02_20260919'
    raw_snapshot = (source/'frozen_zones.json').read_bytes()
    snapshot = json.loads(raw_snapshot)
    frozen_sha = hashlib.sha256(raw_snapshot).hexdigest()
    start = stamp(snapshot['data_cutoff_exclusive_utc'])
    end = start + 48*3600000
    review = ZoneReview([ReviewZone(z['id'],z['low'],z['high']) for z in snapshot['zones']],
                        reference_price=snapshot['reference_price'], available_ms=stamp(snapshot['decision_utc']))
    archive = ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    raw = archive.read_bytes()
    archive_sha = hashlib.sha256(raw).hexdigest()
    assert archive_sha == archive.with_name(archive.name+'.CHECKSUM').read_text().split()[0]
    events, bars = [], []
    with ZipFile(io.BytesIO(raw)) as z, z.open(z.namelist()[0]) as fp:
        for row in csv.DictReader(io.TextIOWrapper(fp)):
            opening = int(row['open_time'])
            if start <= opening < end:
                b = Bar(opening+60000,row['open'],row['high'],row['low'],row['close'],opening+60000)
                bars.append(b)
                events.extend(review.observe(b))
    assert len(bars)==2880 and bars[0].end_ms==start+60000 and bars[-1].end_ms==end
    # Existing first-six-hour results came from independent aggTrade OHLC.
    earlier = json.loads((source/'forward_observations.json').read_text())
    assert earlier['frozen_snapshot_sha256']==frozen_sha
    for i, record in enumerate(earlier['observations']):
        block = bars[i*15:(i+1)*15]
        assert stamp(record['available_utc'])==block[-1].end_ms
        assert abs(float(block[-1].close)-record['close'])<.00001
        for old in record['zones']:
            zone = review.zones[old['id']]
            touched = min(b.low for b in block)<=zone.high and max(b.high for b in block)>=zone.low
            assert touched==old['touched']
    for event in events:
        event['conditional_review'] = interpretation(event)
    touches = {key: state['touch_minutes'] for key,state in review.states.items()}
    summary = dict(frozen_snapshot_sha256=frozen_sha, archive_sha256=archive_sha,
                   start_utc=utc(start), end_utc=utc(end), minutes=len(bars), event_count=len(events),
                   touched_minutes_by_zone=touches, states=review.states,
                   six_hour_independent_ohlc_comparison='PASS',
                   strategy_decisions='not approved; conditional interpretations only',
                   orders_generated=0, first_event=events[0] if events else None,
                   source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in [Path(__file__),ROOT/'app/research/recovery/zone_review.py']})
    output = ROOT/'reports/validation/frozen_zone_path_48h_20260919'
    output.mkdir(parents=True,exist_ok=False)
    (output/'summary.json').write_text(json.dumps(jsonable(summary),ensure_ascii=False,indent=2)+'\n')
    (output/'events.jsonl').write_text(''.join(json.dumps(jsonable(e),ensure_ascii=False)+'\n' for e in events))
    lines = ['# 固定 매물대의 48시간 순차 검토'.replace('固定','고정'),'',
             '2026-08-15 00:01 UTC에 확보한 구간을 바꾸지 않았다. 방향·보유 상태는 미확정이며 주문을 생성하지 않았다.','',
             '| 구간 | 범위 | 접촉한 1분봉 수 | 최초 접촉/위치 변화 | 마지막 종가 위치 |',
             '| --- | --- | ---: | --- | --- |']
    for z in snapshot['zones']:
        hits=[e for e in events if e['zone_id']==z['id']]
        lines.append(f"| {z['id']} | {z['low']:,.0f}–{z['high']:,.0f} | {touches[z['id']]} | {utc(hits[0]['available_ms']) if hits else '없음'} | {review.states[z['id']]['position']} |")
    lines += ['', '## 시점별 검토', '', '아래 시점은 새 접촉·종가 위치 변화 등의 관찰이며 지지 성공/실패 확정 신호가 아니다. 반복되는 동일 설명은 이벤트 원본에 남겼다.','',
              '| UTC | 구간 | 종가 | 관찰 | 조건부 행동 검토 |','| --- | --- | ---: | --- | --- |']
    seen = set()
    for e in events:
        key=(e['zone_id'],tuple(e['labels']))
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"| {utc(e['available_ms'])} | {e['zone_id']} | {e['close']:,.1f} | {', '.join(e['labels'])} | {e['conditional_review']} |")
    lines += ['', '## 보유 상태가 다른 경우', '',
              '- 무포지션: 가격이 구간에 닿았다는 사실만으로 방향과 진입을 함께 확정하지 않는다.',
              '- 같은 방향 보유: 신규 추가 근거인지 기존 반응의 반복인지 구별하고, 추가 후에도 대응할 여력을 계산한다.',
              '- 추가 물량 보유 후 되돌림: 반대쪽 구간 반응에서 축소를 검토하되 실행을 결정하면 총수량 최소 절반을 덜어낸다. 전체 본절은 필수 조건이 아니다.',
              '- 구간 이탈: 보유 일부의 근거 약화와 전체 추세 전환을 구별한다. 약손절의 수량·발동 기준을 임의로 고정하지 않는다.',
              '- 미체결 존재: 실제 체결·취소가 확정되기 전 다음 주문 수량을 결정하지 않는다.', '',
              '이 관찰로 선정 구간이 충분하다고 검증한 것은 아니다. 새 매물대가 형성되면 그때부터 새 버전으로 별도 기록해야 하며 과거 판단을 소급 변경하지 않는다.']
    (output/'decision_review.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(jsonable(summary),ensure_ascii=False))


if __name__=='__main__':
    run()
