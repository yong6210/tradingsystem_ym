"""Readable Q001 findings and a narrowly scoped Desktop source receipt."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/validation/q001_execution_cost_evidence_20260919'
REPORT = ROOT / 'docs/research/experiments/Q001_RESULTS_2026_09_19.md'


def save(path, value):
    with path.open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def fmt(value):
    return f'{float(value):.5f}'


def main():
    summary = json.loads((OUT / 'summary.json').read_text())
    verification = json.loads((OUT / 'verification.json').read_text())
    for name, expected in verification['artifacts'].items():
        assert hashlib.sha256((OUT / name).read_bytes()).hexdigest() == expected
    overall = summary['overall']
    imm = overall['buy']['immediate']['metrics']['total_bps']
    move = overall['absolute_mid_move_3s_bps']
    table = []
    for date, data in summary['per_date'].items():
        cost = data['results']['buy']['immediate']['metrics']['total_bps']
        delay = data['results']['absolute_mid_move_3s_bps']
        table.append(f"| {date} | {data['valid_points']} | {fmt(cost['mean'])} | {fmt(cost['maximum'])} | {delay['n']} | {fmt(delay['p95'])} | {fmt(delay['maximum'])} |")
    signed = []
    for key, label in [('buy', '매수'), ('sell', '매도')]:
        data = overall[key]['delayed']['metrics']['total_bps']
        signed.append(f"| {label} | {fmt(data['mean'])} | {fmt(data['median'])} | {fmt(data['p95'])} | {fmt(data['minimum'])} | {fmt(data['maximum'])} |")
    n_legs = sum(v['complete_leg_calculations'] for v in verification['by_date'].values())
    text = f'''# Q001 결과 — 표시 호가 비용과 실제 체결 비용을 구분

2026-09-19. **짧은 기존 표본의 표시 비용 분해는 검산 통과. 실제 체결 비용 보정·수익성 검증은 미완료다.** 새 수익 후보, 개선된 계좌 손익, 5% 손실 선호 충족을 입증한 결과가 아니다.

## 확인한 사실

사전 [질문 명세](Q001_EXECUTION_COST_EVIDENCE.md)에 따라 기존 E032 v2의 분기 첫날 UTC 00:00–00:10 구간 8개를 모두 사용했다. 원래 4,800시점 중 유효 {summary['valid_points']:,}시점, 연속 3초 비교 {move['n']:,}개다. 매수·매도는 같은 시각의 대응된 가상 계산이며 거래 횟수가 아니다.

0.001 BTC는 유효 시점마다 양쪽 최우선 호가 물량 안에 들어갔다. 표시 물량 소화에 따른 추가 깊이 비용은 0이었다. 그렇다고 주문 도착 시 물량 잔존이나 실제 체결이 보장되지는 않는다.

| 지표 | 평균 bp | 중앙값 bp | 95백분위 bp | 최대 bp |
|---|---:|---:|---:|---:|
| 즉시 표시 비용: mid→최우선 호가, 편도 | {fmt(imm['mean'])} | {fmt(imm['median'])} | {fmt(imm['p95'])} | {fmt(imm['maximum'])} |
| 3초 mid 이동 절댓값: 방향과 무관 | {fmt(move['mean'])} | {fmt(move['median'])} | {fmt(move['p95'])} | {fmt(move['maximum'])} |

1bp=0.01%. 표시 비용에는 수수료가 없다. 중앙값·95백분위는 nearest rank다. 3초 가격 이동은 비용 자체가 아니라 유리하거나 불리하게 작용할 수 있는 가격 변화이며, 실제 주문 지연 측정값이 아니다.

초기 mid 대비 3초 후 표시 주문 가격의 방향별 차이는 다음과 같다. 가격 이동+미래 반스프레드+미래 깊이 비용을 모두 초기 mid로 나누어 합산했다. 음수는 그 방향에 유리한 가격 이동이며 실제 수익이 아니다.

| 가상 방향 | 평균 bp | 중앙값 bp | 95백분위 bp | 최소 bp | 최대 bp |
|---|---:|---:|---:|---:|---:|
{chr(10).join(signed)}

## 날짜별 범위

| UTC 날짜, 각 10분 | 유효 시점 | 표시 비용 평균 bp | 표시 비용 최대 bp | 3초 구간 | 절대 이동 p95 bp | 절대 이동 최대 bp |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(table)}

연속 3초 구간은 중첩되고 표본은 8개 짧은 시간대에 집중되어 있다. 4,231개의 독립 시행으로 해석하거나 전체 시장의 꼬리 비용을 추정하지 않는다. 초기 무효 545시점과 구간 끝 24시점은 3초 진단에서 제외했다. 표시 물량 부족과 표시 명목 50 USDC 미만은 이 표본에 없었다. 이것은 계정·증거금·주문 승인 검증과 다르다.

## 비용 모델에 대한 결정

| 요소 | 근거 | 현재 결정 |
|---|---|---|
| taker 2.5bp/체결, maker 0bp | 사용자 제공 요율 | 유지. 계정 독립 확인 전 실제 적용 요율로 확정하지 않음 |
| 즉시 스프레드·표시 깊이 | 이번 80분 자료 | 해당 시각·0.001 BTC의 표시 비용만 확인 |
| 3초 동안의 가격 이동 | 과거 수신 시각 기준 가상 지연 | 실측 주문 지연·전략별 역선택 비용으로 해석하지 않음 |
| 기존 추가 슬리피지 2/5bp | 연구 시나리오 | 실제 체결 비용 추정치로 확정 불가. 이번 분위수로 교체하지 않음 |
| 추가 펀딩 1bp 스트레스 | 연구 시나리오 | 실제 역사적 펀딩과 구분. 이번 호가 진단으로 보정 불가 |
| 체결·부분 체결·취소 경합·maker 대기열 | 자료 없음 | 미확인. 표시 호가로 체결을 확정하지 않음 |

사용자 taker 요율을 양쪽에 적용하면 왕복 수수료만 대략 5bp(0.05%)다. 정확한 금액은 진입·청산 각각의 실제 체결 명목에 따라 달라진다. 이를 넘는 가격 이익·현금흐름 근거가 없으면 호가 스프레드가 작다는 사실만으로 수익 기회가 생기지 않는다.

기존 봉 엔진의 진입 가격은 진입 분봉 open을 바탕으로 슬리피지·틱을 적용하고, 호가 기반 E032는 실제 표시 호가에 추가 2/5bp·틱을 적용한다. 두 값은 기준 가격이 다르다. 이번 mid 기준 비용으로 기존 봉 비용을 대체하거나, 진입 시점 가격에 이미 포함된 이동을 다시 더할 수 없다. 신호 발생·주문 제출·거래소 도착·체결 시각 및 기준 가격을 다음 정책에서 각각 명시해야 한다.

[Binance 공식 시장 자료 API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)는 호가 가격·수량과 시각을 제공하지만 주문 체결 영수증이 아니다. 일반 호가에서 제외되는 RPI 물량 등도 있어 표시 상위 5단계를 전체 유동성으로 부르지 않는다. 현재 API 설명으로 과거 공급자 자료의 완전성을 증명하지 않는다.

## 검산과 종료

계산 전 명세·코드·테스트·입력과 기존 기록 70개 해시를 고정했고 종료 후 일치를 확인했다. Decimal의 잔여 수량 소화와 별도 Fraction의 누적 물량 구간 계산으로 9,600행 상태 및 완전 표시 계산 {n_legs:,}건, 날짜별·전체 모든 집계값을 대조했다. 6개 테스트로 다단계 물량, 부족, 부호, 무효 구간, 시각과 분위수 경계를 확인했다. 이번 독립 검산은 저장된 grid부터의 산술이며 원시 L2 재구성을 다시 검증한 것은 아니다.

**이번 비용 자료 진단은 종료한다.** 2/5bp가 현실의 실제 비용인지 확인되지 않았다는 결론을 남기며, 과거 전략을 낮춘 비용으로 재분류하지 않는다. E048 보류와 기존 실패 판정은 유지한다. 추가 짧은 표본 수집·비용 배수 탐색으로 연구를 연장하지 않는다.

다음 성과 실험은 누가 왜 비용 이상의 가격 이익 또는 현금흐름을 제공하는지 설명하는 경제적 질문 하나와 그에 맞는 완결된 보유·청산 정책을 먼저 명세해야 한다. 이 진단만으로 어느 전략군을 선택할 수는 없다. 실제 수익성 확보는 여전히 미완료이며, 사용자 수익 목표·손실 정의·운영비도 미정이다.

원본: [집계](../../../reports/validation/q001_execution_cost_evidence_20260919/summary.json), [사전 등록](../../../reports/validation/q001_execution_cost_evidence_20260919/registration.json), [검산](../../../reports/validation/q001_execution_cost_evidence_20260919/verification.json). 신규 백테스트 0, 시장 자료 요청 0, 실주문 0, 자동화 변경 0.
'''
    with REPORT.open('x') as f:
        f.write(text)
    source = dict(label='E032 v2 BTCUSDC 표시 호가 · Q001 산술 진단',
        files=[dict(label='Q001_RESULTS_2026_09_19.md'), dict(label='summary.json'), dict(label='verification.json')],
        executedAt=summary['completed_at_utc'],
        metricDefinitions=[dict(label='즉시 표시 비용 bp', definition='초기 mid 대비 0.001 BTC 표시 주문 가격의 편도 차이. 수수료와 추가 슬리피지는 제외.'),
                           dict(label='3초 mid 이동 절댓값 bp', definition='초기 mid 대비 3초 뒤 mid 변화의 절댓값. 실제 지연이나 확정 비용이 아니다.')],
        filters=['분기 첫날 UTC 00:00–00:10의 기존 8개 구간 전수', '기존 valid 판정 충족 4,255시점',
                 '3초 진단은 4개 연속 시점이 모두 유효한 4,231개 구간', '수량 0.001 BTC, 양 방향 대응 계산'],
        caveats=['80분 재사용 표본은 대표 시장 표본이나 독립 전진 검증이 아니다.',
                 '중첩 구간과 양 방향 계산은 독립 거래가 아니다.',
                 '표시 물량은 실제 체결을 보장하지 않는다. 실제 비용 보정과 수익성은 미확인이다.'],
        evidenceFlow=[dict(kind='validation', title='표시 가격과 집계 독립 산술 대조',
            detail=f'Decimal 계산과 Fraction 계산으로 9,600행 상태 및 {n_legs:,}건 완전 표시 계산, 날짜별·전체 집계를 확인했다. 동결 해시 70개 일치.')])
    save(OUT / 'delivery_sources.json', dict(schemaVersion=1, items=[dict(
        id='q001-displayed-cost', title='작은 표시 스프레드와 3초 가격 이동의 구분',
        queries=[dict(id='displayed-components', source=source,
            reportingPeriod='2024-10-01~2026-07-01 중 8개 10분 구간',
            columns=[dict(field='metric', label='지표'), dict(field='n', label='시점/구간'),
                     dict(field='mean_bps', label='평균 bp'), dict(field='p95_bps', label='95백분위 bp'),
                     dict(field='maximum_bps', label='최대 bp')],
            rows=[dict(metric=label, n=data['n'], mean_bps=float(data['mean']),
                       p95_bps=float(data['p95']), maximum_bps=float(data['maximum']))
                  for label, data in [('즉시 표시 편도 비용', imm), ('3초 mid 이동 절댓값', move)]])])]))
    save(OUT / 'progress_addendum.json', dict(status='Q001_COMPLETE_SCOPED_DIAGNOSTIC',
        base_protocol='configs/research/current_research_protocol_v2_20260919.json',
        active_alpha_hypotheses=[], cost_calibration='UNIDENTIFIED',
        e048_status='PAUSED_UNEXECUTED', user_unknowns_preserved=True,
        next='SPECIFY_ONE_ECONOMIC_QUESTION_AND_COMPLETE_POLICY_BEFORE_PERFORMANCE_RUN',
        new_backtests=0, new_market_requests=0, actual_orders=0))
    print(REPORT)


if __name__ == '__main__':
    main()
