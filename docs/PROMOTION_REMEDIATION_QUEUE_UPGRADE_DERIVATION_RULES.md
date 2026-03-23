# Promotion Remediation Queue Upgrade Derivation Rules

최종 갱신: 2026-03-23
상태: Item 2 baseline fixed

## 1. 목적
- 여러 family의 `promotion_governance`와 `promotion_review_queue` 결과를 cross-family remediation ordering으로 번역해서, 같은 입력이면 항상 같은 `promotion_remediation_queue`가 나오게 한다.
- 이번 규칙은 approval / sizing / rollout policy / candidate row를 직접 바꾸지 않는다.
- remediation queue는 compare-only governance remediation ordering만 담당한다.

## 2. 입력 우선순위
1. `promotion_governance`
2. `promotion_review_queue`
3. `family_execution_degradation_advisory`
4. `rollout_recommendation`
5. `strategy_lifecycle`
6. `outcome_bucket_granularity`
7. `positive_evidence_expansion`
8. `capital_allocator`
9. `alpha_research_pipeline`

원칙:
1. `promotion_governance`는 primary remediation context source다.
2. `promotion_review_queue`는 cross-family ordering anchor다.
3. `family_execution_degradation_advisory`는 execution remediation source다.
4. `rollout_recommendation`과 `strategy_lifecycle`는 policy remediation source다.
5. `outcome_bucket_granularity`는 condition remediation source다.
6. `capital_allocator`와 `alpha_research_pipeline`은 support-only modifier다.

## 3. family universe
queue 후보 family는 아래 합집합으로 만든다.
1. `promotion_review_queue.review_queue[*].family`
2. `promotion_governance.family`
3. `strategy_lifecycle.family`
4. `positive_evidence_expansion.family`
5. `capital_allocator.family_weights[*].family`
6. `alpha_research_pipeline.recommended_actions[*].target_family`

정리 규칙:
1. 빈 값과 `unknown`은 제외한다.
2. 동일 family는 한 row로 합친다.
3. `alpha_research_pipeline` family는 `recommended_scope == family`이고 `target_family`가 있을 때만 추가한다.
4. 상위 노출은 최대 `5` row까지다.

## 4. evidence normalization
각 family row는 아래 evidence를 먼저 정규화한다.

### 4A. promotion state
1. `promotion_governance.family == family`면 `promotion_governance.state`
2. 없으면 `promotion_review_queue.review_queue[*].promotion_state`
3. 그래도 없으면 `hold`

### 4B. review queue anchor
1. `promotion_review_queue.review_queue[*]`에서 같은 family row를 찾는다.
2. 있으면 `review_action`, `priority_rank`, `confidence`를 ordering anchor로 사용한다.
3. 없으면 `hold_monitor`, `999`, `low`를 기본값으로 둔다.

### 4C. family execution state
1. `family_execution_degradation_advisory.families[*].status`
2. 없으면 `promotion_governance.source_summary.family_execution_status`
3. 허용값은 `healthy / watch / manual_review / unavailable`

### 4D. rollout / lifecycle state
1. `rollout_recommendation.family == family`면 `recommendation`, `maturity`
2. 없으면 `promotion_governance.source_summary.rollout_recommendation`, `rollout_maturity`
3. lifecycle은 `strategy_lifecycle.family == family`면 `state`
4. 없으면 `promotion_governance.source_summary.lifecycle_state`

### 4E. condition drag state
1. `outcome_bucket_granularity.family_focus.key == family`
2. 그리고 `top_condition_axis`가 있고 `confidence in {medium, high}`
3. 이때 `condition_drag_state = active`, 아니면 `neutral`
4. axis는 `cost_condition / liquidity_condition / volatility_condition`만 허용한다.

### 4F. allocator support state
1. `capital_allocator.family_weights[*].family == family`
2. `tier`와 `capital_pressure`를 읽는다.
3. allocator는 remediation domain을 단독 결정하지 않는다.

### 4G. alpha research guardrail state
family-targeted recommendation만 support signal로 사용한다.

허용 조건:
1. `recommended_scope == family`
2. `target_family == family`

허용 guardrail 분류:
1. execution guardrail
   - `do_not_promote_if_information_failure_persists`
   - `do_not_promote_if_forced_exit_remains_elevated`
   - `do_not_promote_if_fill_rate_remains_subscale`
2. condition guardrail
   - `do_not_promote_if_cost_drag_persists`
3. policy guardrail
   - `do_not_expand_rollout_until_ev_is_non_negative`

global/regime/session/entry_model scope는 family remediation domain을 직접 만들지 않고 support-only로만 남긴다.

### 4H. thin sample state
아래 중 하나면 `thin_sample = true`
1. `promotion_governance.reason_codes`에 `sample:thin_sample`
2. `promotion_review_queue.review_queue[*].reason_codes`에 `sample:thin_sample`
3. `rollout_maturity == thin_sample`

## 5. remediation_action 규칙
priority precedence:
1. `execution_remediation`
2. `policy_remediation`
3. `condition_remediation`
4. `observe_guardrail`

### Rule 1. observe_guardrail
다음 중 하나면 `observe_guardrail`
1. `thin_sample == true`
2. `promotion_state == promotable`이고 active remediation cause가 없음
3. `promotion_state == hold`이고 execution / policy / condition remediation cause가 없음

guardrail:
1. thin sample은 어떤 경우에도 active remediation queue로 올리지 않는다.
2. `observe_guardrail`는 negative verdict가 아니라 evidence accumulation backlog다.

### Rule 2. execution_remediation
다음 중 하나면 `execution_remediation`
1. family execution status == `manual_review`
2. family-targeted alpha research execution guardrail 존재
3. `promotion_state == defer`이고 주된 reason이 `family_execution:*` 계열

주의:
1. family execution `watch` 단독으로는 execution remediation을 만들지 않는다.
2. `manual_review`는 항상 policy/condition보다 우선한다.

### Rule 3. policy_remediation
위 Rule 2에 걸리지 않고, 아래 중 하나면 `policy_remediation`
1. `rollout_recommendation in {reduce, research_only}`
2. `lifecycle_state in {degraded, retired}`
3. `promotion_state == defer`이고 주된 reason이 rollout/lifecycle 계열

주의:
1. `capital_pressure == overallocated_negative`는 policy remediation support signal이지 standalone cause는 아니다.
2. `promotion_review_queue.review_action == defer_review`는 ordering support일 뿐 domain을 단독 결정하지 않는다.

### Rule 4. condition_remediation
위 Rule 2, 3에 걸리지 않고, 아래를 만족하면 `condition_remediation`
1. `condition_drag_state == active`
2. `promotion_state in {defer, hold}`

support:
1. family-targeted alpha research condition guardrail이 있으면 confidence와 priority를 강화한다.
2. `cost_condition`은 `liquidity_condition`, `volatility_condition`보다 우선 remediation axis다.

## 6. remediation_domain 규칙
1. `execution_remediation -> execution`
2. `policy_remediation -> policy`
3. `condition_remediation -> condition`
4. `observe_guardrail -> observe`

## 7. priority_rank 규칙
정렬은 숫자 `priority_rank`로 고정한다. 낮을수록 먼저 본다.

### 7A. base rank
1. `execution_remediation` -> `10`
2. `policy_remediation` -> `20`
3. `condition_remediation` -> `30`
4. `observe_guardrail` -> `40`

### 7B. execution-side 보정
`execution_remediation` row에서:
1. family execution status == `manual_review` -> `-3`
2. review queue action == `defer_review` -> `-1`
3. family-targeted alpha research execution guardrail 존재 -> `-1`

### 7C. policy-side 보정
`policy_remediation` row에서:
1. lifecycle state == `retired` -> `-3`
2. lifecycle state == `degraded` -> `-2`
3. rollout recommendation == `reduce` -> `-2`
4. rollout recommendation == `research_only` -> `-1`
5. capital pressure == `overallocated_negative` -> `-1`
6. review queue action == `defer_review` -> `-1`

### 7D. condition-side 보정
`condition_remediation` row에서:
1. top condition axis == `cost_condition` -> `-2`
2. top condition axis == `liquidity_condition` -> `-1`
3. condition confidence == `high` -> `-1`
4. family-targeted alpha research condition guardrail 존재 -> `-1`

### 7E. observe-side 보정
`observe_guardrail` row에서:
1. review queue action == `promote_review` -> `-2`
2. positive expansion state == `expandable` -> `-1`
3. review queue action == `hold_monitor` -> no change

### 7F. tie-break
tie-break 순서:
1. `promotion_review_queue.priority_rank` low first
2. `confidence` high > medium > low
3. lifecycle severity
   - `retired`
   - `degraded`
   - `production`
   - `probation`
   - `research`
4. family name ascending

## 8. queue_state 규칙
1. top row가 `execution_remediation`면 `execution_first_queue`
2. top row가 `policy_remediation`면 `policy_first_queue`
3. top row가 `condition_remediation`면 `condition_first_queue`
4. top row가 `observe_guardrail`면 `observe_only_queue`
5. remediation queue가 비어 있으면 `empty_queue`

## 9. headline_family / top_remediation_action 규칙
1. `headline_family`는 정렬 후 첫 번째 row의 family
2. `top_remediation_action`은 정렬 후 첫 번째 row의 remediation_action
3. queue가 비어 있으면 둘 다 빈 문자열

## 10. confidence 규칙
각 row confidence는 다음처럼 정리한다.
1. `promotion_review_queue.review_queue[*].confidence`가 있으면 우선 사용
2. 없으면 `promotion_governance.confidence`
3. 둘 다 없으면 `low`

보정:
1. family-targeted alpha research guardrail이 있으면 minimum `medium`
2. thin sample은 항상 `low`

## 11. source_summary 규칙
top-level `source_summary`에는 아래만 허용한다.
1. `execution_first_count`
2. `policy_first_count`
3. `condition_first_count`
4. `observe_count`
5. `thin_sample_count`
6. `top_promotion_state`
7. `top_review_action`
8. `top_remediation_domain`

## 12. reason_codes 규칙
허용 prefix:
1. `promotion_remediation_queue:*`
2. `promotion_governance:*`
3. `review_queue:*`
4. `family_execution:*`
5. `rollout_recommendation:*`
6. `lifecycle:*`
7. `condition_drag:*`
8. `allocator:*`
9. `alpha_research:*`
10. `sample:*`

예시:
1. `promotion_remediation_queue:execution_first_queue`
2. `promotion_governance:defer`
3. `review_queue:defer_review`
4. `family_execution:manual_review`
5. `rollout_recommendation:reduce`
6. `lifecycle:degraded`
7. `condition_drag:cost_condition`
8. `alpha_research:family_information_failure`
9. `sample:thin_sample`

## 13. wording 규칙
1. `execution_remediation`
   - "review execution drag and exit or fill guardrails before reopening promotion review"
2. `policy_remediation`
   - "review rollout and lifecycle posture before promotion review"
3. `condition_remediation`
   - "review condition drag buckets before promotion review"
4. `observe_guardrail`
   - "keep in observe queue while evidence accumulates"
5. queue headline도 `auto promote`, `auto unlock`, `auto reduce` 같은 wording은 금지한다.
