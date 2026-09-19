"""First Q004 publication receipt, with no invented future outcomes."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'reports/validation/q004_prospective_price_forecast_20260919'
DAY = OUT/'2026-09-19'
REPORT = ROOT/'docs/research/experiments/Q004_FIRST_FORECAST_2026_09_19.md'


def load(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p, obj):
    with p.open('x') as f: json.dump(obj, f, indent=2, ensure_ascii=False); f.write('\n')


def main():
    reg = load(OUT/'registration.json')
    f = load(DAY/'publish/forecast.json')
    r = load(DAY/'publish/publication_receipt.json')
    v = load(DAY/'verification.json')
    assert v['status'] == 'PASS' and r['status'] == 'PUBLISHED_BEFORE_TARGET'
    for key, p in [('registration', OUT/'registration.json'), ('forecast', DAY/'publish/forecast.json'),
                   ('publication_receipt', DAY/'publish/publication_receipt.json'),
                   ('auditor', ROOT/'scripts/audit_prospective_price_forecast.py')]:
        assert v['artifacts'][key] == sha(p)
    assert not (DAY/'score/outcome.json').exists(), 'This initial receipt must precede outcome scoring.'
    directions = {0:'관망', 1:'매수 방향', -1:'매도 방향'}
    original = directions[f['selectors']['original_H']]
    strong = directions[f['selectors']['exploratory_2H']]
    text = f'''# Q004 첫 예측 — 결과 전에 규칙과 예측을 기록

2026-09-19. **고정한 PRICE 모델의 첫 예측을 목표 가격이 형성되기 전에 로컬 파일에 기록했고, 별도 계산으로 검산했다. 실현 수익은 아직 없다.**

Q003에서 찾은 강한 예측 구간을 같은 과거 자료로 다시 최적화하지 않고, 원래 문턱과 강한 문턱을 미래 자료에서 함께 관찰하는 절차를 시작했다. 이는 과거 실패 모델의 채택이나 사용자 계좌의 운용 시작이 아니다.

## 시각과 첫 예측

- 규칙·코드 등록: {reg['registered_at_utc']}.
- UTC 판단 경계: {f['boundary']} — 한국 시각 2026-09-19 09:00.
- 영속 기록 완료: {r['committed_at_utc']}. 목표 시작보다 {v['publication_lead_seconds']:.3f}초 앞섰다.
- 목표 구간: 한국 시각 **9월 19일 09:01 → 9월 20일 09:00**의 BTCUSDC 선물 분봉 시가 변화.
- 결과 조회 가능: 종료 분봉 완료 이후인 **9월 20일 09:01 KST부터**. 해당 시각에 자동 실행을 예약한 것은 아니다.

| 같은 목표의 예측 | 가격 변화 bp | 해석 |
|---|---:|---|
| PRICE | {f['prediction_bps']:+.6f} | 모델의 점 예측, 보장 수익·비용 후 기대이익 아님 |
| 같은 학습 구간 과거 평균 | {f['controls']['MEAN180']:+.6f} | 단순 예측 대조 |
| 변화 없음 | 0.000000 | 단순 예측 대조 |

1bp=0.01%. 원래 H={f['threshold_bps']:.6f}bp, 강한 문턱 2H={2*f['threshold_bps']:.6f}bp. **원래 규칙: {original}, 강한 규칙: {strong}.** 방향이 활성화돼도 실제 주문을 넣은 기록이 아니다. 두 규칙은 별개의 계좌나 서로 독립적인 표본이 아니다.

## 수익은 어떻게 확인하는가

실제 목표 가격과 해당 구간의 정산 펀딩이 나온 뒤에만 원래/강한 선택의 사건 손익을 계산한다. 사용자 제시 수수료 0.025%/편도, 기존 슬리피지 2/5bp, 추가 펀딩 스트레스 0/1bp를 유지했다. 펀딩이 누락되면 비용 0으로 간주하지 않는다.

그 계산도 미래 분봉 시가와 고정 비용을 사용한 **단위 명목 사건 손익**이다. 실제 체결·부분 체결·주문 지연·증거금·운영비를 포함한 계좌 순익이 아니므로 1,000 USDC 자본에 곱하거나 사용자 5% 손실 선호를 충족했다고 말하지 않는다. 현재 실현 손익·MSE·MAE는 모두 미관측이며, 첫 한 번의 정답이나 양수 손익으로 모델을 채택하지 않는다.

## 확인한 범위

경계 시각, 미성숙 목표 제외, 훈련 구간 표준화, 원래 특징 계산과의 일치, 비용 방향·틱, 펀딩 경계·자료 누락을 다루는 **9개 검사**가 통과했다. 기존 8월 입력의 겹치는 값 118개가 일치했고, 공표 때 {f['overlap_value_checks']}개 값을 다시 대조했다.

별도 감사는 보존된 기존 소스/증거 {v['protected_hashes_unchanged']}개와 이번 고정 입력/코드 {v['source_hashes_unchanged']}개의 해시를 확인했다. 공개 요청 {v['raw_request_checks']}개와 서버 시각 {v['clock_checks']}회, 원문에서 재구성한 {v['minute_rows_reconstructed']:,}개 분봉의 {v['minute_values_compared']:,}개 값을 확인했다. 달력 날짜로 학습 180일을 다시 선택하고 Decimal 평균·표준편차 및 최소제곱 계산으로 예측을 검산했다. 저장 예측과의 차이는 {v['forecast_decimal_moments_lstsq_difference']:.3g}bp다.

8월 9일 이전은 동결된 E040 일별 입력을 재사용했으며 더 오래된 원시 분봉 전체를 다시 해석한 것은 아니다. 공표는 로컬 시각·해시·거래소 시각 대조 기록이고 외부 공증은 아니다. 해시 보존 개수는 서로 중복되는 파일을 포함할 수 있으므로 합산해 독립 파일 수라고 부르지 않는다.

## 상태와 다음 판단

고정 관찰 범위는 UTC 2026-09-19~12-17의 90개 판단 경계다. 마지막 목표 종료는 12-18 00:00 UTC다. **지금 실행한 것은 첫 날짜의 예측 1개이며, 90일 자동 관찰은 생성하지 않았다.** 이후 기동되지 않은 날은 무신호가 아닌 미공표로 집계하고 뒤늦은 예측을 만들지 않는다. 유효 표본이 부족하면 미판정으로 끝낸다.

다음 실질적인 새 증거는 첫 목표의 실현 가격·펀딩이다. PRICE와 두 단순 예측의 오차, 원래/강한 선택의 양 비용 손익을 함께 보고한다. 수익·손실 집중·회복·실제 계좌 비용 근거가 확보되기 전에는 결합이나 실운용 준비로 승격하지 않는다. Q001 비용 시나리오와 Q002 실행 자료 불충분, 기존 E040 판정과 E048 보류는 유지한다.

수익 확보는 미완료다. 사용자 월 수익 목표·5% 손실의 정의·실제 운영비도 미정으로 보존했다.

[고정 명세](Q004_PROSPECTIVE_FORECAST.md) · [정책](../../../configs/research/q004_prospective_price_forecast_v1.json) · [첫 예측](../../../reports/validation/q004_prospective_price_forecast_20260919/2026-09-19/publish/forecast.json) · [기록 영수증](../../../reports/validation/q004_prospective_price_forecast_20260919/2026-09-19/publish/publication_receipt.json) · [별도 검산](../../../reports/validation/q004_prospective_price_forecast_20260919/2026-09-19/verification.json).
'''
    with REPORT.open('x') as handle: handle.write(text)
    summary = dict(status='FIRST_PROSPECTIVE_FORECAST_PUBLISHED_AND_AUDITED_OUTCOME_PENDING',
        boundary=f['boundary'], published_at_utc=r['committed_at_utc'],prediction_bps=f['prediction_bps'],
        controls=f['controls'],threshold_bps=f['threshold_bps'],selectors=f['selectors'],
        valid_publications=1,realized_outcomes=0,actual_orders=0,actual_account_profit_verified=False,
        automatic_schedule_created=False,next_outcome_earliest_utc='2026-09-20T00:01:00+00:00',
        source_report=str(REPORT.relative_to(ROOT)))
    save(OUT/'first_publication_summary.json',summary)
    source = dict(label='Q004 고정 등록·첫 예측·기록 영수증·독립 검산',
        files=[dict(label=x) for x in ['Q004_FIRST_FORECAST_2026_09_19.md','registration.json','forecast.json','publication_receipt.json','verification.json']],
        executedAt=r['committed_at_utc'],
        filters=['BTCUSDC PRICE 예측 1개, 실현 결과 0개','원래 H와 사후 선택 2H를 함께 기록'],
        metricDefinitions=[dict(label='가격 변화 예측 bp',definition='UTC 경계+1분 시가에서 다음 날 경계 시가까지 가격 변화의 모델 점 예측. 1bp=0.01%, 비용 후 수익 아님.')],
        caveats=['실현 결과·수익성·5% 손실 선호는 아직 검증되지 않았다.',
                 '로컬 기록으로 외부 공증이 아니며 실제 체결을 관측하지 않았다.',
                 '첫 예측 1개를 실행했으며 90일 자동 일정은 생성하지 않았다.'],
        evidenceFlow=[dict(kind='validation',title='결과 이전 기록과 독립 산술 대조',
            detail=f"목표 시작 {v['publication_lead_seconds']:.3f}초 전 기록. 기존 {v['protected_hashes_unchanged']}개 및 이번 {v['source_hashes_unchanged']}개 해시 확인. 공개 원문 분봉 재구성과 날짜 기준 180일 학습·Decimal 모멘트·최소제곱 대조.")])
    save(OUT/'delivery_sources.json',dict(schemaVersion=1,items=[dict(id='q004-first-prospective-forecast',
        title='결과 전에 기록한 첫 예측 — 실현 결과 대기',queries=[dict(id='first-forecast',source=source,
            reportingPeriod='목표: 한국 시각 2026-09-19 09:01~2026-09-20 09:00',
            columns=[dict(field='model',label='예측'),dict(field='prediction_bps',label='가격 변화 bp')],
            rows=[dict(model='PRICE',prediction_bps=f['prediction_bps']),
                  dict(model='과거 180일 평균',prediction_bps=f['controls']['MEAN180']),dict(model='변화 없음',prediction_bps=0)])])]))
    print(REPORT)


if __name__ == '__main__': main()
