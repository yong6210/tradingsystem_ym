# B Continuation Edge Validation Upgrade Derivation Rules

최종 갱신: 2026-03-24
상태: Item 2 baseline fixed

## 1. 목적
- 이 문서는 `B continuation edge validation`이 같은 입력에서 같은 edge state를 내도록 derivation 규칙을 고정한다.
- 첫 라운드 목적은 새로운 covariance 엔진이나 portfolio attribution 모델을 만드는 것이 아니라, 기존 `score_to_outcome_funnel / outcome_bucket_granularity / b_continuation_activation / strategy_cluster_balance / capital_allocator`를 `B diversification evidence` 언어로 정리하는 것이다.

## 2. family selection 규칙
1. 평가 대상 family는 무조건 raw `trend_continuation`이다.
2. `multi_strategy_ab_summary`, `strategy_cluster_balance`, `b_continuation_activation`은 `strategy_cluster=b_continuation` context를 주는 support-only source다.
3. family row 선택은 `score_to_outcome_funnel.decomposition.family` 중 `key == trend_continuation` row를 직접 찾는다.
4. `A vs B` 비교용 reference family는 raw `sweep_reversal` row를 직접 찾는다.
5. `top_family_bucket`이나 `headline_cluster`가 다른 family라도 `B 전략` 판정에는 사용하지 않는다.

## 3. sample_state derivation
기준 row는 `trend_continuation` family row다.

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
- `score_to_outcome_funnel.decomposition.family[trend_continuation].baseline_cost_profitable_rate_from_closed`

2. `family_closed`
- `score_to_outcome_funnel.decomposition.family[trend_continuation].closed`

3. `a_reference_post_cost_rate`
- `score_to_outcome_funnel.decomposition.family[sweep_reversal].baseline_cost_profitable_rate_from_closed`
- 없으면 `None`

4. `family_post_cost_ev`
- 현재 decomposition row에는 family-level realized post-cost EV scalar가 직접 없다.
- 따라서 첫 라운드에서는 `family_post_cost_ev`를 `None`으로 두고, family-level post-cost headline은 `family_post_cost_rate`를 primary metric으로 사용한다.
- 후속 라운드에서 stable family-level EV aggregate가 생기면 그때만 채운다.

5. `post_cost_gap_vs_a`
- `family_post_cost_rate - a_reference_post_cost_rate`
- `a_reference_post_cost_rate`가 없으면 `None`

## 5. weakest_axis / weakest_bucket derivation
우선순위는 아래대로 고정한다.

1. `outcome_bucket_granularity.top_condition_axis` / `top_condition_bucket`
2. negative regime row
3. negative session row
4. family row 자체
5. none

판정 규칙:
1. `outcome_bucket_granularity.top_condition_axis`가 있고 `family_focus.key == trend_continuation`이거나, B family를 직접 겨냥한 top condition이라고 읽을 수 있으면 그 axis를 `weakest_axis`로 사용한다.
2. condition axis가 없으면 `score_to_outcome_funnel.decomposition.regime`에서 `closed >= 4 && baseline_cost_profitable_rate_from_closed <= 0.3`인 첫 row를 negative regime으로 본다.
3. regime negative가 없으면 session row에 같은 규칙을 적용한다.
4. family row가 `closed >= 4 && baseline_cost_profitable_rate_from_closed <= 0.3`이면 `weakest_axis=family`, `weakest_bucket=trend_continuation`으로 본다.
5. 위 케이스가 없으면 `weakest_axis=\"\"`, `weakest_bucket=\"\"`로 둔다.

## 6. diversification proxy derivation
첫 라운드 `a_b_correlation_proxy`는 exact correlation coefficient가 아니라 아래 카테고리로 고정한다.

1. `high_overlap_proxy`
2. `mixed_overlap_proxy`
3. `low_overlap_proxy`
4. `unknown_proxy`

판정 규칙:
1. `strategy_cluster_balance.balance_state == balanced_mix`면 `low_overlap_proxy`
2. `strategy_cluster_balance.balance_state == guarded_rebalance`면 `mixed_overlap_proxy`
3. `strategy_cluster_balance.balance_state == a_concentrated`이고 `capital_allocator.family_focus == trend_continuation`이며 `capital_pressure == overallocated_negative`면 `high_overlap_proxy`
4. `strategy_cluster_balance.balance_state == research_only_mix` 또는 B sample이 thin이면 `unknown_proxy`
5. 위에 걸리지 않으면 `mixed_overlap_proxy`

설명:
1. 이 proxy는 live portfolio와 accepted mix, allocator pressure를 읽는 운영 언어일 뿐 exact statistical correlation이 아니다.
2. 실제 rolling correlation coefficient는 후속 라운드에서 별도 aggregate가 생길 때만 교체한다.

## 7. diversification_state / drawdown_contribution_state derivation
### 7A. diversification_state
우선순위는 아래대로 고정한다.

1. `drawdown_additive`
2. `correlation_heavy`
3. `diversifying`
4. `unclear_diversification`

판정 규칙:
1. `drawdown_contribution_state == drawdown_additive`면 `diversification_state=drawdown_additive`
2. `a_b_correlation_proxy == high_overlap_proxy`면 `diversification_state=correlation_heavy`
3. `family_post_cost_rate >= 0.5`이고 `a_b_correlation_proxy in {low_overlap_proxy, mixed_overlap_proxy}`이며 `capital_allocator.capital_pressure != overallocated_negative`면 `diversification_state=diversifying`
4. 그 외는 `unclear_diversification`

### 7B. drawdown_contribution_state
판정 규칙:
1. `capital_allocator.family_focus == trend_continuation`이고 `capital_pressure == overallocated_negative`면 `drawdown_additive`
2. `family_post_cost_rate <= 0.3`이면 `drawdown_additive`
3. `family_post_cost_rate >= 0.5`이고 `capital_pressure == underallocated_positive`이며 `strategy_cluster_balance.balance_state in {guarded_rebalance, balanced_mix}`면 `drawdown_buffering`
4. `sample_state == thin_sample`이면 `drawdown_unknown`
5. 그 외는 `drawdown_neutral`

설명:
1. 첫 라운드에서는 allocator pressure와 current mix를 drawdown proxy로 사용한다.
2. exact contribution-to-drawdown attribution은 후속 라운드에서 realized family curve aggregate가 생길 때만 교체한다.

## 8. execution / posture modifier 규칙
1. `family_execution_degradation_advisory.families`에서 `family == trend_continuation` row를 직접 찾는다.
2. execution status가 `manual_review`면 hard-negative guardrail로 취급한다.
3. execution status가 `watch`면 fragile modifier로 취급한다.
4. `b_continuation_activation.activation_state == blocked`는 edge 자체를 자동으로 부정하지 않고, rollout/guardrail context로만 쓴다.
5. `b_continuation_activation.activation_state in {research_only, guarded_probation}`도 edge verdict를 자동으로 낮추지 않고 support-only context로만 쓴다.
6. `alpha_research_pipeline`는 support-only다.
7. top focus / recommended action이 `post_cost_ev_deterioration`, family forced-exit deterioration, family information-failure deterioration을 가리키면 fragile 또는 insufficient 쪽 근거를 보강한다.

## 9. edge_state precedence
우선순위는 아래대로 고정한다.

1. `insufficient_sample`
2. `insufficient_edge`
3. `fragile_edge`
4. `validated_edge`

세부 규칙:

### 9A. insufficient_sample
아래 중 하나면 무조건 `insufficient_sample`
1. `sample_state == thin_sample`
2. family row가 없어서 `family_post_cost_rate`를 안정적으로 읽을 수 없음

### 9B. insufficient_edge
`insufficient_sample`이 아니고 아래 중 하나면 `insufficient_edge`
1. `family_post_cost_rate <= 0.3`
2. family execution status가 `manual_review`
3. `diversification_state == drawdown_additive` and `a_b_correlation_proxy == high_overlap_proxy`
4. `alpha_research_pipeline` focus가 B family deterioration을 직접 가리키며 `family_post_cost_rate < 0.5`

### 9C. fragile_edge
위 둘이 아니고 아래 중 하나면 `fragile_edge`
1. `0.3 < family_post_cost_rate < 0.5`
2. family execution status가 `watch`
3. `a_b_correlation_proxy == high_overlap_proxy`
4. `drawdown_contribution_state == drawdown_additive`
5. `diversification_state == correlation_heavy`
6. `weakest_axis`가 있고 condition/regime/session drag가 확인됨
7. `alpha_research_pipeline` top focus가 post-cost deterioration 계열

### 9D. validated_edge
아래를 모두 만족할 때만 `validated_edge`
1. `sample_state in {usable_sample, mature_sample}`
2. `family_post_cost_rate >= 0.5`
3. family execution status == `healthy`
4. `a_b_correlation_proxy != high_overlap_proxy`
5. `drawdown_contribution_state in {drawdown_buffering, drawdown_neutral}`
6. `diversification_state == diversifying`
7. `weakest_axis`가 없거나 informational 수준에 머무름

## 10. validation_bias mapping
1. `validated_edge` -> `support_guarded_activation`
2. `fragile_edge` -> `monitor_diversification`
3. `insufficient_edge` -> `reduce_b_confidence`
4. `insufficient_sample` -> `gather_more_evidence`

## 11. wording 규칙
1. `validated_edge`
- “B continuation has usable post-cost evidence and still offers diversification value under the current mix.”

2. `fragile_edge`
- “B continuation still has usable evidence, but diversification value is fragile because correlation, drawdown, or cost-sensitive buckets remain unresolved.”

3. `insufficient_edge`
- “Current B confidence is weak on post-cost or diversification evidence; review B assumptions before treating it as a durable secondary family.”

4. `insufficient_sample`
- “B continuation evidence is still sample-thin; gather more closed evidence before making stronger diversification claims.”

## 12. support-only / non-goal
1. 이 계층은 activation posture, kill-switch, close-only, rollout policy DB를 직접 바꾸지 않는다.
2. `B 전략` 약화가 보여도 immediate stop을 뜻하지 않는다.
3. `A 전략` evidence와 allocator authority를 직접 대체하지 않는다.
4. actual auto-throttle / auto-stop은 다음 kill-condition 라운드에서 분리한다.
