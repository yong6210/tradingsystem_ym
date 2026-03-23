# Promotion Clearance Tracker Upgrade Contract

최종 갱신: 2026-03-23
상태: Item 1 baseline fixed

## 1. 목적
- `promotion_clearance_tracker`는 family별 remediation progress를 같은 tracking language로 정리하는 compare-only summary다.
- 이 계층은 rollout policy DB, approval, sizing, scanner ranking, candidate row authority를 바꾸지 않는다.
- 이 계층은 `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`를 대체하지 않고, remediation 이후 `얼마나 clearance가 진행됐는가`를 family 단위로 번역한다.

## 2. 허용 clearance state
허용값은 아래 넷으로만 고정한다.
1. `blocked`
2. `partial_clear`
3. `clearance_ready`
4. `observe_only`

추가로 `clearance_bias`는 아래 셋만 허용한다.
1. `continue_remediation`
2. `consider_reopen_review`
3. `observe`

## 3. required field
summary object는 아래 필드만 허용한다.
1. `available`
2. `advisory_only`
3. `family`
4. `clearance_state`
5. `clearance_bias`
6. `confidence`
7. `summary`
8. `reason_codes`
9. `remaining_guardrail_domains`
10. `cleared_guardrail_domains`
11. `source_summary`

## 4. 입력 source 범위
직접 입력 source는 아래 범위만 허용한다.
1. `promotion_governance`
2. `promotion_review_queue`
3. `promotion_remediation_queue`
4. `strategy_lifecycle`
5. `family_execution_degradation_advisory`
6. `rollout_recommendation`
7. `outcome_bucket_granularity`
8. `positive_evidence_expansion`
9. `capital_allocator`

원칙:
1. `promotion_governance`는 family review posture anchor다.
2. `promotion_review_queue`는 cross-family review ordering context다.
3. `promotion_remediation_queue`는 current remediation domain anchor다.
4. `family_execution_degradation_advisory`는 execution clearance source다.
5. `rollout_recommendation`과 `strategy_lifecycle`는 policy clearance source다.
6. `outcome_bucket_granularity`는 condition clearance source다.
7. `positive_evidence_expansion`과 `capital_allocator`는 support-only positive modifier다.

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
1. thin sample family는 `clearance_ready`를 허용하지 않고 `observe_only`까지만 허용한다.
2. family execution status가 `manual_review`면 `clearance_ready` 금지다.
3. rollout recommendation이 `reduce` 또는 `research_only`면 policy guardrail이 남아 있는 것으로 본다.
4. active condition drag가 있으면 condition domain을 cleared로 보지 않는다.
5. `clearance_ready`는 execution / policy / condition의 active guardrail이 모두 비활성일 때만 허용한다.
6. 이 계층은 tracking language이며, review 재개를 자동 실행하지 않는다.

## 8. language boundary
1. `promotion_governance`는 family별 review decision language다.
2. `promotion_review_queue`는 cross-family review ordering language다.
3. `promotion_remediation_queue`는 cross-family guardrail clearing ordering language다.
4. `promotion_clearance_tracker`는 family별 clearance progress tracking language다.
5. `operator_action_priority`는 runtime action ordering language다.
6. 이 계층들은 서로 대체 관계가 아니다.
