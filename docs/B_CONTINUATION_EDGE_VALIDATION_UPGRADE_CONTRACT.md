# B Continuation Edge Validation Upgrade Contract

최종 갱신: 2026-03-24
상태: Item 1 baseline fixed

## 1. 목적
- `B continuation edge validation`은 `trend_continuation` family가 after-fee / after-slippage 기준에서도 아직 독립 edge를 가지는지, 그리고 `A` 대비 diversification value가 있는지 읽는 compare-only evidence summary다.
- 이 계층은 `B 전략`을 approval / rollout / sizing authority로 직접 승격시키지 않고, post-cost edge와 diversification evidence를 같은 operator language로 읽게 만드는 것이 목적이다.
- 이 계층은 `b_continuation_activation`, `score_to_outcome_funnel`, `outcome_bucket_granularity`, `capital_allocator`를 대체하지 않고, 그 결과를 `B 전략 검증` 언어로 압축한다.

## 2. 평가 대상 family
첫 라운드 대상은 아래 하나로만 고정한다.
1. raw family: `trend_continuation`

운영 언어:
1. `trend_continuation`은 raw source-of-truth다.
2. `b_continuation`은 optional operating label이지만, family accounting과 historical comparison은 계속 `trend_continuation` 기준으로 한다.

## 3. 허용 edge state
허용값은 아래 넷으로만 고정한다.
1. `validated_edge`
2. `fragile_edge`
3. `insufficient_edge`
4. `insufficient_sample`

추가로 validation bias는 아래 넷만 허용한다.
1. `support_guarded_activation`
2. `monitor_diversification`
3. `reduce_b_confidence`
4. `gather_more_evidence`

`sample_state`는 아래 셋만 허용한다.
1. `mature_sample`
2. `usable_sample`
3. `thin_sample`

`diversification_state`는 아래 넷만 허용한다.
1. `diversifying`
2. `correlation_heavy`
3. `drawdown_additive`
4. `unclear_diversification`

`drawdown_contribution_state`는 아래 넷만 허용한다.
1. `drawdown_buffering`
2. `drawdown_neutral`
3. `drawdown_additive`
4. `drawdown_unknown`

## 4. required field
summary object는 아래 필드만 허용한다.
1. `available`
2. `advisory_only`
3. `raw_family`
4. `strategy_cluster`
5. `edge_state`
6. `validation_bias`
7. `sample_state`
8. `family_post_cost_ev`
9. `family_post_cost_rate`
10. `diversification_state`
11. `drawdown_contribution_state`
12. `a_b_correlation_proxy`
13. `weakest_axis`
14. `weakest_bucket`
15. `summary`
16. `reason_codes`
17. `source_summary`

## 5. 직접 입력 source 범위
직접 입력 source는 아래 범위만 허용한다.
1. `score_to_outcome_funnel`
2. `outcome_bucket_granularity`
3. `family_execution_degradation_advisory`
4. `alpha_research_pipeline`
5. `b_continuation_activation`
6. `multi_strategy_ab_summary`
7. `strategy_cluster_balance`
8. `capital_allocator`

원칙:
1. `score_to_outcome_funnel.family`의 `trend_continuation` bucket이 primary post-cost evidence source다.
2. `b_continuation_activation`은 rollout posture source이지 edge authority가 아니며, secondary context로만 쓴다.
3. `outcome_bucket_granularity`는 condition split modifier로만 쓴다.
4. `family_execution_degradation_advisory`는 implementation drag와 alpha deterioration을 구분하는 guardrail source다.
5. `capital_allocator`, `multi_strategy_ab_summary`, `strategy_cluster_balance`는 diversification posture context로만 쓴다.
6. 첫 라운드 `a_b_correlation_proxy`와 drawdown contribution은 exact covariance/portfolio attribution이 아니라 proxy language로만 제한한다.

## 6. 직접 반영 surface
직접 반영 가능한 surface는 아래만 허용한다.
1. `validation_report`
2. `operations/checklist`
3. `execution/operator-dashboard`
4. `README`

## 7. 비반영 surface
아래에는 직접 반영하지 않는다.
1. `/scanner/top` row additive field
2. `/portfolio/budget` candidate row
3. `ExecutionApproval`
4. `approval_snapshot`
5. `recommended_risk_r`
6. rollout policy DB row
7. `operator_action_priority` hard ordering override

## 8. guardrail
1. `thin_sample`이면 `validated_edge`를 금지하고 `insufficient_sample` 또는 `fragile_edge`까지만 허용한다.
2. gross outcome이 positive여도 family-level post-cost EV가 non-positive면 `validated_edge`를 금지한다.
3. family execution status가 `watch` 또는 `manual_review`면 `support_guarded_activation` 공격적 wording을 금지한다.
4. `a_b_correlation_proxy`가 높거나 `drawdown_contribution_state=drawdown_additive`면 `validated_edge`보다 `fragile_edge`를 우선한다.
5. `insufficient_edge`는 `B` 폐기를 뜻하지 않고, current guarded activation confidence가 post-cost/diversification 기준으로 약하다는 뜻이다.
6. 이 계층은 `B 전략 유지/축소`에 대한 evidence language이지 auto-kill authority가 아니다.

## 9. language boundary
1. `b_continuation_activation`은 first-wave activation posture language다.
2. `multi_strategy_ab_summary`는 A/B coexistence language다.
3. `strategy_cluster_balance`는 current family-mix posture language다.
4. `capital_allocator`는 scarce capital tilt language다.
5. `B continuation edge validation`은 B diversification evidence language다.
6. 이 계층들은 서로 대체 관계가 아니다.
