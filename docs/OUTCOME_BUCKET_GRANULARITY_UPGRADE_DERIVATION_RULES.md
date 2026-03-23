# Outcome Bucket Granularity Upgrade Derivation Rules

최종 갱신: 2026-03-23
상태: Item 2 baseline fixed

## 1. 목적
- `volatility_condition / cost_condition / liquidity_condition` bucket을 기존 decomposition에 어떻게 붙일지 고정한다.
- 이번 문서는 새 axis를 execution authority가 아니라 compare-only segmentation layer로 정의한다.
- approval, sizing, rollout policy DB row는 직접 바꾸지 않는다.

## 2. 공통 원칙
1. `family`는 계속 headline 축이다.
2. 새 axis는 `condition split`을 설명하는 supporting layer다.
3. runtime과 historical key derivation은 가능한 한 같은 언어를 쓴다.
4. 계산 불가하면 `unknown`으로 남긴다.
5. `closed < 4` bucket은 interpretation에서 thin sample로 취급한다.

## 3. runtime / historical key derivation

### 3A. volatility_condition
primary source:
- `atr5 / atr15` ratio

runtime derivation:
1. `atr15 > 0`이고 `atr5`가 있으면 `atr_ratio = atr5 / atr15`
2. `atr_ratio <= 0.70` -> `low_vol`
3. `atr_ratio >= 1.30` -> `high_vol`
4. 그 사이 -> `normal_vol`

runtime fallback:
1. `portfolio_volatility > 0`이면 proxy 사용
2. `portfolio_volatility <= 0.015` -> `low_vol`
3. `portfolio_volatility >= 0.035` -> `high_vol`
4. 그 사이 -> `normal_vol`

historical derivation:
1. plan validity나 persisted indicator payload에 `atr5`, `atr15`가 있으면 runtime과 같은 ratio 규칙 사용
2. 없으면 `unknown`

주의:
- 이번 라운드는 volatility bucket을 `atr-based condition proxy`로만 본다.
- 새 raw volatility store는 만들지 않는다.

### 3B. cost_condition
primary source:
- runtime은 `expected_fee_bps + max_slippage_bps`
- historical은 `baseline_cost_r`

runtime derivation:
1. `combined_cost_bps = expected_fee_bps + max_slippage_bps`
2. `combined_cost_bps <= 8.0` -> `low_cost`
3. `combined_cost_bps >= 18.0` -> `high_cost`
4. 그 사이 -> `normal_cost`
5. 계산 불가하면 `unknown`

historical derivation:
1. `baseline_adjusted[plan_id].baseline_cost_r`가 있으면 사용
2. `baseline_cost_r <= 0.05` -> `low_cost`
3. `baseline_cost_r >= 0.15` -> `high_cost`
4. 그 사이 -> `normal_cost`
5. `baseline_cost_r`가 없으면 `unknown`

historical confidence note:
- `cost_source == execution_fills`면 higher-confidence cost bucket
- `cost_source == plan_cost_est`면 estimated bucket으로 보고 해석 문구를 보수적으로 쓴다

주의:
- cost bucket은 fee/slippage burden을 나누는 axis이지, strategy quality verdict가 아니다.

### 3C. liquidity_condition
primary source:
- existing `liquidity proxy`, not raw order-book depth

runtime derivation:
1. `strategy_scorecard_raw_components.liquidity`가 있으면 primary proxy로 사용
2. `liquidity_score <= 35` -> `shallow_liquidity`
3. `liquidity_score >= 70` -> `deep_liquidity`
4. 그 사이 -> `normal_liquidity`

runtime fallback:
1. `max_slippage_bps`가 있으면 secondary liquidity proxy로 사용
2. `max_slippage_bps <= 6.0` -> `deep_liquidity`
3. `max_slippage_bps >= 15.0` -> `shallow_liquidity`
4. 그 사이 -> `normal_liquidity`

historical derivation:
1. persisted plan validity에 `strategy_scorecard_raw_components.liquidity`가 있으면 same threshold 사용
2. 없으면 `unknown`

주의:
- liquidity bucket은 raw depth metric이 아니라 `liquidity proxy bucket`이다.
- 그래서 wording도 `depth certainty`가 아니라 `liquidity-condition proxy` 언어를 우선한다.

### 3D. unknown handling
아래면 항상 `unknown`
1. required field missing
2. numeric field is `<= 0` and unusable for thresholding
3. payload exists but parsing fails

원칙:
- `unknown`은 negative bucket이 아니다.
- summary에서 `coverage_gap` 또는 `limited granularity`로만 해석한다.

## 4. decomposition row semantics
새 axis row shape는 기존 decomposition row와 동일하게 유지한다.

포함 필드:
1. `key`
2. `runtime_candidates`
3. `accepted_candidates`
4. `blocked_candidates`
5. `submitted`
6. `filled`
7. `closed`
8. `profitable`
9. `baseline_cost_profitable`
10. `accept_rate`
11. `fill_rate_from_submitted`
12. `close_rate_from_filled`
13. `profitable_rate_from_closed`
14. `baseline_cost_profitable_rate_from_closed`

즉 새 axis는 `row schema`를 늘리지 않고 `axis 종류`만 늘린다.

## 5. interpretation maturity rules
bucket 해석 성숙도는 `closed` 기준으로 고정한다.

1. `thin_sample`
- `closed < 4`

2. `usable`
- `4 <= closed < 8`

3. `mature`
- `closed >= 8`

원칙:
- thin sample bucket은 headline condition으로 승격하지 않는다.
- usable/mature bucket만 condition divergence 계산에 쓴다.

## 6. summary derivation
`outcome_bucket_granularity` summary는 아래 규칙으로 만든다.

### 6A. family focus
1. 기존 family decomposition에서 `closed`가 가장 큰 family를 headline으로 사용
2. 동률이면 `baseline_cost_profitable_rate_from_closed`가 더 낮은 family를 우선

### 6B. axis divergence score
각 condition axis에 대해 mature/usable row만 대상으로 아래 score를 계산한다.

1. mature 또는 usable row가 2개 미만이면 axis는 `insufficient`
2. 아니면
   - `best_rate = max(baseline_cost_profitable_rate_from_closed)`
   - `worst_rate = min(baseline_cost_profitable_rate_from_closed)`
   - `divergence_score = best_rate - worst_rate`

### 6C. top condition axis
1. `divergence_score`가 가장 큰 axis를 `top_condition_axis`로 사용
2. `divergence_score < 0.15`면 strong divergence가 없다고 보고 `top_condition_axis = none`

### 6D. top condition bucket
1. `top_condition_axis`가 있으면 그 axis에서 `baseline_cost_profitable_rate_from_closed`가 가장 낮은 bucket을 `top_condition_bucket`으로 사용
2. 동률이면 `closed`가 더 많은 bucket 우선

## 7. confidence rules
summary confidence는 아래처럼 고정한다.

1. `high`
- top axis has at least two `mature` buckets
- divergence score `>= 0.20`

2. `medium`
- top axis available
- divergence score `>= 0.15`

3. `low`
- top axis unavailable
- or only `usable` evidence exists

## 8. reason code generation
reason code는 아래 prefix만 사용한다.

### 8A. focus reasons
- `family_focus:<family>`

### 8B. top-axis reasons
- `top_axis:volatility_condition`
- `top_axis:cost_condition`
- `top_axis:liquidity_condition`

### 8C. bucket reasons
- `top_bucket:low_vol`
- `top_bucket:normal_vol`
- `top_bucket:high_vol`
- `top_bucket:low_cost`
- `top_bucket:normal_cost`
- `top_bucket:high_cost`
- `top_bucket:shallow_liquidity`
- `top_bucket:normal_liquidity`
- `top_bucket:deep_liquidity`

### 8D. coverage reasons
- `coverage:thin_sample`
- `coverage:limited_condition_split`
- `coverage:unknown_bucket_present`

## 9. wording rules
### 9A. strong split
- `family outcome diverges most in <axis>/<bucket>; post-cost conversion weakens materially there`

### 9B. moderate split
- `family outcome shows a noticeable condition split in <axis>; keep this as a supporting modifier`

### 9C. low evidence
- `condition bucket evidence is still limited; keep family/regime/session as the main read`

guardrail:
- new bucket summary도 `family headline`을 뒤집지 않는다.
- `high_cost`, `high_vol`, `shallow_liquidity`는 직접적인 failure verdict가 아니라 `condition drag` 언어로 쓴다.
