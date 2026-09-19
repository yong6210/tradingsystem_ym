"""Q006 planning report, preserving the distinction from future inference."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/q006_forward_sample_feasibility_20260919'
REPORT=ROOT/'docs/research/experiments/Q006_RESULTS_2026_09_19.md'
def load(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):
    with p.open('x') as f:json.dump(x,f,indent=2,ensure_ascii=False);f.write('\n')


def main():
    s=load(OUT/'summary.json');v=load(OUT/'verification.json')
    for name,h in v['artifacts'].items():assert sha(OUT/name)==h
    labels={'original_H':'원래 H','exploratory_2H':'강한 2H (사후 선택)'}
    count_lines=[];precision_lines=[];source_rows=[]
    for name,x in s['results'].items():
        c=x['rolling_90_day_counts'];m=x['costs']['stress']
        count_lines.append(f"| {labels[name]} | {m['active_days']} | {100*m['historical_active_fraction']:.2f}% | {m['reference_count']:.2f} | {c['minimum']} / {c['median']:.0f} / {c['maximum']} |")
        source_rows.append(dict(rule=labels[name],historical_signals=m['active_days'],reference_90day_count=m['reference_count'],
            rolling_min=c['minimum'],rolling_median=c['median'],rolling_max=c['maximum'],
            stress_mean_bps=m['historical_mean_bps'],planning_se_bps=m['iid_planning_standard_error_bps']))
        for cost,a in x['costs'].items():
            precision_lines.append(f"| {labels[name]} | {'기본' if cost=='base' else '스트레스'} | {a['historical_mean_bps']:+.4f} | {a['historical_sample_sd_bps']:.4f} | {a['rounded_reference_count']} | {a['iid_planning_standard_error_bps']:.4f} |")
    text=f'''# Q006 결과 — 90일 관측과 수익성 확증은 다르다

2026-09-19. **강한 PRICE 신호는 과거의 연속 90일 구간에서 중앙값 6회뿐이었다. 현재 90일 관측을 ‘그 뒤에는 수익 모델이 확보되는 일정’으로 기대할 근거는 부족하다.** Q004는 처음부터 확증이 아닌 진단으로 명세했다. 이번 계산은 그 제한을 수량화했으며 규칙·종료일·첫 예측을 바꾸지 않았다.

## 먼저 확인한 거래 수

기존 E040/Q003의 같은 729일 PRICE 예측과 비용 사건을 읽었다. 날짜는 2024-09-01~2026-08-30 UTC 판단 경계다. 반복 사용한 과거 탐색 자료이며 새 독립 표본이 아니다. 2H는 이전 결과에서 사후 선택한 문턱이라는 이력을 유지한다.

| 규칙 | 과거 선택일/729일 | 과거 비율 | 비율×90일 참조 건수 | 과거 연속 90일 선택일 최소 / 중앙 / 최대 |
|---|---:|---:|---:|---:|
{chr(10).join(count_lines)}

90일 구간은 시작 날짜를 하루씩 옮긴 640개 전부다. 서로 겹치므로 640개의 독립 표본이 아니다. 최소·최대는 미래 범위나 확률 보장이 아니다. 비율×90은 과거 빈도가 유지되고 모든 날짜가 실제로 기록되는 경우의 산술 비교다. 실제 앞으로의 거래 수는 달라질 수 있고, 실행 누락은 정상 관망으로 세지 않는다.

## 이익 크기에 비해 손익 변동이 크다

아래는 **활성 사건당 bp**이며 계좌 USDC 수익률이 아니다. 표준편차는 선택된 과거 사건의 표본 표준편차(ddof=1)다. 무신호 0을 섞어 변동을 작게 만들지 않았다.

| 규칙 | 비용 | 과거 평균 bp | 과거 사건 표준편차 bp | 계획 비교 건수 N | 독립 가정의 평균 표준오차 참조 bp |
|---|---|---:|---:|---:|---:|
{chr(10).join(precision_lines)}

N은 위 참조 건수를 정수로 반올림한 값이다. 마지막 열은 과거 표준편차를 N의 제곱근으로 나눈 계획 비교치다. 평균의 표준오차가 표준편차와 표본 수에 좌우되는 관계는 [NIST 설명](https://www.itl.nist.gov/div898/handbook/eda/section3/eda352.htm)에 따른다. **실제 미래 표준오차·95% 신뢰구간·검정력을 계산한 것은 아니다.** 독립·동일분포·과거 변동 유지 가정은 검증되지 않았으며 시계열 의존, 장세 변화, 사후 선택과 표준편차 추정의 불확실성이 남는다.

강한 규칙의 스트레스 평균은 과거 +14.6484bp였지만, 9회라는 계획 비교에서 평균 표준오차 참조 크기는 약 115.1992bp다. 관측 몇 번의 손익에 따라 평균이 크게 달라질 수 있음을 보여준다. 이 비율만으로 유의성·성공 확률·필요 관측 연수를 선언하지 않는다. 원래 H는 더 자주 발생하지만 스트레스 평균 자체가 과거 −7.9929bp였다는 사실도 함께 보존한다.

## 판단과 다음 연구 기준

1. **Q004의 90일은 연결·인과적 예측 기록·예측/실현 격차를 확인하는 관측이다.** 양수 몇 번을 수익성 확증이나 손실 5% 충족으로 승격하지 않는다. 작은 양의 이익을 정밀하게 입증할 충분한 정보량이 확보된 일정으로 보지 않는다.
2. 원래 90일 종료는 유지한다. 결과가 좋아질 때까지 기간을 연장하거나 강한 문턱을 다시 조정하지 않는다. 표본 부족이면 미판정으로 끝낸다. 첫 예측은 변경 없이 유지했고 아직 목표 결과가 없다. 새 자동 일정도 없다.
3. 새 후보에는 구현 전 **비용 후 이익 규모·기회 빈도·기간 안에 얻을 근거**를 함께 요구한다. 거래를 늘리기 위해 문턱을 낮추거나 위험을 키우는 처방이 아니다. 정보량 부족을 보완할 구조적 근거가 없으면 대규모 개발·장기간 수집을 먼저 시작하지 않는다. 관련 [표본 계획 추가 기준](../SAMPLE_FEASIBILITY_GATE_2026_09_19.md)을 남겼다.

수익을 확보하려는 전체 목표는 미완료다. 이번 결과는 가격 예측 불가능성을 증명하지 않으며, 계좌 정책·실행 제약과 별개인 표본 계획상의 한계를 확인한 것이다. 월 수익 목표·손실 5% 정의·실제 운영비를 임의 확정하지 않는다. Q002/Q005 캐리 실행 자료 불충분, E048 보류도 유지한다.

Q006은 종료한다. 같은 과거 예측을 더 작게 분할하거나 이 계산으로 새 전략을 채택하지 않는다. 이후 Q004의 실제 결과가 발생하면 원래/강한 규칙과 단순 대조를 함께 기록한다.

## 검산

날짜 729개와 비용 사건 1,458개를 정렬하고 방향·비용 항등식을 확인했다. 두 문턱의 rolling 선택일 1,280개를 별도 직접 슬라이스 합으로 전수 대조했다. 평균·표준편차·계획 표준오차 12개는 Decimal 합·제곱합·제곱근으로 계산해 float 결과와 대조했고, Q003의 선택 사건 수와 평균에도 일치했다. 경계 검사 {v['tests']}개, 기존 보호 해시 {v['protected_hashes_unchanged']}개, 이번 소스 {v['source_hashes_unchanged']}개를 확인했다. 미래 수익·독립 가정·실제 계좌는 검증하지 않았다.

[명세](Q006_FORWARD_SAMPLE_FEASIBILITY.md) · [집계](../../../reports/validation/q006_forward_sample_feasibility_20260919/summary.json) · [모든 90일 구간](../../../reports/validation/q006_forward_sample_feasibility_20260919/rolling_counts.json) · [검산](../../../reports/validation/q006_forward_sample_feasibility_20260919/verification.json).
'''
    with REPORT.open('x') as f:f.write(text)
    source=dict(label='E040 PRICE 저장 예측·사건 원장 / Q003 대조 / Q006 계획 진단',
        files=[dict(label=n) for n in ['Q006_RESULTS_2026_09_19.md','summary.json','rolling_counts.json','verification.json']],
        executedAt=s['completed_at_utc'],filters=['기존 729일 PRICE 예측','원래 H/사후 선택 2H와 기본/스트레스 모두 확인'],
        metricDefinitions=[dict(label='90일 참조 건수',definition='과거 선택 비율×90. 과거 비율 유지·누락 없음 조건의 산술 참조이며 미래 거래 수 예측이 아니다.'),
            dict(label='평균 표준오차 참조 bp',definition='과거 활성 사건 표준편차 / sqrt(반올림 참조 건수). 독립 가정의 계획 규모 비교이며 미래 신뢰구간이 아니다.')],
        caveats=['반복 사용한 과거 자료와 사후 선택 문턱이다.','640개 rolling 구간은 서로 겹친다.',
            '기존 Q004 정책·90일 종료·첫 예측을 변경하지 않았다.','실현 미래 수익·계좌 손실·독립 가정은 미검증이다.'],
        evidenceFlow=[dict(kind='validation',title='선택 빈도와 변동 산술 대조',detail=f"729일/1,458 사건 정렬, 1,280개 rolling 합, 12개 Decimal 모멘트 대조. {v['tests']}개 경계 검사.")])
    save(OUT/'delivery_sources.json',dict(schemaVersion=1,items=[dict(id='q006-sample-feasibility',title='90일 관측의 정보량 — 수익성 확증 아님',queries=[dict(
        id='signal-count-planning',source=source,reportingPeriod='2024-09-01~2026-08-30 과거 판단 경계; 90일 계획 비교',
        columns=[dict(field=k,label=l) for k,l in [('rule','규칙'),('historical_signals','과거 선택일'),('reference_90day_count','90일 산술 참조'),
            ('rolling_min','과거 90일 최소'),('rolling_median','중앙'),('rolling_max','최대'),('stress_mean_bps','과거 스트레스 평균 bp'),('planning_se_bps','독립 가정 표준오차 참조 bp')]],rows=source_rows)])]))
    save(OUT/'progress_addendum.json',dict(status='Q006_COMPLETE_DESCRIPTIVE_SAMPLE_PLANNING',q004_policy_changed=False,
        q004_role='FIXED_90_DAY_DIAGNOSTIC_NOT_PROFIT_CONFIRMATION',profit_verified=False,
        next_hypothesis_requirement='ECONOMIC_EDGE_AFTER_COSTS_PLUS_OPPORTUNITY_FREQUENCY_AND_EVIDENCE_FEASIBILITY_BEFORE_IMPLEMENTATION',
        new_models=0,new_market_requests=0,new_schedules=0,new_orders=0))
    print(REPORT)


if __name__=='__main__':main()
