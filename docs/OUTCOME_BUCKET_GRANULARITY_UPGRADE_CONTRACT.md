# Outcome Bucket Granularity Upgrade Contract

최종 갱신: 2026-03-23
상태: Item 1 baseline fixed

## 1. 목적
- 기존 `family / regime / session` decomposition 위에 더 미세한 market-condition bucket을 추가한다.
- 새 bucket은 strategy family를 대체하지 않고, family outcome을 더 잘 설명하는 supporting condition axis로만 사용한다.
- 이번 계약은 authority를 늘리지 않고 `decomposition + compare-only summary` 범위만 정의한다.

## 2. 허용 axis 집합
이번 라운드에서 허용하는 새 axis는 아래 셋으로 고정한다.

1. `volatility_condition`
- low / normal / high volatility 상태를 나누는 condition bucket

2. `cost_condition`
- low / normal / high trading cost 상태를 나누는 condition bucket

3. `liquidity_condition`
- shallow / normal / deep liquidity 상태를 나누는 condition bucket

주의:
- `entry_model`, `symbol`, `day_of_week`, `exchange_state` 같은 axis는 이번 라운드에 넣지 않는다.
- 새 axis는 독립 signal이 아니라 decomposition axis다.

## 3. axis 역할
1. `family`
- 계속 1차 headline 축

2. `regime / session`
- 기존 modifier 축

3. `volatility_condition / cost_condition / liquidity_condition`
- supporting market-condition 축
- family verdict를 설명하거나 분해하는 용도로만 사용

즉 `family first` 원칙은 유지한다.

## 4. bucket state 집합
각 axis의 허용 bucket 값은 아래처럼 제한한다.

### 4A. volatility_condition
1. `low_vol`
2. `normal_vol`
3. `high_vol`
4. `unknown`

### 4B. cost_condition
1. `low_cost`
2. `normal_cost`
3. `high_cost`
4. `unknown`

### 4C. liquidity_condition
1. `shallow_liquidity`
2. `normal_liquidity`
3. `deep_liquidity`
4. `unknown`

주의:
- thin sample은 bucket 이름으로 만들지 않고, 해석 규칙에서 `sample guardrail`로 처리한다.

## 5. 입력 source 범위
새 axis는 아래 source에서만 파생 가능하다.

1. `score_to_outcome_funnel`
- decomposition 원본 확장 대상

2. `execution_quality`
- slippage / fee / fill quality 관련 cost-side evidence

3. `portfolio / runtime candidate payload`
- `atr5`, `atr15`, `portfolio_volatility`, `expected_fee_bps`, `max_slippage_bps` 같은 existing field

4. existing validation/runtime metadata
- 기존 schema에 이미 있는 condition-like field만 사용

주의:
- 이번 라운드에서는 새 raw market-data collector를 만들지 않는다.
- 계산 불가한 값은 `unknown`으로 남긴다.

## 6. 직접 반영 surface
이번 라운드에서 직접 반영하는 곳:

1. `score_to_outcome_funnel.decomposition`
- 새 axis row 추가

2. `validation_report`
- condition bucket summary

3. `operations/checklist`
- informational condition review item

4. `execution/operator-dashboard`
- signal funnel 또는 summary cluster의 condition summary

5. `README`
- condition bucket layer 설명

## 7. 비반영 surface
이번 라운드에서 넣지 않는 곳:

1. `ExecutionApproval`
2. `approval_snapshot`
3. `plan.validity`
4. `/scanner/top`
5. `/portfolio/budget` candidate rows
6. rollout policy DB row
7. strategy family router

## 8. summary object 이름
공통 summary 이름은 아래로 고정한다.

- `outcome_bucket_granularity`

이 summary는 새 authority object가 아니라 decomposition interpretation layer다.

## 9. 공통 shape

```json
{
  "available": true,
  "advisory_only": true,
  "family_focus": "sweep_reversal",
  "top_condition_axis": "cost_condition",
  "top_condition_bucket": "high_cost",
  "summary": "family outcome diverges most in high-cost conditions; post-cost conversion weakens materially there",
  "reason_codes": [
    "family_focus:sweep_reversal",
    "top_axis:cost_condition",
    "top_bucket:high_cost"
  ],
  "condition_axes": {
    "volatility_condition": [],
    "cost_condition": [],
    "liquidity_condition": []
  }
}
```

## 10. hard guardrails
새 axis는 아래를 직접 바꾸지 못한다.

1. approval state
2. `recommended_risk_r`
3. `allocated_risk_r`
4. rollout policy DB row
5. scanner ranking
6. portfolio ordering

즉 새 bucket은 explanation / segmentation layer다.

## 11. thin-sample 보호 규칙
1. 새 axis row의 `closed < 4`는 interpretation에서 thin sample로 취급한다.
2. thin sample bucket은 negative/positive 확정 language보다 `informational` 언어를 우선한다.
3. 새 bucket은 family headline을 뒤집지 못한다.

## 12. wording 규칙
1. 새 bucket은 `cause certainty` 언어보다 `condition split` 언어를 우선한다.
2. `high_cost` 같은 bucket은 strategy failure로 단정하지 않는다.
3. `shallow_liquidity`는 execution drag explanation에 가깝게 쓴다.
4. `high_vol`은 opportunity 또는 risk를 동시에 가질 수 있으므로 deterministic verdict처럼 쓰지 않는다.
