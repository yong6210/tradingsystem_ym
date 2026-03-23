# Promotion Review Queue Upgrade Contract

최종 갱신: 2026-03-23
상태: Item 1 baseline fixed

## 1. 목적
- `promotion_review_queue`는 여러 family 중 어떤 승격 검토를 먼저 봐야 하는지를 queue language로 정리하는 compare-only summary다.
- 이 계층은 rollout policy DB, approval, sizing, scanner ranking, candidate row authority를 바꾸지 않는다.
- 이 계층은 `promotion_governance`를 대체하지 않고, family별 review decision을 cross-family ordering으로 번역한다.

## 2. 허용 review action
허용값은 아래 셋으로만 고정한다.
1. `promote_review`
2. `defer_review`
3. `hold_monitor`

추가로 top-level queue state는 아래 넷만 허용한다.
1. `promotion_ready_queue`
2. `defer_first_queue`
3. `monitor_only_queue`
4. `empty_queue`

## 3. required field
summary object는 아래 필드만 허용한다.
1. `available`
2. `advisory_only`
3. `queue_state`
4. `headline_family`
5. `top_review_action`
6. `summary`
7. `reason_codes`
8. `review_queue`
9. `source_summary`

`review_queue` row는 아래 필드만 허용한다.
1. `family`
2. `review_action`
3. `promotion_state`
4. `target_posture`
5. `priority_rank`
6. `confidence`
7. `summary`
8. `reason_codes`

## 4. 입력 source 범위
직접 입력 source는 아래 범위만 허용한다.
1. `promotion_governance`
2. `strategy_lifecycle`
3. `positive_evidence_expansion`
4. `capital_allocator`
5. `family_execution_degradation_advisory`
6. `mode_advisory`
7. `score_to_outcome_funnel.decomposition.family`

원칙:
1. `promotion_governance`는 primary review decision source다.
2. `strategy_lifecycle`는 posture anchor다.
3. `positive_evidence_expansion`은 positive support signal이다.
4. `capital_allocator`는 support-only modifier다.
5. `score_to_outcome_funnel.decomposition.family`는 family coverage fallback이다.

## 5. 직접 반영 surface
직접 반영 가능한 surface는 아래만 허용한다.
1. `validation_report`
2. `operations/checklist`
3. `execution/operator-dashboard`
4. `README`

## 6. 비반영 surface
아래에는 직접 반영하지 않는다.
1. `ExecutionApproval`
2. `approval_snapshot`
3. `plan.validity`
4. `/scanner/top`
5. `/portfolio/budget` candidate row
6. rollout policy DB row
7. `operator_action_priority` hard ordering override

## 7. guardrail
1. thin sample family는 `promote_review` queue에 올리지 않는다.
2. family execution status가 `manual_review`면 `promote_review` 금지다.
3. `defer_review`는 hard block이 아니라 governance review order다.
4. `hold_monitor`는 neutral backlog이지 negative verdict가 아니다.
5. queue는 최대 상위 `5` row만 노출한다.
6. `operator_action_priority`가 urgent control을 다루고, `promotion_review_queue`는 governance ordering만 다룬다.

## 8. language boundary
1. `promotion_governance`는 family별 review decision language다.
2. `promotion_review_queue`는 cross-family review ordering language다.
3. `operator_action_priority`는 runtime action ordering language다.
4. 이 셋은 서로 대체 관계가 아니다.
