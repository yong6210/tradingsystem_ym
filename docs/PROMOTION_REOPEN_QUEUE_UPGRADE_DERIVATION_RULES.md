# Promotion Reopen Queue Upgrade Derivation Rules

최종 갱신: 2026-03-23
상태: Item 2 baseline fixed

## 1. 목적
- `promotion_clearance_tracker`와 supporting signal을 cross-family review re-open ordering으로 번역해서, 같은 입력이면 항상 같은 `promotion_reopen_queue`가 나오게 한다.
- 이번 규칙은 approval / sizing / rollout policy / candidate row를 직접 바꾸지 않는다.
- reopen queue는 compare-only governance re-open ordering만 담당한다.

## 2. 입력 우선순위
1. `promotion_clearance_tracker`
2. `promotion_governance`
3. `promotion_review_queue`
4. `promotion_remediation_queue`
5. `family_execution_degradation_advisory`
6. `strategy_lifecycle`
7. `positive_evidence_expansion`
8. `capital_allocator`

원칙:
1. `promotion_clearance_tracker`는 primary re-open readiness source다.
2. `promotion_governance`는 family posture anchor다.
3. `promotion_review_queue`는 prior cross-family review context다.
4. `promotion_remediation_queue`는 current clearance pressure context다.
5. `family_execution_degradation_advisory`는 execution reopen guardrail source다.
6. `positive_evidence_expansion`과 `capital_allocator`는 support-only positive modifier다.

## 3. family universe
queue 후보 family는 아래 합집합으로 만든다.
1. `promotion_clearance_tracker.family`
2. `promotion_review_queue.review_queue[*].family`
3. `promotion_remediation_queue.remediation_queue[*].family`
4. `promotion_governance.family`
5. `strategy_lifecycle.family`
6. `positive_evidence_expansion.family`
7. `capital_allocator.family_weights[*].family`

정리 규칙:
1. `unknown`과 빈 값은 제외한다.
2. 동일 family는 한 row로 합친다.
3. 상위 노출은 최대 `5` row까지다.

## 4. evidence normalization
각 family row는 아래 evidence를 먼저 정규화한다.

### 4A. clearance state
1. `promotion_clearance_tracker.family == family`면 `clearance_state`, `clearance_bias`, `confidence`
2. 없으면 기본값은 `observe_only`, `observe`, `low`

### 4B. promotion posture
1. `promotion_governance.family == family`면 `promotion_governance.state`, `promotion_bias`, `confidence`
2. 없으면 `promotion_review_queue.review_queue[*].promotion_state`
3. 그래도 없으면 `hold`

### 4C. review queue context
1. `promotion_review_queue.review_queue[*]`에서 같은 family row를 찾는다.
2. 있으면 `review_action`, `priority_rank`, `confidence`를 ordering context로 사용한다.
3. 없으면 `hold_monitor`, `999`, `low`를 기본값으로 둔다.

### 4D. remediation context
1. `promotion_remediation_queue.remediation_queue[*]`에서 같은 family row를 찾는다.
2. 있으면 `remediation_action`, `priority_rank`, `confidence`를 clearance pressure context로 사용한다.
3. 없으면 빈 값, `999`, `low`

### 4E. family execution state
1. `family_execution_degradation_advisory.families[*].status`
2. 없으면 `promotion_clearance_tracker.source_summary.family_execution_status`
3. 허용값은 `healthy / watch / manual_review / unavailable`

### 4F. lifecycle / positive / allocator modifier
1. lifecycle은 `strategy_lifecycle.family == family`면 `state`
2. 없으면 `promotion_clearance_tracker.source_summary.lifecycle_state`
3. positive expansion은 same family일 때만 `state`, `confidence`
4. allocator는 same family row의 `tier`, `capital_pressure`

### 4G. thin sample state
아래 중 하나면 `thin_sample = true`
1. `promotion_clearance_tracker.reason_codes`에 `sample:thin_sample`
2. `promotion_review_queue.review_queue[*].reason_codes`에 `sample:thin_sample`
3. `promotion_remediation_queue.remediation_queue[*].reason_codes`에 `sample:thin_sample`

## 5. reopen_action 규칙
priority precedence:
1. `reopen_review`
2. `continue_clearance`
3. `observe_reopen`

### Rule 1. observe_reopen
다음 중 하나면 `observe_reopen`
1. `thin_sample == true`
2. `clearance_state == observe_only`
3. family execution status == `unavailable` and promotion posture도 `hold`

guardrail:
1. thin sample은 어떤 경우에도 active re-open queue로 올리지 않는다.
2. `observe_reopen`는 neutral backlog이며 reopen rejection이 아니다.

### Rule 2. reopen_review
위 Rule 1에 걸리지 않고, 아래를 모두 만족하면 `reopen_review`
1. `clearance_state == clearance_ready`
2. family execution status != `manual_review`
3. `promotion_governance.state in {hold, promotable}`
4. current remediation action이 비어 있거나 `observe_guardrail`

support:
1. `positive_evidence_expansion.state == expandable`면 confidence와 priority를 강화한다.
2. allocator tier == `boost`는 support-only positive modifier다.

### Rule 3. continue_clearance
위 Rule 1, 2에 걸리지 않으면 `continue_clearance`

대표 케이스:
1. `clearance_state == blocked`
2. `clearance_state == partial_clear`
3. family execution status == `manual_review`
4. current remediation action이 `execution_remediation / policy_remediation / condition_remediation`

## 6. priority_rank 규칙
정렬은 숫자 `priority_rank`로 고정한다. 낮을수록 먼저 본다.

### 6A. base rank
1. `reopen_review` -> `10`
2. `continue_clearance` -> `20`
3. `observe_reopen` -> `30`

### 6B. reopen-side 보정
`reopen_review` row에서:
1. `clearance_state == clearance_ready` -> `-2`
2. positive expansion state == `expandable` -> `-2`
3. positive expansion confidence == `high` -> `-1`
4. allocator tier == `boost` -> `-1`
5. review queue action == `promote_review` -> `-1`

### 6C. clearance-side 보정
`continue_clearance` row에서:
1. family execution status == `manual_review` -> `-3`
2. remediation action == `execution_remediation` -> `-2`
3. remediation action == `policy_remediation` -> `-1`
4. `clearance_state == blocked` -> `-1`
5. review queue action == `defer_review` -> `-1`

### 6D. observe-side 보정
`observe_reopen` row에서:
1. `clearance_state == observe_only` -> no change
2. review queue action == `hold_monitor` -> no change

### 6E. tie-break
tie-break 순서:
1. `promotion_review_queue.priority_rank` low first
2. `promotion_remediation_queue.priority_rank` low first
3. `confidence` high > medium > low
4. lifecycle severity
   - `retired`
   - `degraded`
   - `production`
   - `probation`
   - `research`
5. family name ascending

## 7. queue_state 규칙
1. top row가 `reopen_review`면 `reopen_ready_queue`
2. top row가 `continue_clearance`면 `clearance_first_queue`
3. top row가 `observe_reopen`면 `observe_only_queue`
4. queue가 비어 있으면 `empty_queue`

## 8. headline_family / top_reopen_action 규칙
1. `headline_family`는 정렬 후 첫 번째 row의 family
2. `top_reopen_action`은 정렬 후 첫 번째 row의 reopen_action
3. queue가 비어 있으면 둘 다 빈 문자열

## 9. confidence 규칙
각 row confidence는 다음처럼 정리한다.
1. `promotion_clearance_tracker.confidence`가 있으면 우선 사용
2. 없으면 `promotion_governance.confidence`
3. 둘 다 없으면 `low`

보정:
1. `reopen_review` and positive expansion confidence `high` -> minimum `high`
2. thin sample은 항상 `low`

## 10. source_summary 규칙
top-level `source_summary`에는 아래만 허용한다.
1. `reopen_ready_count`
2. `clearance_continue_count`
3. `observe_count`
4. `thin_sample_count`
5. `top_clearance_state`
6. `top_promotion_state`
7. `top_remediation_action`

## 11. reason_codes 규칙
허용 prefix:
1. `promotion_reopen_queue:*`
2. `promotion_clearance:*`
3. `promotion_governance:*`
4. `review_queue:*`
5. `remediation_queue:*`
6. `family_execution:*`
7. `positive_expansion:*`
8. `allocator:*`
9. `sample:*`

예시:
1. `promotion_reopen_queue:reopen_ready_queue`
2. `promotion_clearance:clearance_ready`
3. `promotion_governance:hold`
4. `review_queue:promote_review`
5. `remediation_queue:observe_guardrail`
6. `family_execution:healthy`
7. `positive_expansion:expandable`
8. `allocator:boost`
9. `sample:thin_sample`

## 12. wording 규칙
1. `reopen_review`
   - "review first for controlled promotion re-open"
2. `continue_clearance`
   - "continue guardrail clearing before promotion review re-opens"
3. `observe_reopen`
   - "keep in observe queue while re-open evidence accumulates"
4. queue headline도 `auto reopen` 같은 wording은 금지한다.
