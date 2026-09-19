"""Point-in-time context cards; descriptive windows are not directional votes."""
from pathlib import Path
from datetime import datetime, timezone
from zipfile import ZipFile
import csv
import io
import json
import hashlib
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.recovery.position_alternatives import PositionExample, ExampleCosts, alternative
from app.research.recovery.models import jsonable

MINUTE = 60_000
SLOT = 15 * MINUTE


def stamp(value):
    return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000)


def utc(value):
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()


def price_context(rows, decision_ms, windows=(15, 60, 240, 1440)):
    # Index only already available, completed candles. Future rows are immaterial.
    known = {r['end_ms']: r for r in rows if r['end_ms'] <= decision_ms}
    if decision_ms not in known:
        raise ValueError('missing decision candle')
    result = {}
    for minutes in windows:
        times = range(decision_ms - minutes * MINUTE, decision_ms + 1, MINUTE)
        if any(t not in known for t in times):
            raise ValueError('incomplete price history')
        baseline = known[decision_ms - minutes * MINUTE]['close']
        block = [known[t] for t in times if t > decision_ms - minutes * MINUTE]
        result[str(minutes)] = dict(change=block[-1]['close'] - baseline,
            return_pct=100 * (block[-1]['close'] / baseline - 1),
            high=max(r['high'] for r in block), low=min(r['low'] for r in block),
            volume_btc=sum(r['volume'] for r in block))
    return result


def profile_context(hist, offset, start_ms, decision_ms, low, high, windows=(96, 672, 5760)):
    # Upper bin boundary is exclusive: [low, high), unlike geometric candle touches.
    end = (decision_ms - MINUTE - start_ms) // SLOT
    if end > len(hist) or end < max(windows):
        raise ValueError('incomplete profile history')
    left, right = int(low // 50) - offset, int(high // 50) - offset
    if low % 50 or high % 50 or not 0 <= left < right <= hist.shape[1]:
        raise ValueError('invalid aligned profile range')
    result = {}
    for slots in windows:
        values = hist[end - slots:end].sum(axis=0)
        total = float(values.sum())
        zone = float(values[left:right].sum())
        result[str(slots // 4)] = dict(total_btc=total, zone_btc=zone,
                                     share_pct=100 * zone / total if total else None)
    return dict(cutoff_exclusive_ms=start_ms + end * SLOT,
                available_ms=start_ms + end * SLOT + MINUTE, windows_hours=result)


def run():
    sources = {
        'events': ROOT/'reports/validation/frozen_zone_path_48h_20260919/events.jsonl',
        'snapshot': ROOT/'reports/validation/volume_zone_review_v02_20260919/frozen_zones.json',
        'candles': ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip',
        'profile': ROOT/'data/historical/btcusdc_aggprofiles_20260919/histogram_50usdc_15min.npz'}
    hashes = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in sources.items()}
    assert hashes['candles'] == sources['candles'].with_name(sources['candles'].name+'.CHECKSUM').read_text().split()[0]
    assert hashes['profile'] == 'a8068ecca2304219edcc0cf7c64829b7e9894665c934238fb7880059158ee35b'
    snapshot = json.loads(sources['snapshot'].read_text())
    events = [json.loads(line) for line in sources['events'].read_text().splitlines()]
    selected = ['2026-08-15T08:55:00Z', '2026-08-15T09:28:00Z',
                '2026-08-16T22:03:00Z', '2026-08-16T22:04:00Z']
    rows = []
    with ZipFile(sources['candles']) as archive, archive.open(archive.namelist()[0]) as stream:
        for r in csv.DictReader(io.TextIOWrapper(stream)):
            rows.append(dict(end_ms=int(r['open_time'])+MINUTE,
                             **{k: float(r[k]) for k in ('close', 'high', 'low', 'volume')}))
    costs = ExampleCosts('.0004', '.00005', '.0002', '.1', '.001', '2')
    position = PositionExample(1, '.2', '63050', 0, '5.044', '5.044', 10000)
    notes = [
        '구간 첫 접촉. 가격 도달은 확인됐지만 반등 유지나 새 추가 근거는 아직 확인되지 않았다.',
        '상단보다 2.9 USDC 위 마감. 회복 관찰이지만 주된 상승 추세·재지지 성공을 뜻하지 않는다.',
        '하단보다 3.7 USDC 아래 마감. 이 시점에는 다음 봉 복귀를 알 수 없다. 추가 근거를 재검토하되 전량 종료·숏 전환으로 연결하지 않는다.',
        '하단보다 0.4 USDC 위 복귀. 직전 이탈 이력을 유지한다. 한 봉 복귀만으로 새 물타기 근거가 완성되지는 않는다.']
    cards = []
    with np.load(sources['profile']) as cache:
        for value, note in zip(selected, notes):
            t = stamp(value)
            event = next(e for e in events if e['available_ms'] == t and e['zone_id'] == 'Z01')
            context = price_context(rows, t)
            profile = profile_context(cache['hist'], int(cache['offset']), stamp('2026-06-01T00:00:00Z'), t, 62750, 62900)
            assert profile['available_ms'] <= t
            outcomes = [alternative(position, costs, mark=event['close'], action=a, quantity=q,
                                    stress_moves=(2000, 3000))
                        for a, q in [('wait', 0), ('increase', '.1'), ('retracement_reduce', '.1')]]
            cards.append(dict(decision_utc=value, observed_event=event, price=context, profile=profile,
                contemporaneous_reading=note, direction='unassessed', selected_action=None,
                missing_evidence=['주된 방향의 구조적 근거와 무효화 조건',
                                  '되돌림 축소 자리 또는 독립적인 새 추가 반응',
                                  '실제 잔량·미체결·사용 가능한 증거금'],
                hypothetical_alternatives=outcomes))
    artifact = dict(status='conditional_review_not_strategy_validation', orders_generated=0,
        selection='four previously documented touch/reclaim/break/recovery cases; not an untouched holdout',
        assumptions=dict(position=position, costs=costs,
            inventory='each card independently starts from the same hypothetical long; not a sequence of fills',
            funding='zero assumed, not measured', margin='simple leverage proxy, not exchange capacity',
            direction='windows describe price movement, no voting or mandatory timeframe',
            bars='available at minute end; profile assumes one minute delivery delay'),
        frozen_zone=snapshot['zones'][0], source_sha256=hashes,
        code_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (Path(__file__), ROOT/'app/research/recovery/position_alternatives.py')}, cards=cards)
    out = ROOT/'reports/validation/zone_decision_cards_20260919'
    out.mkdir(parents=True, exist_ok=False)
    (out/'cards.json').write_text(json.dumps(jsonable(artifact), ensure_ascii=False, indent=2)+'\n')
    lines = ['# 매물대·시장 관찰·보유 상태를 연결한 판단 카드', '',
        '시점은 UTC. Z01 62,750–62,900은 최초 동결 구간을 유지했다. 거래량 집계는 [하단, 상단) 범위다.',
        '가격 변화 창은 설명용이며 추세 투표가 아니다. 각 카드에는 그 시점까지의 완성 봉과 확보 가능한 체결량만 들어간다.',
        '사례 선정은 기존 검토 자료를 사용했다. 새 표본 검증·실제 거래 재현이 아니다.', '',
        '각 카드는 독립적으로 롱 0.2 BTC·평단 63,050·초기 계좌 10,000을 가정한다. 방향 판정·체결 이력은 가정하지 않는다.',
        '편도 수수료 4bp·반스프레드 0.5bp·슬리피지 2bp·증거금 2배 단순 산식·펀딩 0 가정. 실제 계좌 여력이 아니다.', '']
    for c in cards:
        lines += ['## '+c['decision_utc'], '', c['contemporaneous_reading'], '',
            '| 과거 구간 | 가격 변화(USDC) | 구간 최저–최고 |', '| --- | ---: | --- |']
        for minutes, r in c['price'].items():
            lines.append(f"| {minutes}분 | {r['change']:+,.1f} | {r['low']:,.1f}–{r['high']:,.1f} |")
        p = c['profile']
        lines += ['', f"체결량 집계 종료: {utc(p['cutoff_exclusive_ms'])}. 최초 24시간 점유율 {snapshot['zones'][0]['shares']['24h']*100:.2f}%.", '',
                  '| 집계 창 | Z01 체결량(BTC) | 전체 대비 점유율 |', '| --- | ---: | ---: |']
        for h, r in p['windows_hours'].items():
            lines.append(f"| {h}시간 | {r['zone_btc']:,.2f} | {r['share_pct']:.2f}% |")
        lines += ['', '서로 겹치는 집계 창의 점유율은 합산하지 않는다. 거래 집중은 매수 지지나 매도 저항의 확정 근거가 아니다.', '',
                  '| 가정 행동 | 잔량 BTC | 전체 순손익 | 여력 변화(가정) | 추가 $3,000 하락 시 순손익 |',
                  '| --- | ---: | ---: | ---: | ---: |']
        for label, r in zip(['유지', '0.1 추가', '총수량 절반 축소'], c['hypothetical_alternatives']):
            lines.append(f"| {label} | {r['after'].quantity:.3f} | {r['total_net']:.2f} | {r['free_margin_change']:+.2f} | {r['adverse_scenarios'][-1]['pnl']:.2f} |")
        lines += ['', '조건부 대응: 주된 방향이 유지되고 새 반응·여력이 확인되면 같은 방향 추가를 검토한다. 추가 물량을 덜어낼 되돌림으로 판단했다면 총수량 최소 절반을 축소하며 본절을 필수로 기다리지 않는다.',
                  '미충족: '+ ' / '.join(c['missing_evidence'])+'.',
                  '따라서 이 카드의 확정 행동은 비워 둔다. 약손절 수량·전량 종료·반대 방향 진입을 가격 경계만으로 정하지 않는다.', '']
    (out/'cards.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps([dict(time=c['decision_utc'], changes={k:v['change'] for k,v in c['price'].items()},
        shares={k:v['share_pct'] for k,v in c['profile']['windows_hours'].items()}) for c in cards]))


if __name__ == '__main__':
    run()
