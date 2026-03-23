# Kill Condition Automation Upgrade Derivation Rules

최종 갱신: 2026-03-24
상태: Item 2 baseline fixed

## 1. 목적
- 이 문서는 `kill_condition_automation`이 같은 입력에서 같은 escalation verdict를 내도록 derivation 규칙을 고정한다.
- 첫 라운드 목적은 새로운 risk engine을 만드는 것이 아니라, existing `risk_gate`, `safety_locks`, `execution_friction_measurement`, `forward_stress_regime_validation`, `recent_reconciliation_summary`, `execution_degradation_advisory`를 `proposal-only stop review` 언어로 정리하는 것이다.

## 2. manual override 우선 규칙
1. `safety_state.kill_switch_active == true`면 현재 system은 이미 hard-stopped 상태다.
2. `safety_state.close_only_active == true`면 현재 system은 이미 close-only 상태다.
3. manual/global lock이 이미 active면 `kill_condition_state`는 새 escalation target이 아니라 `observe_only`로 둔다.
4. 이 경우 `active_manual_override=true`, `write_scope=none`, `arm_required=false`로 고정한다.
5. 자동화는 기존 manual lock을 clear, downgrade, replace 하지 않는다.

## 3. trigger axis 정규화
허용 trigger axis:
1. `risk_gate_axis`
2. `friction_axis`
3. `generalization_axis`
4. `reconciliation_axis`
5. `composite_axis`
6. `manual_override_axis`

## 4. 핵심 source 정규화

### 4A. risk gate
1. `risk_gate.state == OPEN` -> `risk_gate_state = open`
2. `risk_gate.state == THROTTLED` -> `risk_gate_state = throttled`
3. `risk_gate.state == CLOSED` -> `risk_gate_state = closed`

`risk_gate_reason`은 그대로 reason code로 유지한다.

### 4B. friction
1. `execution_friction_measurement.friction_state == healthy_friction` -> `friction_state = healthy`
2. `watch_friction` -> `friction_state = watch`
3. `degraded_friction` -> `friction_state = degraded`
4. `insufficient_measurement` -> `friction_state = insufficient`

### 4C. generalization
1. `forward_stress_regime_validation.validation_state == validated_generalization` -> `generalization_state = validated`
2. `fragile_generalization` -> `generalization_state = fragile`
3. `insufficient_generalization` -> `generalization_state = insufficient`
4. `insufficient_evidence` -> `generalization_state = insufficient_evidence`

### 4D. reconciliation
1. `recent_reconciliation_summary.healthy == true` and `critical_count == 0` -> `reconciliation_state = healthy`
2. `degraded == true` or `highest_severity in {WARN, ERROR}` -> `reconciliation_state = degraded`
3. `critical_count > 0` or `lock_required_count > 0` or `highest_severity == CRITICAL` -> `reconciliation_state = critical`

### 4E. execution degradation
1. `execution_degradation_advisory.status == healthy` -> `execution_degradation_state = healthy`
2. `watch` -> `execution_degradation_state = watch`
3. `manual_review` -> `execution_degradation_state = manual_review`

## 5. escalation precedence
우선순위는 아래대로 고정한다.

1. `observe_only`
2. `throttle_review`
3. `close_only_review`
4. `kill_switch_review`

실제 판정은 아래 precedence를 사용한다.

### 5A. observe_only
아래 중 하나면 `observe_only`
1. active manual override가 이미 있음
2. 모든 source가 healthy/open/validated이고 stop review trigger가 없음
3. available source가 너무 적어 escalation evidence를 만들 수 없음

### 5B. throttle_review
`observe_only`가 아니고 아래 중 하나면 `throttle_review`
1. `risk_gate_state == throttled`
2. `friction_state == watch`
3. `generalization_state == fragile`
4. `execution_degradation_state == watch`
5. `generalization_state == insufficient_evidence`

설명:
1. first-wave에서 single-axis fragility는 바로 stop보다 throttle review로 시작한다.
2. `insufficient_evidence`도 aggressive stop이 아니라 confidence throttle 쪽으로만 해석한다.

### 5C. close_only_review
위 둘이 아니고 아래 중 하나면 `close_only_review`
1. `reconciliation_state == critical`
2. `risk_gate_state == closed`
3. `friction_state == degraded`
4. `generalization_state == insufficient`
5. `execution_degradation_state == manual_review`
6. `friction_state == watch` and `generalization_state == fragile`
7. `generalization_state == fragile` and `reconciliation_state == degraded`

설명:
1. hard reconciliation break는 신규 진입 금지 검토를 먼저 만든다.
2. single-source catastrophic proof가 없더라도 `degraded friction`, `insufficient generalization`, `risk_gate closed`는 close-only review로 묶는다.

### 5D. kill_switch_review
위 셋이 아니고 아래 중 하나면 `kill_switch_review`
1. `reconciliation_state == critical` and `risk_gate_state == closed`
2. `reconciliation_state == critical` and `friction_state == degraded`
3. `generalization_state == insufficient` and `friction_state == degraded`
4. `generalization_state == insufficient` and `risk_gate_state == closed`
5. `risk_gate_reason in {api_unhealthy, infra-unhealthy}` and (`reconciliation_state in {degraded, critical}` or `friction_state == degraded`)

설명:
1. kill-switch review는 multi-axis failure에서만 허용한다.
2. single family edge weakness나 single stress failure만으로는 system-wide kill review를 만들지 않는다.

## 6. automation_bias mapping
1. `observe_only` -> `observe_only`
2. `throttle_review` -> `propose_throttle`
3. `close_only_review` -> `propose_close_only`
4. `kill_switch_review` -> `propose_kill_switch`

## 7. write_scope 규칙
1. 기본값은 `proposal_only`
2. active manual override가 있으면 `none`
3. explicit arm이 없으면 live write는 금지
4. explicit arm이 있고 `dry_run=false`일 때만 `armed_live_write`

## 8. trigger_axis 선택 규칙
우선순위는 아래대로 고정한다.
1. `manual_override_axis`
2. `reconciliation_axis`
3. `risk_gate_axis`
4. `friction_axis`
5. `generalization_axis`
6. `composite_axis`

세부:
1. manual override active면 `manual_override_axis`
2. `reconciliation_state == critical`면 `reconciliation_axis`
3. `risk_gate_state == closed`면 `risk_gate_axis`
4. `friction_state == degraded`면 `friction_axis`
5. `generalization_state == insufficient`면 `generalization_axis`
6. 두 개 이상 medium-negative source가 겹치지만 위 단일 우선축이 없으면 `composite_axis`

## 9. reason code 규칙
최소 reason code:
1. `kill_condition:{kill_condition_state}`
2. `risk_gate:{risk_gate_state}`
3. `friction:{friction_state}`
4. `generalization:{generalization_state}`
5. `reconciliation:{reconciliation_state}`
6. `execution_degradation:{execution_degradation_state}`

조건부 reason code:
1. `manual_override:kill_switch_active`
2. `manual_override:close_only_active`
3. `risk_gate_reason:{reason}`
4. `friction_axis:{weakest_axis}`
5. `generalization_axis:{weakest_axis}`

## 10. wording 규칙
1. `observe_only`
- “Current stop evidence does not justify automatic escalation beyond observation.”

2. `throttle_review`
- “Current evidence justifies throttle review, but not close-only or kill-switch escalation.”

3. `close_only_review`
- “Current evidence is weak enough that close-only review should happen before new entries continue.”

4. `kill_switch_review`
- “Multiple hard-failure axes are aligned; kill-switch review is justified before trusting live operation.”

## 11. non-goal
1. 이 단계는 first-wave에서 immediate auto-clear를 구현하지 않는다.
2. scanner / candidate row / approval snapshot으로 stop verdict를 퍼뜨리지 않는다.
3. family-level A/B evidence 하나만으로 system-wide stop을 만들지 않는다.
