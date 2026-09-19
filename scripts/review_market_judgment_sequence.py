"""Stage 1/2 review packet; historical evidence and conditional accounting only."""
import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

from replay_cycling_trial_v1 import ROOT, ARCHIVE, SNAPSHOT, stamp
from review_protected_market_structure import at
from app.research.recovery.models import jsonable
from app.research.recovery.position_alternatives import PositionExample, ExampleCosts, alternative

# Previously inspected development checkpoints, fixed before this replay.
CHECKPOINTS = [
    ('2026-08-15T00:01:00Z', '최초 진입 검토', '주된 방향의 근거가 승인되지 않아 진입 보류.', 'U1/U2/U3'),
    ('2026-08-15T08:55:00Z', 'Z01 접촉', '가격 도달만으로 추가할 수 없다. 새 반응과 여력 한도가 필요하다.', 'U1/U3'),
    ('2026-08-15T09:28:00Z', 'Z01 상단 회복', '위 마감은 관찰 사실이다. 충분한 회복 및 축소 발동인지는 미정이다.', 'U4'),
    ('2026-08-15T10:33:00Z', '국소 고점 접촉', '고점 아래 마감은 반대 근거 후보다. 전체 숏 전환으로 확대하지 않는다.', 'U1/U4'),
    ('2026-08-15T17:55:00Z', '재추가 검토', '저점 위 소폭 마감만으로 재추가하지 않는다. 가까운 목표의 비용 후 여유와 목적을 먼저 확인한다.', 'U3'),
    ('2026-08-16T22:03:00Z', 'Z01 하단 이탈', '기존 지지 논리와 충돌한다. 해당 추가 근거 재검토가 필요하며 주된 전환은 미판정이다.', 'U1/U5'),
    ('2026-08-16T22:04:00Z', 'Z01 내부 복귀', '한 봉 복귀로 직전 이탈 이력을 지우거나 추가를 승인하지 않는다.', 'U3/U5'),
    ('2026-08-16T22:56:00Z', '아래에서 재접근', '국소 실패와 주된 하락 전환을 구별해야 한다. 잔여 물량 처리도 미정이다.', 'U1/U4/U5'),
    ('2026-08-17T00:01:00Z', '관찰 종료', '자료 구간 종료는 전량 종료 신호가 아니다. 잔량과 미결 판단을 이월한다.', 'U1/U5'),
]


def observation(rows, snapshot, t):
    if stamp(snapshot['decision_utc']) > t:
        raise ValueError('zone manifest not yet available')
    known = [r for r in rows if r['end_ms'] <= t]
    if not known or known[-1]['end_ms'] != t:
        raise ValueError('missing decision candle')
    card = at(known, t, stamp('2026-08-01T00:00:00Z'), 'confirmed_path_reanchor')
    bar = known[-1]
    zones = []
    for z in snapshot['zones']:
        if z['id'] not in ('Z01', 'Z02'):
            continue
        zones.append(dict(id=z['id'], low=z['low'], high=z['high'],
            available_ms=stamp(snapshot['decision_utc']),
            formation='trailing executed-volume windows before 2026-08-15T00:00Z; not a precise first-formation timestamp',
            formation_start_ms=None, shares=z['shares'],
            touch=bar['low'] <= z['high'] and bar['high'] >= z['low'],
            close_position='above' if bar['close'] > z['high'] else 'below' if bar['close'] < z['low'] else 'inside'))
    return dict(bar=bar, volume_zones=zones, structure=card,
                main_direction='unassessed', max_evidence_ms=t)


def build(rows, snapshot):
    costs = ExampleCosts('.0004', '.00005', '.0002', '.1', '.001', '2')
    # A counterfactual path illustrates arithmetic; it is NEVER selected by the observations.
    position = PositionExample(1, 0, None, 0, 0, 0, 10000)
    cases = []
    for i, (date, scene, reasoning, unresolved) in enumerate(CHECKPOINTS):
        t = stamp(date)
        evidence = observation(rows, snapshot, t)
        if evidence != observation([r for r in rows if r['end_ms'] <= t], snapshot, t):
            raise ValueError('future suffix affected evidence')
        action = 'increase' if i in (0, 1) else 'retracement_reduce' if i in (2, 7) else 'wait'
        quantity = '.1' if action == 'increase' else position.quantity / 2 if action == 'retracement_reduce' else 0
        before = position
        result = alternative(position, costs, mark=evidence['bar']['close'], action=action,
                             quantity=quantity, stress_moves=(2000, 3000))
        position = result['after']
        cases.append(dict(utc=date, scene=scene, evidence=evidence,
            direction_reason='각 시간 창의 추진·반응 구조는 아래 시험 관찰에 기록. 중요도 선정과 전환 기준 미정이므로 주된 방향으로 승격하지 않음.',
            opposing_evidence=reasoning,
            selected_action='defer_new_exposure', selected_position=dict(quantity='0', average=None, realized_net='0', free_margin_proxy='10000'),
            existing_inventory_action='unresolved; not an instruction to hold or liquidate',
            reconsider_when='새 추진·반응의 확인 시각과 기존 근거 무효화를 함께 설명하고 '+unresolved+'를 결정했을 때 재심사',
            unresolved=unresolved.split('/'),
            conditional_only=dict(status='unapproved_counterfactual_not_execution', assumed_action=action,
                                  before=before, result=result)))
    return dict(status='stage2_review_with_unresolved_entry_and_management',
        stages={'1': 'complete', '2': 'reviewed_with_gaps', '3': 'not_started', '4': 'not_started', '5': 'blocked_by_judgment', '6': 'not_started'},
        assumptions=dict(costs=costs, funding='zero assumption', data='previously inspected development sample; not a blind or holdout study',
            account='hypothetical 10000 USDC; 2x simple margin proxy; no actual account or reserved orders',
            counterfactual='long entry .1, add .1, halve .2, later halve .1; choices illustrate missing decisions, not approved signals',
            fills='same-close mathematical friction examples, not historical fills or executable backtest',
            formation='trailing profile support and availability recorded; precise zone first formation remains unknown'),
        orders_generated=0, prefix_invariance='PASS', cases=cases)


def render(packet):
    lines = ['# 한 구간의 시간순 판단표', '',
        'BTCUSDC · 2026-08-15 00:01~08-17 00:01 UTC. 이미 본 개발 자료의 사후 검토다. 각 계산에는 해당 시각까지의 완성 봉만 전달했다. 진정한 미관측 맹검이나 새 표본 평가는 아니다.', '',
        '**결정:** 최초 진입 근거가 미완성이므로 무포지션 출발 경로에서는 신규 노출을 보류한다. 기존 보유의 유지·축소 판단은 별도 미결이며 자동 보유 지시가 아니다.',
        '**미정:** 주된 방향·중요 구간·새 추가 근거·축소 발동·약손절. 아래 가상 진입→추가→축소 장부가 맞아도 이 빈칸을 해결하지 못한다.', '',
        '| UTC | 장면 / 종가 | 주된 방향·구조 관찰(시험) | 반대 근거·행동 이유 | 행동 / 미정 | 재판단 조건 |',
        '| --- | --- | --- | --- | --- | --- |']
    for c in packet['cases']:
        evidence = c['evidence']
        states = []
        for minutes, scale in evidence['structure']['scales'].items():
            candidate = scale['trial']['candidate']
            states.append(f"{minutes}분: " + ('없음' if candidate is None else f"{candidate['side']}/{candidate['status']}, 반응가격 {candidate['protected']['price']}"))
        lines.append(f"| {c['utc']} | {c['scene']} / {evidence['bar']['close']} | 주된 방향 미판정; {'; '.join(states)} | {c['opposing_evidence']} | 신규 대기 / {', '.join(c['unresolved'])} | {c['reconsider_when']} |")
    lines += ['', '실제 계좌 정보는 제공되지 않았다. 위 선택 경로의 보유는 각 시점 0 BTC·평단 없음·실현손익 0이며, 자금 10,000 USDC는 시험 가정이다.', '',
        '## 중요 구간과 가격 역할', '',
        'Z01 62,750~62,900과 Z02 63,350~63,500은 8월 15일 00:00 이전 체결량 창으로 선정되어 00:01부터 알려진 후보다. 정확한 최초 형성 시각과 중요도는 미정이다. 창별 비중·매 시점 접촉/종가 위치는 JSON에 보존했다. 피벗의 형성 봉·확인 시각·무효화·반응 기준도 JSON에 있으며 매물대 폭으로 바꾸지 않는다.', '',
        '## 조건부 장부 — 승인되지 않은 행동의 계산 예시', '',
        '롱 진입·추가·축소를 했다고 가정한 별도 경로다. 수수료 4bp·반스프레드 0.5bp·슬리피지 2bp·펀딩 0, 관찰 종가 주변 즉시 계산 체결이며 실제 체결 재현이 아니다. 미체결·증거금 예약·역사적 펀딩 자료가 없어 실제 여력은 알 수 없다.', '',
        '| UTC | 가정 행동 | BTC 전→후 | 평단 | 누적 실현총손익 | 누적 비용 | 총손익 | 여력 대용치 | 잔량 본절 / 전체 회복 체결가 |',
        '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |']
    def number(value):
        return '없음' if value is None else f'{value:.2f}'
    for c in packet['cases']:
        h = c['conditional_only']; r = h['result']; p = r['after']
        lines.append(f"| {c['utc']} | {h['assumed_action']} | {h['before'].quantity}→{p.quantity} | {number(p.average)} | {p.realized_gross:.2f} | {p.paid_costs:.2f} | {r['total_net']:.2f} | {r['free_margin_proxy']:.2f} | {number(r['position_break_even_fill'])} / {number(r['campaign_break_even_fill'])} |")
    lines += ['', '실현총손익에서 누적 비용을 빼면 누적 비용 차감 실현액이다. 총손익에는 잔량의 평가손익도 포함한다. 마지막 잔량은 강제 종료하지 않았다.', '',
        '## 단계 종료 판단', '',
        '1단계 원칙 분리는 완료했다. 2단계는 실제 판단표와 미정 사항을 작성했으나, 최초 진입·추가·축소의 시장 근거를 이어 설명하지 못하므로 통과하지 못했다. 방향을 가정한 장부 예시를 검증된 매매 사례로 보고하지 않는다.',
        '다음은 00:01의 주된 방향과 무효화 근거(U1)를 같은 자료로 명세화하고 후반 국소 이탈과 대조하는 것이다. 그 전에는 새 엔진 연결·성과 최적화·별도 평가를 진행하지 않는다.', '']
    return '\n'.join(lines)


def main():
    raw = ARCHIVE.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != ARCHIVE.with_name(ARCHIVE.name+'.CHECKSUM').read_text().split()[0]:
        raise ValueError('source checksum mismatch')
    rows = []
    with ZipFile(io.BytesIO(raw)) as archive, archive.open(archive.namelist()[0]) as fp:
        for r in csv.DictReader(io.TextIOWrapper(fp)):
            rows.append(dict(end_ms=int(r['open_time'])+60000,
                             **{k: float(r[k]) for k in ('high', 'low', 'close')}))
    packet = build(rows, json.loads(SNAPSHOT.read_text()))
    sources = [ARCHIVE, SNAPSHOT, Path(__file__),
               ROOT/'scripts/review_protected_market_structure.py',
               ROOT/'docs/research/MARKET_JUDGMENT_SEQUENCE.md',
               *[ROOT/'app/research/recovery'/name for name in
                 ('structure_review.py', 'protected_structure.py', 'position_alternatives.py', 'models.py')]]
    packet['source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    out = ROOT/'reports/validation/market_judgment_sequence_20260919'
    out.mkdir(parents=True, exist_ok=True)
    (out/'review.md').write_text(render(packet))
    (out/'review.json').write_text(json.dumps(jsonable(packet), ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'stages': packet['stages'], 'report': str(out/'review.md')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
