# Capture-Aware Operator Priority Derivation Rules

최종 갱신: 2026-03-23
상태: Item 2 baseline fixed

## 1. 목적
- `opportunity_capture`의 throughput 병목을 `operator_action_priority`의 action wording으로 deterministic 하게 번역한다.
- 같은 입력이면 validation / checklist / dashboard에서 항상 같은 `top_action`, `top_reason`, `next_actions`, `capture_context`가 나오게 한다.
- 이번 규칙은 review order만 정의한다. approval, sizing, rollout policy, threshold를 직접 바꾸지 않는다.

## 2. 입력 우선순위
1. 1순위: 기존 operator priority 입력
- `playbook_action`
- `execution_degradation_advisory`
- `family_execution_degradation_advisory`
- `mode_advisory`
- `alpha_research_recommended_action`
- `alpha_research_softening_review`
- `alpha_research_promotion_watchlist`

2. 2순위: `opportunity_capture_summary`
- 우선 source:
  - `dashboard.signal_funnel.opportunity_capture`
- 없으면 fallback:
  - `validation_report.opportunity_capture_summary`

3. 3순위: checklist / validation 보조 텍스트
- `playbook_message`
- `deployment_message`

즉 capture-aware priority는 기존 priority stack 위에 덧붙는 supporting layer다.

## 3. 정규화 규칙
### 3.1 opportunity_capture availability
- `available = opportunity_capture.available`
- 없거나 `available = false`면 capture-aware action은 생성하지 않는다.

### 3.2 핵심 추출 필드
- `stage = dominant_bottleneck.stage`
- `reason = dominant_bottleneck.reason`
- `family_key = family_focus.key`
- `maturity = maturity`
- `regime_state = regime_modifier.state`
- `session_state = session_modifier.state`

### 3.3 family label 규칙
- `family_key`가 있으면 그대로 사용
- 없으면 `unknown`

### 3.4 maturity 보호
- `maturity in {"thin_activity", "unknown", ""}` 이거나
- `reason == "thin_activity_window"`
- 이면 capture-aware action family는 무조건 `observe`

## 4. capture-aware action 후보 생성 규칙
capture-aware action은 `dominant_bottleneck` 기준으로 최대 1개의 primary candidate만 만든다.

### 4.1 runtime_to_submit / quality_blocking
- action:
  - `review_selection_bottleneck_before_threshold_changes`
- action_family:
  - `selection_review`
- priority_level:
  - `watch`
- reason template:
  - `runtime-to-submit throughput is constrained by quality blocking`

### 4.2 runtime_to_submit / rollout_blocking
- action:
  - `review_rollout_constraints_before_threshold_changes`
- action_family:
  - `rollout_review`
- priority_level:
  - `watch`
- reason template:
  - `runtime-to-submit throughput is constrained by rollout blocking`

### 4.3 runtime_to_submit / structural_blocking
- action:
  - `review_structural_capacity_before_threshold_changes`
- action_family:
  - `capacity_review`
- priority_level:
  - `monitor`
- reason template:
  - `runtime-to-submit throughput is constrained by structural capacity limits`

### 4.4 runtime_to_submit / selection_shortfall
- action:
  - `review_candidate_supply_before_threshold_changes`
- action_family:
  - `selection_review`
- priority_level:
  - `monitor`
- reason template:
  - `runtime-to-submit throughput remains low despite limited explicit blocking`

### 4.5 submit_to_fill / execution_fill_shortfall
- action:
  - `review_execution_fill_shortage_before_strategy_changes`
- action_family:
  - `execution_review`
- priority_level:
  - `watch`
- reason template:
  - `submission-to-fill throughput is degrading at the fill stage`

### 4.6 submit_to_fill / submission_to_fill_dropoff
- action:
  - `review_submission_to_fill_dropoff_before_strategy_changes`
- action_family:
  - `execution_review`
- priority_level:
  - `monitor`
- reason template:
  - `submission-to-fill throughput drops before orders convert into fills`

### 4.7 fill_to_close / fill_to_close_dropoff
- action:
  - `review_position_resolution_delay_before_strategy_changes`
- action_family:
  - `execution_review`
- priority_level:
  - `monitor`
- reason template:
  - `fills are occurring, but close throughput lags after entry`

### 4.8 fill_to_close / position_resolution_delay
- action:
  - `review_position_resolution_delay_before_strategy_changes`
- action_family:
  - `execution_review`
- priority_level:
  - `monitor`
- reason template:
  - `position resolution remains slow after fills`

### 4.9 any stage / thin_activity_window
- action:
  - `observe_activity_window_before_threshold_changes`
- action_family:
  - `observe`
- priority_level:
  - `monitor`
- reason template:
  - `activity is too thin to separate scarcity from degradation`

## 5. top_reason 조립 규칙
### 5.1 base reason
- 먼저 4장의 reason template를 사용한다.

### 5.2 family focus suffix
- `family_key != "unknown"` 이면 뒤에 추가:
  - `; family focus is {family_key}`

### 5.3 regime/session modifier suffix
- `regime_state == "negative"` 이면 뒤에 추가:
  - `; regime modifier is negative`
- `session_state == "negative"` 이면 뒤에 추가:
  - `; session modifier is negative`
- `positive`나 `neutral`은 기본적으로 headline에 붙이지 않는다.

### 5.4 thin-activity 문구 제한
- `reason == "thin_activity_window"`면
  - `quality_blocking`, `rollout_blocking`, `selection_shortfall` 같은 강한 단어를 같이 쓰지 않는다.

## 6. priority stack 결합 규칙
기존 `operator_action_priority` 후보 리스트에 capture-aware candidate를 아래 위치로 삽입한다.

1. `playbook`
2. `execution_degradation`
3. `family_execution_degradation`
4. `opportunity_capture`
5. `mode_advisory`
6. `alpha_research`

즉 capture-aware action은:
- playbook / execution drag보다 뒤
- mode / research보다 앞

## 7. top_action / next_actions 선택 규칙
### 7.1 정렬 규칙
후보 actions는 아래 순서로 정렬한다.

1. `priority_level`
- `urgent > watch > research > monitor`

2. source precedence
- `playbook > execution_degradation > family_execution_degradation > opportunity_capture > mode_advisory > alpha_research`

3. action 문자열 오름차순

### 7.2 top_action
- 정렬 후 첫 번째 candidate를 `top_action`으로 사용한다.

### 7.3 next_actions
- 남은 candidate 중 최대 3개를 `next_actions`로 저장한다.
- capture-aware candidate가 top이 아니어도 위 정렬 규칙상 상위 3개 안이면 `next_actions`에 남긴다.

즉 capture-aware 계층은 꼭 headline이 아니어도 `review order`에는 들어갈 수 있어야 한다.

## 8. priority_source / action_family 규칙
### 8.1 priority_source
- top action source에 따라 아래 값 사용
  - playbook candidate -> `playbook`
  - global execution drag -> `execution_degradation`
  - family execution drag -> `family_execution_degradation`
  - capture-aware candidate -> `opportunity_capture`
  - mode advisory -> `mode_advisory`
  - alpha research -> `alpha_research`
  - no candidate -> `monitor`

### 8.2 action_family
- top action이 capture-aware이면 4장의 mapping 결과를 사용
- 기존 source면 아래로 매핑한다.
  - playbook -> `playbook`
  - global/family execution drag -> `execution_review`
  - mode advisory -> `mode_review`
  - alpha research -> `research`
  - no candidate -> `monitor`

## 9. supporting_signals 규칙
capture-aware summary가 available이면 아래 supporting signal을 추가할 수 있다.

1. 공통
- `capture:{stage}:{reason}`

2. family focus
- `family_key != "unknown"` 이면
  - `capture_family:{family_key}`

3. maturity
- 항상 추가 가능
  - `capture_maturity:{maturity}`

4. negative modifiers
- `regime_state == "negative"`이면
  - `capture_regime:negative`
- `session_state == "negative"`이면
  - `capture_session:negative`

단:
- capture prefix는 `supporting_signals`에만 추가
- `blocking_signals`에는 추가하지 않는다

## 10. capture_context 규칙
`opportunity_capture_summary.available = true`이면 top action source와 무관하게 `capture_context`를 저장한다.

허용 필드:
- `available`
- `dominant_bottleneck`
- `family_focus`
- `maturity`
- `regime_modifier`
- `session_modifier`

없으면 `capture_context = null`

즉 top action이 execution drag여도, operator는 throughput context를 같은 summary에서 읽을 수 있어야 한다.

## 11. checklist / validation wording guardrail
### 11.1 validation
- summary는 `top_reason`을 그대로 요약하되, capture-aware가 top이 아니면 `capture_context`는 supporting context로만 노출

### 11.2 checklist
- `Operator Action Priority` item은 기존 `priority_level` semantics를 그대로 사용
- capture-aware가 top이어도 `watch`는 `WARN`, `monitor`는 `PASS`

### 11.3 dashboard
- `signal_funnel.operator_action_priority`는 full summary object를 보여주되
- `opportunity_capture` 원본과 서로 다른 역할을 유지한다

## 12. guardrails
이번 derivation rule에서 하지 않는 것:
1. capture-aware priority를 approval block으로 승격
2. `thin_activity_window`를 negative outcome verdict로 해석
3. throughput shortage를 이유로 threshold 자동 완화 제안
4. `blocking_signals`에 capture reason을 넣어 hard block처럼 보이게 만들기
5. family/regime/session modifier가 playbook 또는 execution drag보다 앞서도록 만들기
