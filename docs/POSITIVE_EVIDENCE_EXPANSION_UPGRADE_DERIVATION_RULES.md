# Positive Evidence Expansion Upgrade Derivation Rules

최종 갱신: 2026-03-23
상태: Item 2 baseline fixed

## 1. 목적
- `expandable / hold / not_ready`가 어떤 evidence 조합에서 나오는지 고정한다.
- 이번 문서는 positive expansion을 execution authority가 아니라 compare-only confidence language로 정의한다.
- approval, sizing, rollout policy DB row는 직접 바꾸지 않는다.

## 2. evidence normalization
positive expansion은 family 기준 evidence를 먼저 정규화한다.

### 2A. family selection
positive expansion은 `rollout_recommendation.family`를 primary anchor로 사용한다.

규칙:
1. `rollout_recommendation.family`가 있으면 그 family를 사용
2. 없으면 `strategy_lifecycle.family`
3. 그래도 없으면 `score_to_outcome_funnel.decomposition.family`에서 `closed`가 가장 큰 family

주의:
- 이번 라운드에서는 multi-family expansion matrix를 만들지 않는다.
- top family 1개만 headline으로 사용한다.

### 2B. family outcome state
`score_to_outcome_funnel.decomposition.family[*]` 기준

1. `positive`
- `closed >= 4`
- `baseline_cost_profitable_rate_from_closed >= 0.50`

2. `negative`
- `closed >= 4`
- `baseline_cost_profitable_rate_from_closed <= 0.30`

3. `mixed`
- `closed >= 4`
- `0.30 < baseline_cost_profitable_rate_from_closed < 0.50`

4. `unavailable`
- `closed < 4` 또는 row 없음

### 2C. family execution state
`family_execution_degradation_advisory.families[*]` 기준

1. `healthy`
2. `watch`
3. `manual_review`
4. `unavailable`

confidence는 existing advisory의 `confidence`를 그대로 사용한다.

### 2D. family mode state
`mode_advisory.family[*]` 기준

1. `keep_current_mode`
2. `promotion_watch`
3. `watch`
4. `research_only`
5. `unavailable`

### 2E. rollout state
`rollout_recommendation` 기준

1. `recommendation`
- `expand / hold / reduce / research_only`

2. `maturity`
- `thin_sample / usable / mature`

3. `confidence`
- existing rollout confidence

주의:
- positive expansion은 rollout recommendation을 대체하지 않고, 그 위에 confidence language만 덧붙인다.

### 2F. lifecycle state
`strategy_lifecycle` 기준

1. `research`
2. `probation`
3. `production`
4. `degraded`
5. `retired`

transition bias는 support-only로 사용한다.

### 2G. capital allocator support state
`capital_allocator_summary` 기준

1. `boost`
- `family_focus == selected family`
- 그리고 `family_weights[0].tier == boost`

2. `reduce`
- `family_focus == selected family`
- 그리고 `family_weights[0].tier == reduce`

3. `neutral`
- 위 조건에 걸리지 않음

주의:
- allocator는 support-only다.
- allocator가 `boost`여도 thin sample / execution drag / research-only guardrail을 뒤집지 못한다.

### 2H. modifier state
`rollout_recommendation.top_modifier` 기준

1. `positive`
2. `negative`
3. `neutral`

modifier는 expansion confidence를 강화/완화하지만 family core verdict를 1차로 대체하지 않는다.

## 3. state precedence
최종 state는 아래 우선순위로 결정한다.

1. `not_ready`
2. `expandable`
3. `hold`

즉 positive expansion language도 먼저 guardrail과 negative condition을 본다.

## 4. state rules
### Rule 1. not_ready
다음 중 하나면 `not_ready`

1. `rollout_maturity == thin_sample`
2. `family_outcome_state in {negative, unavailable}`
3. `family_execution_state in {watch, manual_review}`
4. `family_mode_state == research_only`
5. `rollout_recommendation in {reduce, research_only}`
6. `lifecycle_state in {research, degraded, retired}`

요약:
- 아직 positive expansion language를 붙일 때가 아닌 family

guardrail:
- `positive modifier`
- `allocator boost`
둘 다 위 조건을 뒤집지 못한다.

### Rule 2. expandable
다음을 모두 만족하면 `expandable`

1. `rollout_maturity == mature`
2. `family_outcome_state == positive`
3. `family_execution_state == healthy`
4. `family_mode_state in {keep_current_mode, promotion_watch, unavailable}`
5. `rollout_recommendation in {expand, hold}`
6. `lifecycle_state in {production, probation}`
7. `modifier_state != negative`

support strengthening:
- `rollout_recommendation == expand`면 stronger
- `lifecycle_state == production`이면 stronger
- `allocator_support_state == boost`면 stronger

요약:
- mature positive evidence와 healthy execution이 함께 있어 controlled expansion review를 검토할 수 있는 family

주의:
- `expandable`은 auto-expand가 아니다.
- `hold rollout policy but expandable summary`는 허용한다. 즉 policy는 그대로인데 evidence는 상향 검토 가능할 수 있다.

### Rule 3. hold
위 두 규칙에 걸리지 않으면 기본값은 `hold`

대표 예시:
1. `family_outcome_state == positive`지만 `rollout_maturity == usable`
2. `family_outcome_state == positive`지만 `modifier_state == negative`
3. `lifecycle_state == probation`이고 positive cluster는 있으나 아직 mature 확신이 부족함
4. `allocator_support_state == boost`지만 rollout/lifecycle이 아직 강한 확장 언어까지는 못 줌

요약:
- positive evidence는 일부 있지만 expansion-ready로 보기엔 아직 이르다

## 5. expansion_bias rules
### 5A. `consider_expand`
아래를 모두 만족하면 `consider_expand`

1. `state == expandable`
2. `rollout_recommendation == expand`
3. `lifecycle_state in {production, probation}`

### 5B. `do_not_expand`
1. `state == not_ready`

### 5C. `hold`
위 둘이 아니면 기본값은 `hold`

요약:
- positive expansion bias도 rollout/lifecycle guardrail을 먼저 따른다.

## 6. confidence derivation
confidence는 아래처럼 고정한다.

1. `high`
- `state == expandable`
- `rollout_maturity == mature`
- `family_execution` confidence `high`
- `rollout_recommendation == expand`
- `lifecycle_state == production`

2. `medium`
- `state == expandable`지만 위 high 조건을 다 채우지 못함
- 또는 `state == hold`이고 positive evidence가 명확하나 아직 usable/mixed guardrail이 남음

3. `low`
- `state == not_ready`
- 또는 evidence conflict가 커서 positive verdict가 약함

## 7. modifier rules
### 7A. positive modifier
`modifier_state == positive`

효과:
- `expandable`은 유지하고 confidence 강화 가능
- `hold`는 `hold` 유지, 요약과 reason 강화
- `not_ready`를 `hold`로 바꾸지 않음

### 7B. negative modifier
`modifier_state == negative`

효과:
- `expandable -> hold`
- `hold`는 그대로 유지
- `not_ready`는 그대로 유지

주의:
- negative modifier는 guardrail 완화가 아니라 positive wording 보수화에만 사용한다.

## 8. capital allocator support rules
allocator는 support-only로만 사용한다.

### 8A. allocator boost
`allocator_support_state == boost`

효과:
- `expandable` confidence 강화 가능
- `hold` summary에 “capital underallocation” 같은 보조 언어 추가 가능
- `not_ready`를 상향하지 않음

### 8B. allocator reduce
`allocator_support_state == reduce`

효과:
- `expandable -> hold`로 낮출 수 있음
- `hold`는 그대로 유지
- `not_ready`는 reason 강화만 함

## 9. reason code generation
reason code는 아래 prefix만 사용한다.

### 9A. state reasons
- `positive_expansion:expandable`
- `positive_expansion:hold`
- `positive_expansion:not_ready`

### 9B. family reasons
- `family_outcome:positive`
- `family_outcome:mixed`
- `family_outcome:negative`
- `family_execution:healthy`
- `family_execution:watch`
- `family_execution:manual_review`
- `family_mode:keep_current_mode`
- `family_mode:promotion_watch`
- `family_mode:watch`
- `family_mode:research_only`

### 9C. rollout / lifecycle reasons
- `rollout_recommendation:expand`
- `rollout_recommendation:hold`
- `rollout_recommendation:reduce`
- `rollout_recommendation:research_only`
- `lifecycle:research`
- `lifecycle:probation`
- `lifecycle:production`
- `lifecycle:degraded`
- `lifecycle:retired`

### 9D. support reasons
- `allocator:boost`
- `allocator:reduce`
- `modifier:positive`
- `modifier:negative`
- `sample:thin_sample`
- `sample:usable`
- `sample:mature`

## 10. source_summary fields
`source_summary`는 아래만 노출한다.

- `family_closed`
- `family_post_cost_rate`
- `family_execution_status`
- `family_mode_advisory_state`
- `rollout_recommendation`
- `rollout_maturity`
- `lifecycle_state`
- `allocator_tier`
- `modifier_state`

## 11. summary wording rules
### 11A. expandable
- `family has mature positive post-cost evidence and healthy execution; controlled expansion can be reviewed`

### 11B. hold
- `family shows positive evidence, but guardrails still support a hold posture before broader expansion`

### 11C. not_ready
- `family is not ready for positive expansion language because evidence or execution guardrails remain incomplete`

guardrail:
- `expandable`도 항상 `review`, `consider`, `controlled` 언어만 사용한다.

## 12. hard guardrails
positive expansion은 아래를 직접 바꾸지 않는다.

1. approval state
2. `recommended_risk_r`
3. `allocated_risk_r`
4. rollout policy DB row
5. scanner ranking
6. portfolio ordering

즉 positive expansion은 공격적 control layer가 아니라 operator-facing confidence summary다.
