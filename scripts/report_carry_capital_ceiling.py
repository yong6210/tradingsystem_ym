"""Report Q005 conditional capital components without labeling them net returns."""
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/q005_carry_capital_ceiling_20260919'
REPORT=ROOT/'docs/research/experiments/Q005_RESULTS_2026_09_19.md'
def load(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):
    with p.open('x') as f:json.dump(x,f,indent=2,ensure_ascii=False);f.write('\n')


def main():
    s=load(OUT/'summary.json');v=load(OUT/'verification.json');r=load(OUT/'registration.json')
    for name,h in v['artifacts'].items():assert sha(OUT/name)==h
    for name,h in {**r['protected_hashes'],**r['source_hashes']}.items():assert sha(ROOT/name)==h
    table=[];rows=[]
    for result in s['results']:
        for key,label in [('cash_only_largest_quantity','현물만 현금으로 살 수 있는 최대 수량'),
                          ('full_entry_notional_cash_reference','선물 진입 명목 전액을 현금으로 남기는 비교')]:
            x=result[key]
            table.append(f"| {result['symbol']} | {label} | {x['quantity_btc']} | {float(x['basis_component_usdt']):.6f} | {float(x['basis_after_entry_fee_only_usdt']):.6f} | {float(x['cash_after_spot_before_fees_usdt']):.6f} |")
            rows.append(dict(contract=result['symbol'],reference=label,quantity_btc=x['quantity_btc'],
                gross_basis_usdt=float(x['basis_component_usdt']),after_entry_fee_only_usdt=float(x['basis_after_entry_fee_only_usdt']),
                remaining_cash_before_fees_usdt=float(x['cash_after_spot_before_fees_usdt'])))
    far=s['results'][1]['cash_only_largest_quantity']
    text=f'''# Q005 결과 — 가격차가 양수여도 자금 대비 수익 여유는 작다

2026-09-19. **Q002의 같은 호가를 1,000 USDT 참조 자금으로 다시 계산하니, 12월물의 초기 가격차 성분은 비용·담보를 무시해도 최대 약 12.56 USDT였다. 9월물은 일반 현물 진입 수수료 참조 조건만으로 가격차가 소진됐다.** 실제 계좌 수익성·5% 손실 선호는 검증하지 않았다.

이번 진전은 수익 규모와 필요한 비용 여유를 좁힌 것이다. 수익이 발생한 결과가 아니며 새 모델·호가·성과 백테스트를 추가하지 않았다. Q004 첫 예측은 그대로 보존했고 결과는 한국 시각 9월 20일 09:01 이후 확인 가능하다.

## 같은 호가·다른 수량을 정확히 계산

원자료는 Q002의 **2026-09-18 23:17:38 UTC** 표시 호가다. 현재 체결 가능 가격이 아니다. 0.001 BTC의 가격을 선형 확대하지 않고 수량마다 현물 asks/선물 bids의 실제 표시 물량을 소화했다. 특히 12월물 첫 bid 82,195의 수량은 0.001 BTC뿐이어서 그 이상은 다음 bid 82,190.4까지 소화한다.

자본은 **가상 1,000 USDT**다. 사용자 자금 1,000 USDC의 실제 환전 금액·비용은 아직 미확인이다. 비용 없는 현물 매입 한도 0.001~0.012 BTC 전부와 첫 불가 0.013 BTC를 두 만기에 각각 계산했다. 아래는 전 수량표의 두 대수적 참고점이며 권장 거래 수량·담보 정책이 아니다.

| 계약 | 비교 기준 | BTC | 초기 가격차 성분 USDT | 현물 진입 10bp만 뺀 잔여 USDT | 현물 매입 뒤 현금 USDT, 비용 전 |
|---|---|---:|---:|---:|---:|
{chr(10).join(table)}

초기 가격차 성분은 선물 진입 명목−현물 매입 지출이다. 표의 잔여는 **출구 수수료·선물 진입/정산·환전·운영비·체결 차이·만기 정산 괴리 이전**이며 순익이 아니다. 현물 수수료가 BTC로 차감되면 같은 순수량을 맞추기 위한 추가 매입·잔량도 필요하므로 이번 참조 차감은 완결된 순수량 정책을 대체하지 않는다.

## 수익 판단에 새로 확인한 점

**9월물:** 최초 호가 시점에서 만기까지 약 {s['results'][0]['days_at_original_quote']:.2f}일. 공개 일반 사용자 현물 기본 수수료 0.100%/편도를 참조하면, 현물만 살 수 있는 모든 12개 수량에서 가격차보다 진입 수수료가 크다. 정산 괴리 0·다른 비용 비음수·해당 요율이라는 조건에서는 가격차 수취만으로 양의 순익을 만들 수 없다. 실제 사용자 할인·프로모션 적용 여부는 확인하지 않았다. [공식 현물 수수료표](https://www.binance.com/en/fee/trading).

**12월물:** 만기까지 약 {s['results'][1]['days_at_original_quote']:.2f}일. 현물 매입만 가능한 최대 수량 0.012 BTC에서 가격차는 12.557920 USDT이고, 현물 진입 참조 수수료만 빼도 11.584189 USDT다. 나머지 모든 비용과 위험은 아직 남는다. 가격차가 0.001 BTC 결과의 단순 12배보다 작다는 점도 반영했다.

이 0.012 BTC에서는 현물 매입 뒤 현금 26.268520 USDT, 참조 진입 수수료 뒤 25.294789 USDT만 남는다. 후자를 모두 선물 지갑에 놓더라도 선물 명목 대비 **{100*float(far['cash_to_short_notional_ratio_after_entry_fee']):.4f}%**다. 이는 유지증거금·추가 비용·이체 지연을 고려하기 전 숏 가격 상승 흡수 여유의 낙관적 비율이다. 실제 청산 거리나 계좌 최대낙폭이 아니다. 현물 평가이익이 자동으로 숏 지갑의 담보가 된다고 가정하지 않는다.

선물 진입 명목 전액만큼 현금을 남기는 대수적 비교에서는 최대 0.006 BTC이며 12월물 가격차 6.281260 USDT, 현물 진입 참조 수수료 뒤 5.794394 USDT가 남는다. 이것 역시 나머지 비용 전이다. 현금 전액 참고점도 안전 보장·권장 증거금·5% 손실 보호를 뜻하지 않는다.

미래 현물 청산가와 선물 정산 지수가 다르면 실제 손익에 추가 양수/음수가 생긴다. 따라서 ‘최대 12.56’은 이번 자금·표시 호가의 **초기 가격차 성분 상한**이며 실현 순익 상한이나 수익 예측으로 부르지 않는다. 연환산·월 수익으로 확대하지 않았다.

## 확인하지 못한 비용과 결정

[공식 선물 수수료표](https://www.binance.com/en/fee/futureFee)의 이번 응답에는 숫자 요율이 없어 계정/만기물 요율은 미정이다. 기존 BTCUSDC taker 0.025%를 이 계약에 옮기지 않았다. [현재 공식 계약 페이지](https://www.binance.com/en/about-legal/contractspecs-usdsmquarterly)의 PDF 연결은 Q002 저장 규격과 같음을 확인했다. 실제 적용 요율·유지증거금·현물 수수료 자산·USDC 환전·정산 가격 불일치는 추가 근거가 필요하다.

**9월물은 위 일반 현물 요율 조건에서 경제성 근거가 없고, 12월물은 양의 성분을 보존하되 주력 수익 후보로 승격하지 않는다.** 더 큰 수량이나 낮은 담보 가정으로 작은 가격차를 수익 모델처럼 확대하지 않는다. 사용자 월 수익 목표가 미정이므로 12.56이라는 금액만으로 사용자 목표 실패를 확정하지 않지만, 현재 수익 확보의 근거가 충분하지 않다는 판단은 유지한다.

Q005 산술 진단은 종료한다. 캐리는 실행 자료 불충분 상태를 유지한다. 같은 호가의 추가 수량·만기 검색이나 새 수익률 백테스트는 열지 않는다. Q004는 1개 예측의 미래 목표를 기다리며, 새 자동 일정·계정 접근·실주문은 없다.

## 검산과 근거

{v['tests']}개 경계 검사를 통과했다. 전 {v['quantity_rows']}개 수량 행의 현물/선물 명목·가격차·참조 수수료·현금·비율 {v['rational_value_checks']}개를 Decimal 남은 물량 소화와 독립 Fraction 누적 구간 적분으로 대조했다. 현물 한도와 전액 현금 참고점에서 바로 다음 수량이 탈락함을 확인했다. 기존 보호 파일 {v['protected_hashes_unchanged']}개와 이번 코드/명세 {v['source_hashes_unchanged']}개의 해시를 확인했다. 이는 조건부 산술의 확인이며 실제 체결·수익·손실 경로의 검증은 아니다.

[명세](Q005_CARRY_CAPITAL_CEILING.md) · [전 수량표](../../../reports/validation/q005_carry_capital_ceiling_20260919/quantity_rows.json) · [집계](../../../reports/validation/q005_carry_capital_ceiling_20260919/summary.json) · [검산](../../../reports/validation/q005_carry_capital_ceiling_20260919/verification.json) · [웹 자료 확인](../../../reports/validation/q005_carry_capital_ceiling_20260919/source_review.json).
'''
    with REPORT.open('x') as f:f.write(text)
    source=dict(label='Q002 저장 표시 호가 / Q005 수량별 자본·비용 성분',
        files=[dict(label=x) for x in ['Q005_RESULTS_2026_09_19.md','quantity_rows.json','summary.json','verification.json']],
        executedAt=s['completed_at_utc'],filters=['가상 1,000 USDT; 사용자 USDC 환전 미확인','두 만기 각각 0.001~0.012 BTC 및 첫 불가 수량 포함'],
        metricDefinitions=[dict(label='초기 가격차 성분',definition='수량별 선물 bid 명목−현물 ask 지출. 모든 비용과 만기 현물/정산 괴리 전 USDT 성분으로 실제 순익이 아니다.'),
            dict(label='진입 수수료 후 잔여',definition='초기 가격차 성분에서 공개 일반 현물 요율 10bp의 진입 참조액만 차감. 다른 비용·계정 요율 미확인.')],
        caveats=['2026-09-18 23:17:38 UTC의 과거 표시 호가이며 현재 체결 가격이 아니다.',
            '비용 전 성분 상한이지 실현 순익 상한·기대수익이 아니다.',
            '두 수량 참고점은 권장 배분이나 손실 5% 보장이 아니다.'],
        evidenceFlow=[dict(kind='validation',title='전 수량 독립 산술 대조',detail=f"{v['quantity_rows']}개 수량 행, {v['rational_value_checks']}개 값 Fraction/Decimal 대조. {v['tests']}개 검사. 실제 체결·계좌 수익 미검증.")])
    save(OUT/'delivery_sources.json',dict(schemaVersion=1,items=[dict(id='q005-capital-ceiling',title='캐리 가격차의 금액과 비용 여유 — 순익 아님',queries=[dict(
        id='capital-reference-points',source=source,reportingPeriod='2026-09-18 23:17:38 UTC 호가; 만기 9월 25일/12월 25일',
        columns=[dict(field=k,label=l) for k,l in [('contract','계약'),('reference','비교'),('quantity_btc','BTC'),('gross_basis_usdt','비용 전 성분 USDT'),('after_entry_fee_only_usdt','진입 현물비만 차감 USDT'),('remaining_cash_before_fees_usdt','현물 매입 뒤 현금 USDT')]],rows=rows)])]))
    save(OUT/'progress_addendum.json',dict(status='Q005_COMPLETE_CONDITIONAL_COMPONENT_DIAGNOSTIC',
        q002='EXECUTION_EVIDENCE_INCOMPLETE_NOT_PROMOTED',q004='FIRST_FORECAST_UNCHANGED_OUTCOME_PENDING',
        profit_verified=False,loss_preference_verified=False,actual_fee_verified=False,
        currency_conversion_verified=False,new_orders=0,new_schedules=0,
        next='Q004_FROZEN_OUTCOME_ASSESSMENT_WHEN_MATURE; NO_FURTHER_CARRY_SIZE_SEARCH_WITH_SAME_QUOTE'))
    print(REPORT)


if __name__=='__main__':main()
