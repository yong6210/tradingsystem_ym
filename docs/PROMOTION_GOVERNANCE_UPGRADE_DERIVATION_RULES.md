# Promotion Governance Upgrade Derivation Rules

최종 갱신: 2026-03-23
상태: Item 2 baseline fixed

## 1. 입력 우선순위
1. `strategy_lifecycle`
2. `rollout_recommendation`
3. `positive_evidence_expansion`
4. `family_execution_degradation_advisory`
5. `mode_advisory`
6. `outcome_bucket_granularity`
7. `capital_allocator`

이 중:
1. `strategy_lifecycle`는 posture anchor다.
2. `rollout_recommendation`은 policy hint다.
3. `positive_evidence_expansion`은 positive review confidence다.
4. `outcome_bucket_granularity`와 `capital_allocator`는 modifier/support-only input이다.

## 2. family 선택
headline family 선택 우선순위:
1. `strategy_lifecycle.family`
2. `rollout_recommendation.family`
3. `positive_evidence_expansion.family`
4. fallback: `score_to_outcome_funnel.decomposition.family` 중 closed가 가장 많은 family

## 3. maturity guardrail
`thin_sample`이면:
1. `state=promotable` 금지
2. `promotion_bias=consider_promote` 금지
3. 기본값은 `defer`

`usable`이면:
1. `probation` review까지만 허용

`mature`이면:
1. `production` target posture를 검토할 수 있다

## 4. state precedence
precedence:
1. `defer`
2. `promotable`
3. `hold`

세부 규칙:
1. 아래 중 하나라도 참이면 `defer`
   - `strategy_lifecycle.state in {research, degraded, retired}`
   - `rollout_recommendation.recommendation in {reduce, research_only}`
   - `positive_evidence_expansion.state == not_ready`
   - family execution status가 `manual_review`
   - thin sample
   - `outcome_bucket_granularity.top_condition_axis`가 있고 top bucket이 negative drag인데 confidence가 `medium/high`
2. 아래를 모두 만족하면 `promotable`
   - `strategy_lifecycle.state in {probation, production}`
   - `positive_evidence_expansion.state == expandable`
   - `positive_evidence_expansion.expansion_bias == consider_expand`
   - `rollout_recommendation.recommendation in {hold, expand}`
   - family execution status == `healthy`
   - maturity != `thin_sample`
   - top condition modifier가 없거나 neutral/positive
3. 위 둘이 아니면 `hold`

## 5. promotion_bias 규칙
1. `state=promotable -> consider_promote`
2. `state=hold -> hold`
3. `state=defer -> defer`

## 6. target_posture 규칙
1. `state=promotable`이고 `strategy_lifecycle.state == production`이면 `production`
2. `state=promotable`이고 `strategy_lifecycle.state == probation`이면 `production`
3. `state=hold`이고 `strategy_lifecycle.state in {probation, production}`이면 `keep_current`
4. `state=hold`이고 `strategy_lifecycle.state == research`이면 `probation`
5. `state=defer -> keep_current`

## 7. confidence 규칙
1. `high`
   - `state=promotable`
   - lifecycle confidence `high`
   - positive expansion confidence `medium/high`
   - family execution confidence `medium/high`
   - no negative condition drag
2. `medium`
   - `state=promotable`
   - 또는 `state=hold`이지만 lifecycle이 `probation/production`
3. 그 외 `low`

## 8. modifier 해석
`outcome_bucket_granularity`:
1. `top_condition_axis`가 없으면 neutral
2. `top_condition_axis`가 있고 `confidence in {medium, high}`면 negative modifier
3. 이 modifier는 standalone veto가 아니라 `promotable -> hold/defer` 보정에만 사용한다

`capital_allocator`:
1. `family_focus == selected family` and `capital_pressure == overallocated_negative`면 defer 쪽 support signal
2. `family_weights[0].tier == boost`면 promotable confidence support signal
3. allocator alone으로 state를 결정하지 않는다

## 9. reason_codes 규칙
prefix:
1. `promotion_governance:*`
2. `lifecycle:*`
3. `rollout_recommendation:*`
4. `positive_expansion:*`
5. `condition_modifier:*`
6. `allocator:*`
7. `sample:*`

## 10. wording 규칙
1. `promotable`: "controlled promotion review candidate"
2. `hold`: "keep current posture and continue evidence accumulation"
3. `defer`: "promotion review should be deferred while guardrails remain active"
4. `outcome_bucket_granularity`는 "condition drag" 또는 "condition split"로만 표현한다.
