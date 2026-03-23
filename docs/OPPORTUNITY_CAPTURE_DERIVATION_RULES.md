# Opportunity Capture Derivation Rules

최종 갱신: 2026-03-23
상태: Item 2 baseline fixed

## 1. 목적
- `score_to_outcome_funnel`과 runtime blocked mix를 같은 방식으로 해석해서, 같은 입력이면 항상 같은 `opportunity_capture` summary가 나오게 한다.
- 이번 규칙은 `설명 계층`만 정의한다. approval, sizing, rollout policy를 직접 바꾸지 않는다.

## 2. 입력 우선순위
1. 1순위: `score_to_outcome_funnel`
- `report_window_days`
- `snapshot_selection`
- `historical_execution_outcomes`
- `decomposition.family`
- `decomposition.regime`
- `decomposition.session`

2. 2순위: runtime blocked mix
- `portfolio_budget.blocked_gate_group_counts`
- 없으면 `blocked_reason_counts`를 gate group으로 재분류해서 사용

3. 3순위: execution quality 보조 근거
- `execution_quality_summary.fill_rate`
- `execution_quality_summary.fill_events_total`

## 3. 기본 수치 규칙
### 3.1 report_window_days
- `report_window_days = max(1, score_to_outcome_funnel.report_window_days)`

### 3.2 trades_per_day
- `submitted = historical_execution_outcomes.submitted / report_window_days`
- `filled = historical_execution_outcomes.filled / report_window_days`
- `closed = historical_execution_outcomes.closed / report_window_days`
- 소수점 넷째 자리 반올림

### 3.3 capture_rates
- `accept_rate = snapshot_selection.accept_rate`
- `submit_rate_from_runtime = historical_execution_outcomes.submitted / snapshot_selection.runtime_candidates`
- `fill_rate_from_submitted = historical_execution_outcomes.fill_rate_from_submitted`
- `close_rate_from_filled = historical_execution_outcomes.close_rate_from_filled`
- 분모가 0이면 `0.0`
- 소수점 넷째 자리 반올림

### 3.4 capture_gap
- `runtime_to_submit_gap = 1 - submit_rate_from_runtime`
- `submit_to_fill_gap = 1 - fill_rate_from_submitted`
- `fill_to_close_gap = 1 - close_rate_from_filled`
- 소수점 넷째 자리 반올림

## 4. blocked_mix 규칙
### 4.1 gate group source 선택
1. `snapshot_selection.blocked_gate_group_counts`가 있으면 그대로 사용
2. 없으면 `snapshot_selection.blocked_reason_counts`를 gate group으로 재분류
3. 그래도 없으면 빈 object

### 4.2 gate group mapping
기존 dashboard 분류와 동일하게 맞춘다.

- `safety`
  - `reconciliation_*`
  - `kill_switch*`
  - `close_only*`
  - `operating_lock*`
  - `shock*`
  - `transition*`
  - `risk_lock*`
  - `session_lock*`
  - `validation_fail*`
  - `user_stream_stale*`
- `structural`
  - `total_cap_reached`
  - `directional_cap_reached`
  - `cluster_cap_reached`
  - `thesis_duplicate_blocked`
  - `thesis_active_cap_reached`
  - `thesis_cluster_cap_zero_risk`
- `rollout`
  - `mode_shadow_only`
  - `mode_daily_trade_limit_reached`
  - `mode_total_risk_cap_reached`
  - `live_disabled_family`
  - `execution_mode_cap_exceeded`
  - `micro_live_session_not_allowed`
- `quality`
  - `risk_budget_below_min`
  - `adjusted_score_non_positive`
  - `invalid_candidate`
  - `sizing_zero_risk`
- 그 외
  - `unknown`

### 4.3 blocked_mix normalization
- `blocked_mix`는 count object 그대로 유지한다.
- 별도 비율 필드는 만들지 않는다.
- summary wording이 필요할 때만 `share_of_runtime_candidates = blocked / runtime_candidates`를 내부 계산으로 사용한다.

## 5. maturity bucket 규칙
activity 성숙도는 아래처럼 고정한다.

1. `thin_activity`
- `historical_execution_outcomes.submitted < 5`
  또는 `historical_execution_outcomes.closed < 3`

2. `usable_activity`
- `submitted >= 5`
  그리고 `closed >= 3`
  그리고 `closed < 10`

3. `mature_activity`
- `submitted >= 10`
  그리고 `closed >= 10`

`thin_activity` 구간에서는 공격적인 negative wording을 금지한다.

## 6. dominant_bottleneck 규칙
### 6.1 stage gap 후보
- `runtime_to_submit_gap`
- `submit_to_fill_gap`
- `fill_to_close_gap`

### 6.2 thin activity 우선 규칙
- maturity가 `thin_activity`이고
  (`historical_execution_outcomes.submitted == 0`
  또는 `historical_execution_outcomes.closed == 0`)
  이면:
  - `dominant_bottleneck.stage = "runtime_to_submit"`
  - `dominant_bottleneck.reason = "thin_activity_window"`

### 6.3 일반 우선순위
가장 큰 gap을 stage로 선택한다.
동률이면 아래 우선순위를 적용한다.
1. `runtime_to_submit`
2. `submit_to_fill`
3. `fill_to_close`

### 6.4 reason 규칙
1. `runtime_to_submit`
- `quality` blocked가 최댓값이면 `quality_blocking`
- 아니면 `rollout` blocked가 최댓값이면 `rollout_blocking`
- 아니면 `structural` 또는 `safety` blocked가 최댓값이면 `structural_blocking`
- blocked mix가 거의 없고 thin activity면 `thin_activity_window`
- 그 외 `selection_shortfall`

2. `submit_to_fill`
- execution quality summary에 `fill_rate < 0.8` 또는 `fill_events_total >= 5`인데 fill shortage가 유지되면 `execution_fill_shortfall`
- 그렇지 않으면 `submission_to_fill_dropoff`

3. `fill_to_close`
- `close_rate_from_filled < 0.8`이면 `fill_to_close_dropoff`
- thin activity면 `thin_activity_window`
- 그 외 `position_resolution_delay`

## 7. family_focus 선택 규칙
### 7.1 후보 source
- `score_to_outcome_funnel.decomposition.family[*]`

### 7.2 focus score
family row별로 아래 값을 계산한다.

- `submit_rate_from_runtime = submitted / runtime_candidates`
- `runtime_to_submit_gap = 1 - submit_rate_from_runtime`
- `throughput_focus_score =`
  - `runtime_candidates * 100`
  - `+ runtime_to_submit_gap * 10`
  - `+ (1 - fill_rate_from_submitted) * 5`
  - `+ (1 - close_rate_from_filled) * 3`

분모가 0이면 각 rate는 `0.0`

### 7.3 선택 우선순위
가장 높은 `throughput_focus_score`
동률이면:
1. `runtime_candidates` 큰 쪽
2. `submitted` 큰 쪽
3. `closed` 큰 쪽
4. `key` 오름차순

### 7.4 family_focus 출력 필드
- `key`
- `runtime_candidates`
- `accepted_candidates`
- `submitted`
- `filled`
- `closed`
- `accept_rate`
- `submit_rate_from_runtime`
- `fill_rate_from_submitted`

## 8. regime_modifier / session_modifier 규칙
### 8.1 후보 source
- `score_to_outcome_funnel.decomposition.regime[*]`
- `score_to_outcome_funnel.decomposition.session[*]`

### 8.2 state 판정
아래 순서대로 판정한다.

1. `negative`
- `runtime_candidates >= 3`
  그리고 (`submit_rate_from_runtime < 0.2`
  또는 `fill_rate_from_submitted < 0.5`)

2. `positive`
- `runtime_candidates >= 3`
  그리고 `submit_rate_from_runtime >= 0.5`
  그리고 `fill_rate_from_submitted >= 0.7`

3. `neutral`
- 위 조건에 걸리지 않음

4. `unavailable`
- `runtime_candidates == 0`
  그리고 `submitted == 0`

### 8.3 선택 규칙
- regime/session 각각에 대해 `negative`가 있으면 그중 `runtime_candidates`가 가장 큰 bucket 선택
- 없으면 `positive` 중 `runtime_candidates`가 가장 큰 bucket 선택
- 없으면 `neutral` 중 `runtime_candidates`가 가장 큰 bucket 선택
- 전부 없으면 `unavailable`

## 9. summary wording 규칙
summary는 아래 headline만 사용한다.

1. `thin activity`
- reason: `thin_activity_window`
- wording:
  - `activity is thin; current window is too small to separate scarcity from degradation`

2. `blocking-heavy`
- dominant stage가 `runtime_to_submit`
- reason이 `quality_blocking`, `rollout_blocking`, `structural_blocking`
- wording:
  - `throughput is constrained more by blocking than by fill failure`

3. `execution-heavy`
- dominant stage가 `submit_to_fill`
- reason이 `execution_fill_shortfall`
- wording:
  - `signal flow reaches submission but degrades at fill`

4. `close-throughput-heavy`
- dominant stage가 `fill_to_close`
- wording:
  - `fills are occurring, but close throughput lags`

family headline이 있으면 뒤에 붙인다.
- 예:
  - `throughput is constrained more by blocking than by fill failure; family signal flow remains thin`

## 10. guardrails
이번 derivation rule에서 하지 않는 것:
1. accept_rate가 낮다고 approval threshold를 자동 완화
2. fill shortage가 보인다고 sizing을 직접 수정
3. family focus를 rollout policy 변경으로 바로 연결
4. `thin_activity`를 곧바로 negative family verdict로 사용

즉 `opportunity_capture`는 throughput explanation layer다.
