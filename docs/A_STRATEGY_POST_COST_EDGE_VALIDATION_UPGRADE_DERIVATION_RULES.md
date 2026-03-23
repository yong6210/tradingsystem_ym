# A Strategy Post-Cost Edge Validation Upgrade Derivation Rules

최종 갱신: 2026-03-24
상태: Item 2 baseline fixed

## 1. 목적
- 이 문서는 `A 전략 post-cost edge validation`이 같은 입력에서 같은 edge state를 내도록 derivation 규칙을 고정한다.
- 첫 라운드 목적은 새로운 alpha 계산을 만드는 것이 아니라, 기존 `score_to_outcome_funnel / outcome_control_trace / outcome_bucket_granularity / family_execution_degradation_advisory`를 `A anchor evidence` 언어로 정리하는 것이다.

## 2. family selection 규칙
1. 평가 대상 family는 무조건 raw `sweep_reversal`이다.
2. `multi_strategy_ab_summary`, `strategy_cluster_balance`는 `strategy_cluster=a_reversal` context를 주는 support-only source다.
3. family row 선택은 `score_to_outcome_funnel.decomposition.family` 중 `key == sweep_reversal` row를 직접 찾는다.
4. `top_family_bucket`이 다른 family라도 `A 전략` 판정에는 사용하지 않는다.

## 3. sample_state derivation
기준 row는 `sweep_reversal` family row다.

1. family row가 없거나 `closed == 0`이면 `thin_sample`
2. `closed < 4`이면 `thin_sample`
3. `4 <= closed < 8`이면 `usable_sample`
4. `closed >= 8`이면 `mature_sample`

설명:
1. `closed >= 4`는 기존 outcome/approval negative gating이 시작되는 최소선이다.
2. `closed >= 8`은 rollout / positive expansion / bucket granularity 계층이 mature로 읽기 시작하는 기준과 맞춘다.

## 4. 핵심 metric derivation
첫 라운드는 아래 값을 표준으로 고정한다.

1. `family_post_cost_rate`
- `score_to_outcome_funnel.decomposition.family[sweep_reversal].baseline_cost_profitable_rate_from_closed`

2. `family_closed`
- `score_to_outcome_funnel.decomposition.family[sweep_reversal].closed`

3. `family_post_cost_ev`
- 현재 decomposition row에는 family-level realized post-cost EV scalar가 직접 없다.
- 따라서 첫 라운드에서는 `family_post_cost_ev`를 `None`으로 두고, family-level post-cost headline은 `family_post_cost_rate`를 primary metric으로 사용한다.
- 후속 라운드에서 stable family-level EV aggregate가 생기면 그때만 채운다.

4. `historical_anchor_rate`
- `score_to_outcome_funnel.historical_execution_outcomes.baseline_cost_profitable_rate_from_closed`

## 5. weakest_axis / weakest_bucket derivation
우선순위는 아래대로 고정한다.

1. `outcome_bucket_granularity.top_condition_axis` / `top_condition_bucket`
2. negative regime row
3. negative session row
4. family row 자체
5. none

판정 규칙:
1. `outcome_bucket_granularity.top_condition_axis`가 있고 divergence가 0.15 이상이면 그 axis를 `weakest_axis`로 사용한다.
2. condition axis가 없으면 `score_to_outcome_funnel.decomposition.regime`에서 `closed >= 4 && baseline_cost_profitable_rate_from_closed <= 0.3`인 첫 row를 negative regime으로 본다.
3. regime negative가 없으면 session row에 같은 규칙을 적용한다.
4. family row가 `closed >= 4 && baseline_cost_profitable_rate_from_closed <= 0.3`이면 `weakest_axis=family`, `weakest_bucket=sweep_reversal`로 본다.
5. 위 케이스가 없으면 `weakest_axis=""`, `weakest_bucket=""`로 둔다.

## 6. execution / control modifier 규칙
1. `family_execution_degradation_advisory.families`에서 `family == sweep_reversal` row를 직접 찾는다.
2. execution status가 `manual_review`면 alpha negative modifier가 아니라 hard-negative guardrail로 취급한다.
3. execution status가 `watch`면 fragile modifier로 취급한다.
4. `outcome_control_trace.approval_penalty_status == manual_review` 또는 `sizing_penalty_tier == hard_clamp`면 hard-negative guardrail로 취급한다.
5. `outcome_control_trace.approval_penalty_status == watch` 또는 `sizing_penalty_tier == soft_clamp`면 fragile modifier로 취급한다.
6. `alpha_research_pipeline`는 support-only다.
7. top focus / softening review / recommended action이 `post_cost_ev_deterioration`, family forced-exit deterioration, family information-failure deterioration을 가리키면 fragile 또는 insufficient 쪽 근거를 보강한다.

## 7. edge_state precedence
우선순위는 아래대로 고정한다.

1. `insufficient_sample`
2. `insufficient_edge`
3. `fragile_edge`
4. `validated_edge`

세부 규칙:

### 7A. insufficient_sample
아래 중 하나면 무조건 `insufficient_sample`
1. `sample_state == thin_sample`
2. family row가 없어서 `family_post_cost_rate`를 안정적으로 읽을 수 없음

### 7B. insufficient_edge
`insufficient_sample`이 아니고 아래 중 하나면 `insufficient_edge`
1. `family_post_cost_rate <= 0.3`
2. `historical_anchor_rate <= 0.3`
3. family execution status가 `manual_review`
4. `outcome_control_trace.approval_penalty_status == manual_review`
5. `outcome_control_trace.sizing_penalty_tier == hard_clamp`

### 7C. fragile_edge
위 둘이 아니고 아래 중 하나면 `fragile_edge`
1. `0.3 < family_post_cost_rate < 0.5`
2. family execution status가 `watch`
3. `outcome_control_trace.approval_penalty_status == watch`
4. `outcome_control_trace.sizing_penalty_tier == soft_clamp`
5. `weakest_axis`가 있고 condition/regime/session drag가 확인됨
6. `outcome_bucket_granularity.top_condition_axis == cost_condition` and divergence >= 0.15
7. `alpha_research_pipeline` top focus가 post-cost deterioration 계열

### 7D. validated_edge
아래를 모두 만족할 때만 `validated_edge`
1. `sample_state in {usable_sample, mature_sample}`
2. `family_post_cost_rate >= 0.5`
3. family execution status == `healthy`
4. `approval_penalty_status == healthy`
5. `sizing_penalty_tier == none`
6. `weakest_axis`가 없거나 informational 수준에 머무름

## 8. validation_bias mapping
1. `validated_edge` -> `keep_anchor`
2. `fragile_edge` -> `monitor_fragility`
3. `insufficient_edge` -> `reduce_anchor_confidence`
4. `insufficient_sample` -> `gather_more_evidence`

## 9. wording 규칙
1. `validated_edge`
- “A anchor remains defendable on current post-cost evidence.”

2. `fragile_edge`
- “A anchor still has usable evidence, but fragility is visible in execution or cost-sensitive buckets.”

3. `insufficient_edge`
- “Current A anchor confidence is weak on post-cost evidence; review anchor assumptions before expanding trust.”

4. `insufficient_sample`
- “A anchor evidence is still sample-thin; gather more closed evidence before making stronger claims.”

## 10. support-only / non-goal
1. 이 계층은 kill-switch, close-only, rollout policy DB를 직접 바꾸지 않는다.
2. `A 전략` 약화가 보여도 immediate stop을 뜻하지 않는다.
3. `B continuation` evidence는 이번 라운드에서 섞지 않는다.
4. actual auto-throttle / auto-stop은 다음 kill-condition 라운드에서 분리한다.
