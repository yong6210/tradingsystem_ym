# A Strategy Post-Cost Edge Validation Upgrade Contract

최종 갱신: 2026-03-24
상태: Item 1 baseline fixed

## 1. 목적
- `A 전략 post-cost edge validation`은 current anchor family가 after-fee / after-slippage 기준에서도 아직 유지 가능한 edge를 가지는지 읽는 compare-only evidence summary다.
- 이 계층은 `A 전략`을 promotion / rollout / sizing authority로 직접 승격시키지 않고, post-cost evidence를 같은 operator language로 읽게 만드는 것이 목적이다.
- 이 계층은 `outcome_control_trace`, `score_to_outcome_funnel`, `outcome_bucket_granularity`, `alpha_research_pipeline`를 대체하지 않고, 그 결과를 `A 전략 anchor 검증` 언어로 압축한다.

## 2. 평가 대상 family
첫 라운드 대상은 아래 하나로만 고정한다.
1. raw family: `sweep_reversal`

운영 언어:
1. `sweep_reversal`은 raw source-of-truth다.
2. `a_reversal`은 optional overlay label이지만, family accounting과 historical comparison은 계속 `sweep_reversal` 기준으로 한다.

## 3. 허용 edge state
허용값은 아래 넷으로만 고정한다.
1. `validated_edge`
2. `fragile_edge`
3. `insufficient_edge`
4. `insufficient_sample`

추가로 validation bias는 아래 넷만 허용한다.
1. `keep_anchor`
2. `monitor_fragility`
3. `reduce_anchor_confidence`
4. `gather_more_evidence`

`sample_state`는 아래 셋만 허용한다.
1. `mature_sample`
2. `usable_sample`
3. `thin_sample`

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
10. `weakest_axis`
11. `weakest_bucket`
12. `summary`
13. `reason_codes`
14. `source_summary`

## 5. 직접 입력 source 범위
직접 입력 source는 아래 범위만 허용한다.
1. `score_to_outcome_funnel`
2. `outcome_control_trace`
3. `outcome_bucket_granularity`
4. `family_execution_degradation_advisory`
5. `mode_advisory`
6. `alpha_research_pipeline`
7. `multi_strategy_ab_summary`
8. `strategy_cluster_balance`

원칙:
1. `score_to_outcome_funnel.family`의 `sweep_reversal` bucket이 primary evidence source다.
2. `outcome_control_trace`는 approval drift가 아니라 post-cost conversion weakness를 읽는 secondary context다.
3. `outcome_bucket_granularity`는 condition split modifier로만 쓴다.
4. `family_execution_degradation_advisory`는 implementation drag와 alpha deterioration을 구분하는 guardrail source다.
5. `alpha_research_pipeline`은 support-only follow-up source다.
6. `multi_strategy_ab_summary`와 `strategy_cluster_balance`는 A anchor posture context로만 쓴다.

## 6. 직접 반영 surface
직접 반영 가능한 surface는 아래만 허용한다.
1. `validation_report`
2. `operations/checklist`
3. `execution/operator-dashboard`
4. `README`

## 7. 비반영 surface
아래에는 직접 반영하지 않는다.
1. `ExecutionApproval`
2. `approval_snapshot`
3. `recommended_risk_r`
4. `/scanner/top`
5. `/portfolio/budget` candidate row
6. rollout policy DB row
7. `operator_action_priority` hard ordering override

## 8. guardrail
1. `thin_sample`이면 `validated_edge`를 금지하고 `insufficient_sample` 또는 `fragile_edge`까지만 허용한다.
2. gross outcome이 positive여도 family-level post-cost EV가 non-positive면 `validated_edge`를 금지한다.
3. family execution status가 `watch` 또는 `manual_review`면 `keep_anchor` 공격적 wording을 금지한다.
4. weakest axis가 `cost_condition`이고 divergence가 크면 `validated_edge`보다 `fragile_edge`를 우선한다.
5. `insufficient_edge`는 전략 폐기를 뜻하지 않고, current anchor confidence가 post-cost 기준으로 약하다는 뜻이다.
6. 이 계층은 `A 전략 유지/축소`에 대한 evidence language이지 auto-stop authority가 아니다.

## 9. language boundary
1. `outcome_control_trace`는 approval / sizing pressure language다.
2. `outcome_bucket_granularity`는 condition split language다.
3. `alpha_research_pipeline`는 research follow-up language다.
4. `multi_strategy_ab_summary`는 A/B coexistence language다.
5. `A strategy post-cost edge validation`은 A anchor evidence language다.
6. 이 계층들은 서로 대체 관계가 아니다.
