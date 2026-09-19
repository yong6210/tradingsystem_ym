"""Report Q002's single quote batch without turning gross basis into profit."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/validation/q002_dated_carry_preflight_20260919'
REPORT = ROOT / 'docs/research/experiments/Q002_RESULTS_2026_09_19.md'


def save(path, value):
    with path.open('x') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def main():
    result = json.loads((OUT / 'summary.json').read_text())
    verification = json.loads((OUT / 'verification.json').read_text())
    for name, expected in verification['artifacts'].items():
        assert hashlib.sha256((OUT / name).read_bytes()).hexdigest() == expected
    table, rows = [], []
    for r in result['results']:
        assert r['status'] == 'COMPONENT_DIAGNOSTIC_ONLY'
        x = r['components']
        assert x['status'] == 'DISPLAYED_COMPONENT_ONLY' and x['displayed_filters_pass']
        days = r['seconds_to_delivery'] / 86400
        gross, bp = float(x['initial_basis_component_usdt']), float(x['initial_basis_bps'])
        table.append(f"| {r['symbol']} | {days:.2f}일 | {float(x['spot_buy_vwap']):,.2f} | {float(x['future_sell_vwap']):,.2f} | {gross:.5f} | {bp:.5f} |")
        rows.append(dict(contract=r['symbol'], days_to_expiry=days, quantity_btc=.001,
            spot_cost_usdt=float(x['spot_quote_usdt']), basis_component_usdt=gross,
            basis_bps=bp, net_profit_usdc=None))
    report = f'''# Q002 결과 — 만기형 캐리의 가격차 수입과 미확인 비용

2026-09-19. **수익 원리가 있는 질문 하나를 선정하고 현재 계약·표시 가격차까지 확인했다. 순익·낙폭·실행 가능성을 검증한 전략은 아니다.**

## 무엇을 검증하려는가

현물을 사고 만기 선물을 같은 BTC 순수량만큼 팔면, 만기 정산과 현물 청산 가격이 일치할 때 최초 가격차가 남는다. 선물 상승 노출 수요와 제한된 차익거래 자금을 가격차의 배경으로 설명하는 [BIS 연구](https://www.bis.org/publications/working-paper-1087-crypto-carry)를 근거로 이 질문을 골랐다. 논문의 과거 평균 수익을 현재 Binance 계좌의 기대 수익으로 적용하지 않는다.

기존 E028은 무기한 선물의 미래 펀딩 수입에 의존했다. 이번 질문은 만기형 계약의 최초 가격차에 관한 추가 캐리 연구다. E028을 비용이나 규칙 변경으로 다시 합격시키는 실험이 아니며, 같은 캐리 계열이라는 연구 이력도 유지한다.

## 실제로 확인한 범위

공개 API 조회 당시 BTCUSDC에는 만기형 계약이 없었다. BTCUSDT의 2026-09-25·2026-12-25 만기물이 거래 중이며 0.001 BTC 최소·증분과 5 USDT 최소 명목이었다. 현물 BTCUSDT와 두 만기물의 현재 표시 물량·필터는 이 수량에서 조건을 충족했다. 실제 계정의 주문 승인·수수료·증거금 조건은 확인하지 않았다.

이는 기존 BTCUSDC 운용과 구분한 **BTCUSDT 비교 연구**다. 사용자 자금 1,000 USDC를 1,000 USDT로 간주하거나 사용자 0.025% 선물 요율을 새 계약에 적용하지 않았다. 새 계약에 대한 계정 접근·환전·매매는 없다.

## 현재 가격차는 얼마인가

조회 시각: 2026-09-18 23:17:38 UTC, 한국 2026-09-19 08:17:38. 세 depth 요청의 전체 시작~수신 폭은 {result['depth_batch_seconds']:.3f}초였다. 선물 메시지 E/T 시각·호가 정렬·표시 물량·필터 조건을 통과했지만 현물 depth에는 거래소 시각이 없어 진정한 동시 체결 가격으로 부를 수 없다. 단 한 번의 표시 호가 점검이며 재조회로 유리한 시점을 고르지 않았다.

수량은 양쪽 0.001 BTC, 현물 표시 매입 명목은 81.14429 USDT다. 현물 asks와 선물 bids의 표시 물량 가중 가격을 사용했다.

| 계약 | 만기까지 | 현물 매수 USDT/BTC | 선물 매도 USDT/BTC | 최초 가격차 수입 USDT | 현물 명목 대비 bp |
|---|---:|---:|---:|---:|---:|
{chr(10).join(table)}

1bp=0.01%. 표의 수입은 비용을 빼기 전 `0.001×(선물 표시 매도가−현물 표시 매수가)`라는 구성요소다. 진입 수수료, 현물 청산 수수료, 선물 만기 정산 수수료, 환전·운영비, 담보 비용, 지연·체결 차이와 정산 괴리를 차감하지 않았다. 실제로 진입한 거래·확정 이익·순익 예측이 아니다. 분리 선물 담보가 필요하므로 81.14 USDT만 있으면 이 거래를 유지할 수 있다는 뜻도 아니다.

9월물의 가격차는 7.65427bp, 12월물은 129.48662bp다. **정산 괴리가 0이라는 추가 조건에서**, 모든 비용이 각각 0.06211 또는 1.05071 USDT 이상이면 해당 표시 가격차 수입은 전부 소진된다. 실제 미래 괴리는 양·음 어느 쪽도 가능하므로 이 금액을 보장된 수익 상한으로도 해석하지 않는다. 12월물은 더 긴 약 97일의 자금 사용과 담보 경로를 평가해야 한다. 연환산으로 작은 금액을 확대해 제시하지 않는다.

## 손익과 위험을 분리하지 않으면 생기는 오류

만기까지 수량이 정확히 맞고 두 포지션이 유지된 경우의 선형 손익은:

`최초 가격차 수입 + q×(현물 청산가−선물 정산 지수) − 실제 비용`

이다. [공식 만기형 계약 규격](https://www.binance.com/en/about-legal/contractspecs-usdsmquarterly)을 직접 확인해 USDT 선형 현금 정산과 만기 정산 수수료를 기록했다. COIN-M FAQ의 역수 손익 산식을 사용하지 않았다. 현물 청산가는 선물 정산 지수와 자동으로 같아지지 않는다.

또한 현물 상승분이 선물 지갑의 담보로 자동 이동하지 않는다. 총 가격 방향 노출이 작더라도 숏 지갑은 중간 가격 상승이나 베이시스 확대 때 증거금 부족을 겪을 수 있다. 보유 중 강제/조기 청산이 발생하면 최초 가격차를 끝까지 수취한다는 전제가 깨진다. 따라서 합산 만기 산식만으로 손실 5% 선호를 충족했다고 판단하지 않는다.

## 이번 결정과 남은 일

| 판단 항목 | 결론 |
|---|---|
| 수익 원리 | 설명 가능: 만기형 최초 가격차 수취 |
| 현재 상품·최소 표시 주문 | BTCUSDT 만기 2개 존재, 0.001 BTC의 표시 필터·물량 조건 충족 |
| 최초 가격차 | 양수이나 최소 수량 기준 절대 금액이 작음 |
| 실제 순익 | 미판정: 새 계약/현물 요율·정산 괴리·담보·환전·운영비 미확인 |
| 사용자 조건 적합성 | 미판정: 1,000 USDC 계좌 경로와 손실 조건 미평가, 월 목표도 미정 |
| 장기·독립 검증 | 미실행: 현재 호가 한 번은 기회 빈도나 지속 수익의 증거가 아님 |
| 채택·결합·실운용 | 진행하지 않음 |

**Q002 현재 호가 선행 진단은 종료한다.** 만기형 캐리는 경제적 질문으로 보존하되 실행 자료가 불완전한 후보로 분류한다. 이번 표시 가격차만으로 주력 수익 후보로 승격하지 않는다. 좋은 가격이 나올 때까지 재조회하거나 같은 표본에서 만기·수량을 튜닝하지 않는다.

다음으로 필요한 것은 해당 계약의 실제 비용과 분리 담보·만기 청산 괴리를 반영한 정책이다. [질문 명세](Q002_DATED_CARRY_FEASIBILITY.md)의 미확정 항목을 기록했으며, 이를 빈칸 상태로 둔 채 새로운 성과 백테스트를 시작하지 않는다. 미정 사용자 목표를 임의의 수익 목표로 대체하지 않는다. 자료가 없는 maker 체결이나 자동 지갑 이체로 수익을 늘려 보이지 않는다.

## 검산과 보존

가격 조회 전에 코드·명세·계약 메타데이터·기존 보호 기록 {verification['frozen_hashes_unchanged']}개 해시를 고정했다. Decimal 물량 소화와 별도 Fraction 누적 구간 계산으로 두 계약의 표시 가격·명목·가격차·bp를 대조했다. 6개 경계 검사는 여러 호가 물량 소화, 물량 부족, bid/ask 방향, 교차 호가, 동일 정산 가격에서의 방향 손익 상쇄, 청산 괴리로 가격차가 사라지는 경우를 확인했다.

이는 호가 산술과 조건부 손익 항등식 검산이다. 실제 체결·자금 경로·수익성 검증을 의미하지 않는다. 공개 API 요청 5회(선물 계약 목록 1, 현물 계약 1, depth 3), 공식 규격 PDF 요청 1회와 웹 문헌 검토를 수행했다. 실주문·사설 계정 API·유료 자료·신규 예약·성과 백테스트는 없다. 기존 E028/Q001/방법 v2 기록과 비용 시나리오는 보존했다.

기록: [사전 등록](../../../reports/validation/q002_dated_carry_preflight_20260919/registration.json), [현재 호가 결과](../../../reports/validation/q002_dated_carry_preflight_20260919/summary.json), [검산](../../../reports/validation/q002_dated_carry_preflight_20260919/verification.json), [공식 규격 PDF](../../../reports/validation/q002_dated_carry_preflight_20260919/delivery_contract_spec.pdf).
'''
    with REPORT.open('x') as f:
        f.write(report)
    source = dict(label='Binance 공개 계약·호가 · Q002 단일 조회',
        files=[dict(label='Q002_RESULTS_2026_09_19.md'), dict(label='registration.json'),
               dict(label='summary.json'), dict(label='verification.json')],
        links=[dict(label='공식 만기형 계약 규격', url='https://www.binance.com/en/about-legal/contractspecs-usdsmquarterly')],
        executedAt=result['completed_at_utc'],
        metricDefinitions=[dict(label='최초 가격차 수입 USDT',
            definition='0.001 BTC×(선물 표시 매도 가중 가격−현물 표시 매수 가중 가격). 거래·정산·환전·운영비 차감 전 구성요소이며 실제 순익이 아니다.')],
        filters=['BTCUSDT 2026-09-25 및 2026-12-25 만기물 전수',
                 '각 0.001 BTC, 현물 asks와 선물 bids 상위 5단계',
                 '한국 시각 2026-09-19 08:17:38 단일 조회'],
        caveats=['현재 표시 호가는 실제 체결이나 진정한 동시 가격을 보장하지 않는다.',
                 '최초 가격차 외에 현물 청산가와 선물 정산 지수의 괴리 및 실제 비용이 최종 손익을 바꾼다.',
                 '선물 담보는 별도로 필요하다. USDC 계좌 수익과 5% 손실 조건은 검증하지 않았다.'],
        evidenceFlow=[dict(kind='validation', title='원본·표시 물량·산술 대조',
            detail=f"{verification['frozen_hashes_unchanged']}개 동결 해시 일치. Decimal과 Fraction으로 두 계약 표시 가격·명목·가격차·bp를 대조했다. 세 depth 요청 폭은 {result['depth_batch_seconds']:.3f}초였다.")])
    save(OUT / 'delivery_sources.json', dict(schemaVersion=1, items=[dict(
        id='q002-dated-carry', title='만기형 가격차 수입의 실제 크기',
        queries=[dict(id='current-basis-components', source=source,
            reportingPeriod='2026-09-18 23:17:38 UTC 단일 조회',
            columns=[dict(field='contract', label='만기 계약'), dict(field='days_to_expiry', label='만기까지 일'),
                     dict(field='spot_cost_usdt', label='현물 명목 USDT'),
                     dict(field='basis_component_usdt', label='비용 전 가격차 USDT'),
                     dict(field='basis_bps', label='가격차 bp')],
            rows=[{k:v for k,v in row.items() if k not in ('net_profit_usdc','quantity_btc')} for row in rows])])]))
    save(OUT / 'progress_addendum.json', dict(status='Q002_PREFLIGHT_COMPLETE_POLICY_NOT_READY',
        economic_question='DATED_LINEAR_CASH_AND_CARRY', active_economic_questions=1,
        performance_experiment_registered=False, complete_trade_policy=False,
        disposition='ECONOMIC_MECHANISM_IDENTIFIED_EXECUTION_EVIDENCE_INCOMPLETE',
        deployment_scope_changed=False, net_profit_verified=False, user_unknowns_preserved=True,
        previous_diagnostic='Q001_CLOSED_NO_COST_CHANGE', e048='PAUSED_UNEXECUTED',
        blocking_inputs_for_performance=['ACCOUNT_SPOT_DATED_FUTURE_AND_SETTLEMENT_FEES',
            'USDC_USDT_CONVERSION', 'SEPARATE_MARGIN_PATH', 'SPOT_EXIT_SETTLEMENT_MISMATCH',
            'COMPLETE_SIZING_EXIT_AND_RISK_POLICY'],
        repeat_quote_until_positive=False))
    print(REPORT)


if __name__ == '__main__':
    main()
