# Outcome-First Rollout Recommendation Derivation Rules

최종 갱신: 2026-03-23
상태: Item 2 baseline fixed

## 1. 목적
- `expand / hold / reduce / research_only` recommendation이 어떤 evidence 조합에서 나오는지 고정한다.
- 이번 문서는 rollout policy source-of-truth를 바꾸지 않고, recommendation 생성 규칙만 정의한다.

## 2. evidence normalization
rollout recommendation은 family 기준 evidence를 먼저 정규화한다.

### 2A. family outcome state
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

### 2B. family execution state
`family_execution_degradation_advisory.families[*]` 기준

1. `manual_review`
- family advisory status가 `manual_review`

2. `watch`
- family advisory status가 `watch`

3. `healthy`
- family advisory status가 `healthy`

4. `unavailable`
- row 없음

### 2C. family mode state
`mode_advisory.family[*]` 기준

1. `research_only`
2. `promotion_watch`
3. `watch`
4. `keep_current_mode`
5. `unavailable`

### 2D. maturity bucket
family rollout recommendation은 아래 maturity bucket을 먼저 정한다.

1. `thin_sample`
- family `closed < 4`
- 또는 family execution confidence `low`
- 또는 family mode advisory sample note가 thin sample

2. `usable`
- family `closed >= 4` and `< 8`
- 또는 family execution confidence `medium`

3. `mature`
- family `closed >= 8`
- and family execution confidence `high` 또는 최소 `medium` 이상

주의:
- `mature`가 아니면 `expand`를 직접 추천하지 않는다.
- `thin_sample`에서는 `reduce`도 hard wording 대신 `hold` 또는 `research_only`를 우선한다.

## 3. recommendation precedence
최종 recommendation은 아래 우선순위로 결정한다.

### Rule 1. research_only
다음 중 하나면 `research_only`

1. family mode advisory가 `research_only`
2. maturity가 `thin_sample`이고 quality/advisory 신호가 이미 부정적
3. promotion watchlist보다 softening/research signal이 더 강함

요약:
- research bucket 유지가 우선
- rollout 확대/축소보다 evidence 수집이 먼저

### Rule 2. reduce
다음 중 하나면 `reduce`

1. family execution state가 `manual_review`
2. family outcome state가 `negative` and family execution state가 `watch` 이상
3. family execution state가 `watch` and family mode state가 `watch`
4. current global execution degradation가 `manual_review` and family evidence도 중립 이하

요약:
- rollout expansion을 멈추고 보수화 검토
- 단, `thin_sample`이면 바로 `reduce` 대신 `hold`로 완화 가능

### Rule 3. expand
다음을 모두 만족하면 `expand`

1. maturity가 `mature`
2. family outcome state가 `positive`
3. family execution state가 `healthy`
4. family mode state가 `keep_current_mode` 또는 `promotion_watch`
5. global execution degradation가 `healthy` 또는 최소 `watch` 이하이되 family conflict가 없음

요약:
- operator가 incremental expansion을 검토할 수 있는 상태
- 자동 적용은 아님

### Rule 4. hold
위 세 규칙에 해당하지 않으면 기본값은 `hold`

대표 예시:
1. family outcome `mixed`
2. family outcome `positive`지만 maturity가 `usable`
3. family outcome `negative`지만 sample이 얇음
4. family execution `healthy`인데 mode/watch evidence가 일부 남아 있음

## 4. regime / session modifier rules
regime/session은 family recommendation을 뒤집는 1차 근거가 아니라 보조 modifier다.

### 4A. positive modifier
다음이면 positive modifier 추가

1. regime 또는 session bucket이 `closed >= 4`
2. `baseline_cost_profitable_rate_from_closed >= 0.50`
3. mode advisory가 `watch/research_only`가 아님

효과:
- `hold -> hold` 유지, confidence 상향 가능
- `expand -> expand` 유지, reason 강화
- `reduce`를 `expand`로 바꾸지는 않음

### 4B. negative modifier
다음이면 negative modifier 추가

1. regime 또는 session bucket이 `closed >= 4`
2. `baseline_cost_profitable_rate_from_closed <= 0.30`

효과:
- family가 `expand` 후보면 `hold`로 낮출 수 있음
- family가 `hold`면 negative hold summary로 남김
- family가 `reduce`면 reason 강화만 하고 recommendation은 그대로

### 4C. thin-sample modifier
regime/session `closed < 4`면 modifier를 적용하지 않는다.

## 5. confidence derivation
recommendation confidence는 아래 기준으로 정한다.

1. `high`
- maturity `mature`
- family execution confidence `high`
- family mode state가 thin sample 아님

2. `medium`
- maturity `usable`
- 또는 family execution confidence `medium`

3. `low`
- maturity `thin_sample`
- 또는 conflicting evidence가 많아 family 결론이 약함

## 6. suggested policy delta derivation
`suggested_policy_delta`는 실제 DB write가 아니라 operator hint다.

### 6A. expand
1. `action = expand_consideration`
2. `suggested_max_execution_mode = one_step_higher(current.max_execution_mode)`
3. `suggested_max_risk_r = current.max_risk_r` 유지
4. `change_hint = incremental_mode_step_only`

설명:
- 우선 mode step만 한 단계 검토
- risk cap 숫자는 이번 라운드에서 자동 확대 제안하지 않음

### 6B. hold
1. `action = no_change`
2. `suggested_max_execution_mode = current.max_execution_mode`
3. `suggested_max_risk_r = current.max_risk_r`
4. `change_hint = keep_current_policy`

### 6C. reduce
1. `action = reduce_consideration`
2. `suggested_max_execution_mode = one_step_lower_or_same(current.max_execution_mode)`
3. `suggested_max_risk_r = round(current.max_risk_r * 0.5, 4)`
4. `change_hint = reduce_mode_or_risk_after_operator_review`

주의:
- 이미 `SHADOW`면 mode는 유지하고 risk hint만 낮춘다.

### 6D. research_only
1. `action = keep_research_only`
2. `suggested_max_execution_mode = current.max_execution_mode`
3. `suggested_max_risk_r = current.max_risk_r`
4. `change_hint = keep_research_bucket_and_collect_evidence`

## 7. reason code generation
reason_codes는 family 중심으로 만들고 regime/session modifier를 뒤에 붙인다.

### 7A. core family reasons
- `family_outcome:positive`
- `family_outcome:mixed`
- `family_outcome:negative`
- `family_execution:healthy`
- `family_execution:watch`
- `family_execution:manual_review`
- `mode_advisory:keep_current_mode`
- `mode_advisory:watch`
- `mode_advisory:research_only`

### 7B. sample reasons
- `sample:thin_family_closed`
- `sample:usable_family_closed`
- `sample:mature_family_closed`

### 7C. modifier reasons
- `regime_outcome:positive`
- `regime_outcome:negative`
- `session_outcome:positive`
- `session_outcome:negative`

### 7D. policy reasons
- `policy:max_mode_shadow`
- `policy:max_mode_paper`
- `policy:max_mode_micro_live`
- `policy:live_disabled`

## 8. guardrails
다음은 recommendation을 직접 바꾸지 않는다.

1. approval state
2. `deployment_go_no_go`
3. `recommended_risk_r`
4. rollout policy repository row

즉 recommendation은 explanation / suggestion layer다.

## 9. implementation notes
구현 시 우선순위는 아래로 고정한다.

1. current policy snapshot 로드
2. family evidence normalize
3. maturity bucket 계산
4. precedence 적용 (`research_only -> reduce -> expand -> hold`)
5. regime/session modifier 반영
6. confidence / suggested delta / summary / reason_codes 생성

## 10. 완료 기준
1. 같은 입력이면 항상 같은 recommendation이 나온다.
2. thin-sample 구간에서 `expand`가 나오지 않는다.
3. negative family evidence가 `expand`로 잘못 읽히지 않는다.
4. recommendation이 rollout policy DB 자동 변경처럼 읽히지 않는다.
