# Promotion Reopen Queue Upgrade Contract

최종 갱신: 2026-03-23
상태: Item 1 baseline fixed

## 1. 목적
- `promotion_reopen_queue`는 여러 family 중 어떤 promotion review를 다시 열어볼 수 있는지를 queue language로 정리하는 compare-only summary다.
- 이 계층은 rollout policy DB, approval, sizing, scanner ranking, candidate row authority를 바꾸지 않는다.
- 이 계층은 `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`, `promotion_clearance_tracker`를 대체하지 않고, family별 progress와 guardrail 상태를 cross-family re-open ordering으로 번역한다.

## 2. 허용 reopen action
허용값은 아래 셋으로만 고정한다.
1. `reopen_review`
2. `continue_clearance`
3. `observe_reopen`

추가로 top-level queue state는 아래 넷만 허용한다.
1. `reopen_ready_queue`
2. `clearance_first_queue`
3. `observe_only_queue`
4. `empty_queue`

## 3. required field
summary object는 아래 필드만 허용한다.
1. `available`
2. `advisory_only`
3. `queue_state`
4. `headline_family`
5. `top_reopen_action`
6. `summary`
7. `reason_codes`
8. `reopen_queue`
9. `source_summary`

`reopen_queue` row는 아래 필드만 허용한다.
1. `family`
2. `reopen_action`
3. `clearance_state`
4. `promotion_state`
5. `priority_rank`
6. `confidence`
7. `summary`
8. `reason_codes`

## 4. 입력 source 범위
직접 입력 source는 아래 범위만 허용한다.
1. `promotion_governance`
2. `promotion_review_queue`
3. `promotion_remediation_queue`
4. `promotion_clearance_tracker`
5. `strategy_lifecycle`
6. `positive_evidence_expansion`
7. `capital_allocator`
8. `family_execution_degradation_advisory`

원칙:
1. `promotion_clearance_tracker`는 primary re-open readiness source다.
2. `promotion_governance`는 family posture anchor다.
3. `promotion_review_queue`는 prior cross-family review context다.
4. `promotion_remediation_queue`는 current clearance pressure context다.
5. `positive_evidence_expansion`과 `capital_allocator`는 support-only positive modifier다.
6. `family_execution_degradation_advisory`는 reopen guardrail check source다.

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
1. thin sample family는 `reopen_review` queue에 올리지 않는다.
2. family execution status가 `manual_review`면 `reopen_review` 금지다.
3. `promotion_clearance_tracker.clearance_state == blocked`면 `reopen_review` 금지다.
4. `continue_clearance`는 negative verdict가 아니라 review re-open 전 보완 ordering이다.
5. `observe_reopen`는 neutral backlog이지 reopen rejection이 아니다.
6. queue는 최대 상위 `5` row만 노출한다.
7. `operator_action_priority`가 urgent runtime control을 다루고, `promotion_reopen_queue`는 governance re-open ordering만 다룬다.

## 8. language boundary
1. `promotion_governance`는 family review decision language다.
2. `promotion_review_queue`는 cross-family review ordering language다.
3. `promotion_remediation_queue`는 cross-family guardrail clearing ordering language다.
4. `promotion_clearance_tracker`는 family clearance progress tracking language다.
5. `promotion_reopen_queue`는 cross-family review re-open ordering language다.
6. `operator_action_priority`는 runtime action ordering language다.
7. 이 계층들은 서로 대체 관계가 아니다.
