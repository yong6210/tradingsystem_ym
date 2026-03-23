# Promotion Decision Brief Upgrade Contract

최종 갱신: 2026-03-23
상태: Item 1 baseline fixed

## 1. 목적
- `promotion_decision_brief`는 top family 하나를 기준으로 promotion case를 한 객체로 압축하는 compare-only summary다.
- 이 계층은 rollout policy DB, approval, sizing, scanner ranking, candidate row authority를 바꾸지 않는다.
- 이 계층은 `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`, `promotion_clearance_tracker`, `promotion_reopen_queue`를 대체하지 않고, 그 결과를 single-family decision brief로 압축한다.

## 2. 허용 brief state
허용값은 아래 셋으로만 고정한다.
1. `reopen_candidate`
2. `clearance_required`
3. `observe_case`

추가로 decision bias는 아래 셋만 허용한다.
1. `consider_reopen_review`
2. `continue_clearance`
3. `observe_only`

`target_posture`는 아래 셋만 허용한다.
1. `probation`
2. `production`
3. `keep_current`

## 3. required field
summary object는 아래 필드만 허용한다.
1. `available`
2. `advisory_only`
3. `family`
4. `brief_state`
5. `decision_bias`
6. `target_posture`
7. `summary`
8. `reason_codes`
9. `source_summary`

## 4. 입력 source 범위
직접 입력 source는 아래 범위만 허용한다.
1. `promotion_governance`
2. `promotion_review_queue`
3. `promotion_remediation_queue`
4. `promotion_clearance_tracker`
5. `promotion_reopen_queue`
6. `strategy_lifecycle`
7. `positive_evidence_expansion`
8. `capital_allocator`
9. `family_execution_degradation_advisory`

원칙:
1. `promotion_reopen_queue`는 primary family-selection context다.
2. `promotion_governance`는 posture anchor다.
3. `promotion_review_queue`는 original review intent context다.
4. `promotion_remediation_queue`는 current guardrail-clearing context다.
5. `promotion_clearance_tracker`는 family progress anchor다.
6. `positive_evidence_expansion`과 `capital_allocator`는 support-only positive modifier다.
7. `family_execution_degradation_advisory`는 decision brief guardrail check source다.

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
1. thin sample family는 `reopen_candidate` brief로 올리지 않는다.
2. family execution status가 `manual_review`면 `consider_reopen_review` 금지다.
3. `promotion_clearance_tracker.clearance_state == blocked`면 `reopen_candidate` 금지다.
4. `clearance_required`는 negative verdict가 아니라 re-open 전 보완 필요를 뜻한다.
5. `observe_case`는 neutral backlog이지 promotion rejection이 아니다.
6. brief는 single-family headline만 보여주고 multi-row queue를 대체하지 않는다.
7. `operator_action_priority`가 urgent runtime control을 다루고, `promotion_decision_brief`는 governance case compression만 다룬다.

## 8. language boundary
1. `promotion_governance`는 family review decision language다.
2. `promotion_review_queue`는 cross-family review ordering language다.
3. `promotion_remediation_queue`는 cross-family guardrail clearing ordering language다.
4. `promotion_clearance_tracker`는 family clearance progress tracking language다.
5. `promotion_reopen_queue`는 cross-family review re-open ordering language다.
6. `promotion_decision_brief`는 single-family decision compression language다.
7. `operator_action_priority`는 runtime action ordering language다.
8. 이 계층들은 서로 대체 관계가 아니다.
