# Promotion Remediation Queue Upgrade Contract

최종 갱신: 2026-03-23
상태: Item 1 baseline fixed

## 1. 목적
- `promotion_remediation_queue`는 여러 family 중 어떤 guardrail clearing review를 먼저 봐야 하는지를 queue language로 정리하는 compare-only summary다.
- 이 계층은 rollout policy DB, approval, sizing, scanner ranking, candidate row authority를 바꾸지 않는다.
- 이 계층은 `promotion_governance`나 `promotion_review_queue`를 대체하지 않고, family별 defer/promotable context를 cross-family remediation ordering으로 번역한다.

## 2. 허용 remediation action
허용값은 아래 넷으로만 고정한다.
1. `execution_remediation`
2. `policy_remediation`
3. `condition_remediation`
4. `observe_guardrail`

추가로 top-level queue state는 아래 다섯 개만 허용한다.
1. `execution_first_queue`
2. `policy_first_queue`
3. `condition_first_queue`
4. `observe_only_queue`
5. `empty_queue`

## 3. required field
summary object는 아래 필드만 허용한다.
1. `available`
2. `advisory_only`
3. `queue_state`
4. `headline_family`
5. `top_remediation_action`
6. `summary`
7. `reason_codes`
8. `remediation_queue`
9. `source_summary`

`remediation_queue` row는 아래 필드만 허용한다.
1. `family`
2. `remediation_action`
3. `promotion_state`
4. `remediation_domain`
5. `priority_rank`
6. `confidence`
7. `summary`
8. `reason_codes`

## 4. 입력 source 범위
직접 입력 source는 아래 범위만 허용한다.
1. `promotion_governance`
2. `promotion_review_queue`
3. `strategy_lifecycle`
4. `positive_evidence_expansion`
5. `outcome_bucket_granularity`
6. `family_execution_degradation_advisory`
7. `rollout_recommendation`
8. `capital_allocator`
9. `alpha_research_pipeline`

원칙:
1. `promotion_governance`는 primary remediation context source다.
2. `promotion_review_queue`는 cross-family ordering anchor다.
3. `family_execution_degradation_advisory`는 execution remediation source다.
4. `rollout_recommendation`과 `strategy_lifecycle`는 policy remediation source다.
5. `outcome_bucket_granularity`는 condition remediation source다.
6. `capital_allocator`와 `alpha_research_pipeline`은 support-only modifier다.

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
1. thin sample family는 `execution_remediation`, `policy_remediation`, `condition_remediation` 대신 `observe_guardrail`까지만 허용한다.
2. family execution status가 `manual_review`면 remediation action은 `execution_remediation` 우선으로 제한한다.
3. `promotion_governance.state == promotable`인 family도 blocking remediation cause가 없을 때만 active remediation queue에 올라갈 수 있다.
4. `observe_guardrail`는 negative verdict가 아니라 evidence accumulation backlog다.
5. queue는 최대 상위 `5` row만 노출한다.
6. `operator_action_priority`가 urgent runtime control을 다루고, `promotion_remediation_queue`는 governance remediation ordering만 다룬다.

## 8. language boundary
1. `promotion_governance`는 family별 review decision language다.
2. `promotion_review_queue`는 cross-family review ordering language다.
3. `promotion_remediation_queue`는 cross-family guardrail clearing ordering language다.
4. `operator_action_priority`는 runtime action ordering language다.
5. 이 네 계층은 서로 대체 관계가 아니다.
