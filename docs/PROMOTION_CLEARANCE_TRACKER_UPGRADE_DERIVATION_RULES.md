# Promotion Clearance Tracker Upgrade Derivation Rules

최종 갱신: 2026-03-23
상태: Item 2 baseline fixed

## 1. 목적
- `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`와 supporting signal을 family별 clearance progress로 번역해서, 같은 입력이면 항상 같은 `promotion_clearance_tracker`가 나오게 한다.
- 이번 규칙은 approval / sizing / rollout policy / candidate row를 직접 바꾸지 않는다.
- clearance tracker는 compare-only governance progress tracking만 담당한다.

## 2. 입력 우선순위
1. `promotion_governance`
2. `promotion_remediation_queue`
3. `promotion_review_queue`
4. `family_execution_degradation_advisory`
5. `rollout_recommendation`
6. `strategy_lifecycle`
7. `outcome_bucket_granularity`
8. `positive_evidence_expansion`
9. `capital_allocator`

원칙:
1. `promotion_governance`는 family posture anchor다.
2. `promotion_remediation_queue`는 current remediation domain anchor다.
3. `promotion_review_queue`는 cross-family review context다.
4. `family_execution_degradation_advisory`, `rollout_recommendation`, `strategy_lifecycle`, `outcome_bucket_granularity`는 domain clearance source다.
5. `positive_evidence_expansion`과 `capital_allocator`는 support-only positive modifier다.

## 3. family 선택
headline family 선택 우선순위:
1. `promotion_governance.family`
2. `promotion_remediation_queue.headline_family`
3. `promotion_review_queue.headline_family`
4. `strategy_lifecycle.family`
5. `positive_evidence_expansion.family`
6. `capital_allocator.family_focus`

guardrail:
1. 빈 값과 `unknown`은 제외한다.
2. family를 끝까지 못 고르면 summary는 `available=false`가 아니라 `available=true`, `family=""`, `clearance_state=observe_only`로 남기지 않고, 이 단계에서는 `available=false`로 처리한다.

## 4. evidence normalization
선택된 family에 대해 아래 evidence를 먼저 정규화한다.

### 4A. promotion posture
1. `promotion_governance.family == family`면 `promotion_governance.state`, `promotion_bias`, `confidence`
2. 없으면 `promotion_review_queue.review_queue[*].promotion_state`
3. 그래도 없으면 `hold`

### 4B. remediation anchor
1. `promotion_remediation_queue.headline_family == family`면 `top_remediation_action`
2. 아니면 `promotion_remediation_queue.remediation_queue[*]`에서 같은 family row의 `remediation_action`
3. 없으면 빈 값

### 4C. review anchor
1. `promotion_review_queue.review_queue[*]`에서 같은 family row를 찾는다.
2. 있으면 `review_action`, `priority_rank`, `confidence`를 context로 사용한다.
3. 없으면 `hold_monitor`, `999`, `low`를 기본값으로 둔다.

### 4D. execution domain state
1. `family_execution_degradation_advisory.families[*].status`
2. 없으면 `promotion_governance.source_summary.family_execution_status`
3. 허용값은 `healthy / watch / manual_review / unavailable`

정리:
1. `manual_review -> blocked`
2. `watch -> partial`
3. `healthy -> cleared`
4. `unavailable -> unknown`

### 4E. policy domain state
1. `rollout_recommendation.family == family`면 `recommendation`, `maturity`
2. 없으면 `promotion_governance.source_summary.rollout_recommendation`, `rollout_maturity`
3. lifecycle은 `strategy_lifecycle.family == family`면 `state`
4. 없으면 `promotion_governance.source_summary.lifecycle_state`

정리:
1. `recommendation in {reduce, research_only}` -> policy blocked
2. `lifecycle_state in {degraded, retired}` -> policy blocked
3. `recommendation == hold` and `lifecycle_state in {probation, production}` -> policy cleared
4. 그 외는 policy partial

### 4F. condition domain state
1. `outcome_bucket_granularity.family_focus.key == family`
2. 그리고 `top_condition_axis`가 있고 `confidence in {medium, high}`면 active condition drag
3. axis는 `cost_condition / liquidity_condition / volatility_condition`만 허용한다.

정리:
1. active drag -> condition blocked
2. family match인데 active drag 아님 -> condition partial
3. family mismatch 또는 no axis -> condition cleared

### 4G. thin sample state
아래 중 하나면 `thin_sample = true`
1. `promotion_governance.reason_codes`에 `sample:thin_sample`
2. `promotion_review_queue.review_queue[*].reason_codes`에 `sample:thin_sample`
3. `promotion_remediation_queue.remediation_queue[*].reason_codes`에 `sample:thin_sample`
4. `rollout_maturity == thin_sample`

## 5. remaining / cleared guardrail domain 규칙
도메인은 `execution / policy / condition` 셋만 허용한다.

1. `remaining_guardrail_domains`
  - execution domain state == blocked -> `execution`
  - policy domain state == blocked -> `policy`
  - condition domain state == blocked -> `condition`
2. `cleared_guardrail_domains`
  - execution domain state == cleared -> `execution`
  - policy domain state == cleared -> `policy`
  - condition domain state == cleared -> `condition`
3. partial 상태 도메인은 두 리스트 어디에도 넣지 않는다.

## 6. clearance_state precedence
precedence:
1. `observe_only`
2. `blocked`
3. `clearance_ready`
4. `partial_clear`

세부 규칙:
1. 아래 중 하나면 `observe_only`
  - `thin_sample == true`
  - family를 선택하지 못함
  - `promotion_governance.state == hold`이고 remediation anchor도 없고 positive support도 약함
2. `remaining_guardrail_domains`가 2개 이상이면 `blocked`
3. `remaining_guardrail_domains`가 1개이고 `promotion_governance.state == defer`면 `blocked`
4. `remaining_guardrail_domains`가 0개이고 아래를 모두 만족하면 `clearance_ready`
  - family execution state != `manual_review`
  - `thin_sample == false`
  - `promotion_governance.state in {hold, promotable}`
  - `positive_evidence_expansion.state in {hold, expandable}` or unavailable
5. 위에 걸리지 않으면 `partial_clear`

## 7. clearance_bias 규칙
1. `clearance_state=blocked -> continue_remediation`
2. `clearance_state=partial_clear -> continue_remediation`
3. `clearance_state=clearance_ready -> consider_reopen_review`
4. `clearance_state=observe_only -> observe`

## 8. confidence 규칙
1. `low`
  - `thin_sample == true`
  - family 선택이 fallback 4순위 이하
2. `high`
  - `clearance_state=clearance_ready`
  - `promotion_governance.confidence in {medium, high}`
  - family execution state == `healthy`
  - no active condition drag
3. `medium`
  - `clearance_state=partial_clear`
  - 또는 `clearance_state=blocked`인데 remaining domain이 1개뿐인 경우
4. 그 외 `low`

## 9. positive modifier 해석
`positive_evidence_expansion`:
1. same family and `state == expandable`이면 `clearance_ready` confidence support signal
2. same family and `state == not_ready`면 `partial_clear -> blocked`로 내리지 않고 support 부재로만 처리한다

`capital_allocator`:
1. same family and `tier == boost`면 positive support signal
2. `capital_pressure == underallocated_positive`면 `consider_reopen_review` wording support signal
3. allocator alone으로 `clearance_ready`를 만들지 않는다

## 10. source_summary 규칙
top-level `source_summary`에는 아래만 허용한다.
1. `promotion_state`
2. `review_action`
3. `remediation_action`
4. `family_execution_status`
5. `rollout_recommendation`
6. `lifecycle_state`
7. `top_condition_axis`
8. `allocator_tier`

## 11. reason_codes 규칙
허용 prefix:
1. `promotion_clearance:*`
2. `promotion_governance:*`
3. `review_queue:*`
4. `remediation_queue:*`
5. `family_execution:*`
6. `rollout_recommendation:*`
7. `lifecycle:*`
8. `condition_drag:*`
9. `allocator:*`
10. `sample:*`

예시:
1. `promotion_clearance:blocked`
2. `promotion_governance:defer`
3. `review_queue:defer_review`
4. `remediation_queue:execution_remediation`
5. `family_execution:manual_review`
6. `rollout_recommendation:reduce`
7. `lifecycle:degraded`
8. `condition_drag:cost_condition`
9. `allocator:boost`
10. `sample:thin_sample`

## 12. wording 규칙
1. `blocked`: "clearance remains blocked while active guardrail domains remain unresolved"
2. `partial_clear`: "some remediation has cleared but at least one domain still needs review"
3. `clearance_ready`: "guardrail domains appear cleared enough to reopen promotion review"
4. `observe_only`: "keep this family in observe tracking while evidence accumulates"
