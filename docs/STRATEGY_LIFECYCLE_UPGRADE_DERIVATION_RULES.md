# Strategy Lifecycle Upgrade Derivation Rules

최종 갱신: 2026-03-23
상태: Item 2 baseline fixed

## 1. 목적
- family 중심 lifecycle state가 기존 research / rollout / degradation / outcome 입력에서 어떤 규칙으로 파생되는지 고정한다.
- 이번 문서는 governance summary 규칙만 정의한다. approval, sizing, rollout policy DB row는 직접 바꾸지 않는다.

## 2. evidence normalization
lifecycle은 아래 evidence를 먼저 정규화한다.

### 2A. previous_state
`rollout_recommendation.current_policy` 기준으로 현재 운영 posture를 추정한다.

1. `research`
- `live_enabled == false`
- 그리고 `max_execution_mode == SHADOW`

2. `probation`
- `max_execution_mode == PAPER`

3. `production`
- `live_enabled == true`
- 그리고 `max_execution_mode in {MICRO_LIVE, LIVE}`

주의:
- 이번 라운드에서는 persisted lifecycle history가 없으므로 `previous_state`는 실제 history가 아니라 현재 policy-derived posture다.
- `previous_state`는 `degraded`나 `retired`를 직접 반환하지 않는다.

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

1. `manual_review`
2. `watch`
3. `healthy`
4. `unavailable`

confidence는 existing advisory의 `confidence`를 그대로 사용한다.

### 2D. family mode state
`mode_advisory.family[*]` 기준

1. `research_only`
2. `promotion_watch`
3. `watch`
4. `keep_current_mode`
5. `unavailable`

### 2E. rollout state
`rollout_recommendation.family[*]` 기준

1. `recommendation`
- `expand / hold / reduce / research_only`

2. `maturity`
- `thin_sample / usable / mature`

3. `current_policy`
- `live_enabled`
- `max_execution_mode`
- `max_risk_r`

주의:
- lifecycle은 rollout recommendation을 재해석할 뿐, rollout policy source-of-truth를 대체하지 않는다.

### 2F. alpha research signal
`alpha_research_pipeline`은 family-resolved source가 아니므로 support-only 신호로만 사용한다.

1. `promotion_watch`
- `promotion_watchlist.available == true`
- 그리고 `watch_items[*].not_ready_reason in {None, "", "none"}`
- 그리고 `confidence in {"medium", "high"}`

2. `research_active`
- `recommended_action_summary` 존재
  또는 `research_focus_alignment.available == true`

3. `unavailable`
- 위 조건이 모두 아님

주의:
- alpha research signal은 단독으로 `production`, `degraded`, `retired`를 만들지 않는다.

### 2G. lifecycle modifier
`rollout_recommendation.top_modifier` 기준

1. `negative`
- `top_modifier.state == negative`

2. `positive`
- `top_modifier.state == positive`

3. `neutral`
- modifier 없음 또는 명시적 neutral/unavailable

modifier는 family state를 뒤집는 1차 근거가 아니라 support-only 보정이다.

## 3. lifecycle state precedence
최종 lifecycle state는 아래 우선순위로 결정한다.

1. `retired`
2. `degraded`
3. `production`
4. `probation`
5. `research`

즉 negative/off-ramp를 먼저 보고, 그 다음 stable live state, 그 다음 pre-live state, 마지막으로 research state를 판정한다.

## 4. state rules
### Rule 1. retired
다음을 모두 만족하면 `retired`

1. `previous_state in {probation, production}`
2. `rollout recommendation == research_only`
3. `rollout maturity != thin_sample`
4. 아래 중 하나
- `family execution state == manual_review`
- `family outcome state == negative`
- `family mode state == research_only`

요약:
- 한때 live/probation posture였지만, 이제는 research backlog로만 유지해야 하는 family

guardrail:
- `previous_state == research`이면 `retired`를 쓰지 않고 `research`에 남긴다.

### Rule 2. degraded
다음을 만족하면 `degraded`

1. `previous_state in {probation, production}`
2. 아래 중 하나
- `rollout recommendation == reduce`
- `family execution state == manual_review`
- `family execution state == watch` and `family outcome state == negative`
- `family mode state == watch` and `family outcome state in {negative, mixed}`

요약:
- live/probation family가 유지 불가까진 아니지만 보수화가 필요한 상태

guardrail:
- thin sample만으로 `degraded`를 만들지 않는다.
- `negative modifier` 단독으로 `degraded`를 만들지 않는다.

### Rule 3. production
다음을 모두 만족하면 `production`

1. `rollout recommendation in {expand, hold}`
2. `rollout maturity == mature`
3. `family outcome state == positive`
4. `family execution state == healthy`
5. `family mode state in {keep_current_mode, promotion_watch, unavailable}`
6. `lifecycle modifier != negative`

요약:
- mature post-cost evidence와 healthy execution이 같이 있는 family

주의:
- `previous_state`가 `research` 또는 `probation`이어도 위 조건을 만족하면 target lifecycle은 `production`이 될 수 있다.
- 단, 실제 rollout policy DB 변경은 별도다.

### Rule 4. probation
위 규칙에 걸리지 않았고, 아래 중 하나면 `probation`

1. `rollout maturity == usable`
   그리고 `rollout recommendation in {hold, expand}`
   그리고 `family execution state in {healthy, watch, unavailable}`

2. `family mode state == promotion_watch`
   그리고 `family execution state != manual_review`

3. `alpha research signal == promotion_watch`
   그리고 `rollout recommendation in {hold, expand}`
   그리고 `family outcome state != negative`

4. `previous_state == production`
   그리고 hard negative는 아니지만 evidence가 `mature -> usable` 또는 `positive -> mixed`로 약해짐

요약:
- live expansion 전 단계이거나, production에서 한 단계 보수화되어 재검증이 필요한 family

guardrail:
- `thin_sample`은 기본적으로 probation을 만들지 않는다.
- 예외는 `family mode state == promotion_watch`이고 family execution이 healthy 쪽일 때만 제한적으로 허용한다.

### Rule 5. research
위 규칙에 걸리지 않으면 기본값은 `research`

대표 예시:
1. `rollout recommendation == research_only`
2. `family mode state == research_only`
3. `rollout maturity == thin_sample`
4. `family outcome state == unavailable`
5. `alpha research signal == research_active`인데 promotion-ready evidence는 없음

요약:
- 아직 live 승격을 논하기보다 evidence 수집이 먼저인 family

## 5. transition_bias rules
`transition_bias`는 state와 previous_state 조합으로 결정한다.

### 5A. `promote`
아래 중 하나면 `promote`

1. `previous_state == research` and `state == probation`
2. `previous_state in {research, probation}` and `state == production`

### 5B. `degrade`
아래 중 하나면 `degrade`

1. `state == degraded`
2. `previous_state == production` and `state == probation`

### 5C. `retire`
1. `state == retired`

### 5D. `observe`
아래 중 하나면 `observe`

1. `state == research` and `rollout maturity == thin_sample`
2. evidence conflict가 커서 research에 남기되 state change를 강하게 말하기 어려움

### 5E. `hold`
위 네 규칙에 해당하지 않으면 기본값은 `hold`

## 6. confidence derivation
confidence는 아래처럼 고정한다.

1. `high`
- `state in {production, degraded, retired}`
- 그리고 `rollout maturity == mature`
- 그리고 `family execution confidence in {"medium", "high"}`

2. `medium`
- `state == probation`
- 또는 `rollout maturity == usable`
- 또는 evidence가 한 방향으로는 정렬됐지만 sample이 아직 moderate

3. `low`
- `rollout maturity == thin_sample`
- 또는 `alpha research signal`만 있고 family outcome / execution 정렬이 약함

## 7. reason code generation
reason_codes는 아래 prefix만 사용한다.

### 7A. state reasons
- `lifecycle:research`
- `lifecycle:probation`
- `lifecycle:production`
- `lifecycle:degraded`
- `lifecycle:retired`

### 7B. rollout reasons
- `rollout_recommendation:expand`
- `rollout_recommendation:hold`
- `rollout_recommendation:reduce`
- `rollout_recommendation:research_only`

### 7C. family reasons
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

### 7D. sample reasons
- `sample:thin_sample`
- `sample:usable`
- `sample:mature`

### 7E. research / modifier reasons
- `promotion_watchlist:eligible`
- `promotion_watchlist:inactive`
- `alpha_research:research_active`
- `modifier:positive`
- `modifier:negative`

## 8. source_summary fields
`source_summary`는 아래 축만 노출한다.

- `family_closed`
- `family_post_cost_rate`
- `family_execution_status`
- `family_mode_advisory_state`
- `rollout_recommendation`
- `rollout_maturity`
- `previous_state`
- `alpha_research_signal`
- `modifier_state`

## 9. summary wording guardrails
summary 문구는 아래 원칙을 지킨다.

1. `production`
- stable wording
- `mature positive post-cost evidence and healthy execution support production posture`

2. `probation`
- pre-promotion wording
- `usable evidence supports probation while rollout remains one step below production`

3. `research`
- evidence-collection wording
- `family remains research-led until repeat post-cost evidence and rollout maturity improve`

4. `degraded`
- defensive wording
- `family has weakened from live-ready posture and should be reviewed in degraded mode`

5. `retired`
- off-ramp wording
- `family should be taken out of live rotation and maintained as research backlog only`

## 10. guardrails
다음은 lifecycle이 직접 바꾸지 않는다.

1. approval state
2. `recommended_risk_r`
3. `allocated_risk_r`
4. rollout policy DB row
5. scanner ranking
6. portfolio ordering

즉 lifecycle은 governance summary이며, execution authority가 아니다.
