# Promotion Review Queue Upgrade Derivation Rules

최종 갱신: 2026-03-23
상태: Item 2 baseline fixed

## 1. 목적
- 여러 family의 `promotion_governance` 결과를 cross-family review ordering으로 번역해서, 같은 입력이면 항상 같은 `promotion_review_queue`가 나오게 한다.
- 이번 규칙은 approval / sizing / rollout policy / candidate row를 직접 바꾸지 않는다.
- review queue는 compare-only governance ordering만 담당한다.

## 2. 입력 우선순위
1. `promotion_governance`
2. `strategy_lifecycle`
3. `positive_evidence_expansion`
4. `family_execution_degradation_advisory`
5. `mode_advisory`
6. `capital_allocator`
7. `score_to_outcome_funnel.decomposition.family`

원칙:
1. `promotion_governance`는 primary review decision source다.
2. `strategy_lifecycle`는 posture anchor다.
3. `positive_evidence_expansion`은 promote-side support signal이다.
4. `capital_allocator`는 queue ordering support signal이다.
5. `score_to_outcome_funnel.decomposition.family`는 family coverage fallback이다.

## 3. family universe
queue 후보 family는 아래 합집합으로 만든다.
1. `promotion_governance.family`
2. `strategy_lifecycle.family`
3. `positive_evidence_expansion.family`
4. `capital_allocator.family_weights[*].family`
5. `score_to_outcome_funnel.decomposition.family[*].key`

정리 규칙:
1. `unknown`과 빈 값은 제외한다.
2. 동일 family는 한 row로 합친다.
3. 상위 노출은 최대 `5` row까지다.

## 4. review_action 규칙
priority precedence:
1. `promote_review`
2. `defer_review`
3. `hold_monitor`

세부 규칙:
1. `promote_review`
   - `promotion_governance.state == promotable`
   - `promotion_governance.promotion_bias == consider_promote`
   - thin sample 아님
   - family execution status != `manual_review`

2. `defer_review`
   - `promotion_governance.state == defer`
   - 또는 lifecycle state in `{degraded, retired}`
   - 또는 family execution status == `manual_review`

3. `hold_monitor`
   - 위 둘이 아니면 기본값

guardrail:
1. thin sample이면 무조건 `promote_review` 금지
2. `defer_review`는 negative verdict가 아니라, 먼저 guardrail 원인을 review하라는 뜻이다
3. `hold_monitor`는 backlog 관찰 상태다

## 5. priority_rank 규칙
정렬은 숫자 `priority_rank`로 고정한다. 낮을수록 먼저 본다.

### 5.1 base rank
1. `promote_review` -> `10`
2. `defer_review` -> `20`
3. `hold_monitor` -> `30`

### 5.2 promote-side 보정
`promote_review` row에서:
1. lifecycle state == `production` -> `-2`
2. lifecycle state == `probation` -> `-1`
3. positive expansion confidence `high` -> `-2`
4. positive expansion confidence `medium` -> `-1`
5. capital allocator tier == `boost` -> `-1`

### 5.3 defer-side 보정
`defer_review` row에서:
1. family execution status == `manual_review` -> `-3`
2. lifecycle state == `retired` -> `-2`
3. capital pressure == `overallocated_negative` -> `-1`

### 5.4 hold-side 보정
`hold_monitor` row에서:
1. lifecycle state == `probation` -> `-1`
2. positive expansion state == `expandable` but promotion state != `promotable` -> `-1`
3. thin sample hold는 추가 보정 없이 맨 뒤에 둔다

### 5.5 tie-break
tie-break 순서:
1. `confidence` high > medium > low
2. lifecycle severity
   - `retired`
   - `degraded`
   - `production`
   - `probation`
   - `research`
3. family name ascending

## 6. queue_state 규칙
1. top row가 `promote_review`면 `promotion_ready_queue`
2. top row가 `defer_review`면 `defer_first_queue`
3. top row가 `hold_monitor`면 `monitor_only_queue`
4. review queue가 비어 있으면 `empty_queue`

## 7. headline_family / top_review_action 규칙
1. `headline_family`는 정렬 후 첫 번째 row의 family
2. `top_review_action`은 정렬 후 첫 번째 row의 review_action
3. queue가 비어 있으면 둘 다 빈 문자열

## 8. confidence 규칙
각 row confidence는 다음처럼 정리한다.
1. `promotion_governance.confidence`가 있으면 우선 사용
2. 없으면 lifecycle confidence를 fallback
3. 둘 다 없으면 `low`

queue headline confidence는 top row confidence를 따른다.

## 9. source_summary 규칙
top-level `source_summary`에는 아래만 허용한다.
1. `promotion_ready_count`
2. `defer_count`
3. `hold_count`
4. `thin_sample_count`
5. `top_lifecycle_state`
6. `top_promotion_state`
7. `top_allocator_tier`

## 10. reason_codes 규칙
허용 prefix:
1. `promotion_review_queue:*`
2. `promotion_governance:*`
3. `lifecycle:*`
4. `positive_expansion:*`
5. `allocator:*`
6. `sample:*`

예시:
1. `promotion_review_queue:promotion_ready_queue`
2. `promotion_governance:promotable`
3. `lifecycle:probation`
4. `allocator:boost`
5. `sample:thin_sample`

## 11. wording 규칙
1. `promote_review`
   - "review first for controlled promotion"
2. `defer_review`
   - "review guardrail causes before promotion"
3. `hold_monitor`
   - "keep in monitor queue while evidence accumulates"
4. queue headline도 `auto promote`, `auto defer` 같은 wording은 금지한다.
