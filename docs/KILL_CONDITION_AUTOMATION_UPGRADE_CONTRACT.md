# Kill Condition Automation Upgrade Contract

최종 갱신: 2026-03-24

## 1. 목적
- `kill_condition_automation`은 existing evidence layer를 `auto_throttle / close_only / kill_switch` review language로 번역하는 compare-first control layer다.
- first-wave는 live safety authority를 바로 열지 않고 `proposal / dry-run / explicit arm` 경계를 먼저 고정한다.

## 2. Raw Source Contract
허용 raw/direct source:
1. `execution_friction_measurement`
2. `forward_stress_regime_validation`
3. `recent_reconciliation_summary`
4. `execution_degradation_advisory`
5. `family_execution_degradation_advisory`
6. `risk_gate`
7. `safety_state`

support-only context:
1. `a_strategy_post_cost_edge_validation`
2. `b_continuation_edge_validation`
3. `outcome_control_trace`
4. `rollout_recommendation`
5. `strategy_lifecycle`

비범위:
1. scanner row direct stop flag
2. portfolio candidate row direct stop flag
3. approval/sizing direct override
4. rollout DB direct mutation without explicit arm

## 3. Verdict State Contract
허용 top-level state:
1. `observe_only`
2. `throttle_review`
3. `close_only_review`
4. `kill_switch_review`

허용 bias:
1. `observe_only`
2. `propose_throttle`
3. `propose_close_only`
4. `propose_kill_switch`

허용 write scope:
1. `none`
2. `proposal_only`
3. `armed_live_write`

## 4. Action Contract
- `auto_throttle`
  - 의미: runtime new-entry confidence를 낮추고 size/review pressure를 높이는 first escalation
- `close_only`
  - 의미: 신규 진입 금지, existing position 관리만 허용
- `kill_switch`
  - 의미: system-wide 신규 실행 완전 중단

first-wave에서 허용되는 실제 write target:
1. `safety_locks.set_close_only(...)`
2. `safety_locks.set_kill_switch(...)`

`auto_throttle`는 first-wave에서 compare/proposal language로만 시작해도 된다.

## 5. Manual Override Contract
1. manual lock이 이미 active면 자동 action은 같은 domain에서 downgrade나 clear를 직접 실행하지 않는다.
2. auto action은 reason code에 `auto_kill_condition_*` prefix를 사용한다.
3. clear/unset은 first-wave에서 수동 해제 또는 별도 explicit clear rule로만 허용한다.

## 6. Safety Boundary
1. `dry_run=false`만으로는 live write가 일어나면 안 된다.
2. live write는 `explicit arm`이 켜져 있을 때만 허용한다.
3. first-wave dashboard / validation / checklist / README는 `proposal-only` 상태를 기본으로 노출한다.
4. operator UI는 existing policy/lock inspector를 재사용하되 새 authority wording은 contract 고정 후 연결한다.

## 7. Surface Contract
직접 반영 surface:
1. validation
2. checklist
3. dashboard
4. README

후순위 surface:
1. operator UI
2. notifier / session brief

비범위 surface:
1. scanner
2. candidate row
3. approval snapshot
4. portfolio budget direct stop field

## 8. Summary Payload Minimum Fields
1. `available`
2. `advisory_only`
3. `kill_condition_state`
4. `automation_bias`
5. `write_scope`
6. `trigger_axis`
7. `trigger_reason_codes`
8. `active_manual_override`
9. `arm_required`
10. `summary`
11. `source_summary`

## 9. Acceptance Boundary
1. 이번 라운드는 `왜 stop review가 필요한가`를 설명할 수 있어야 한다.
2. accidental live stop risk가 없어야 한다.
3. manual operator control과 source-of-truth 충돌이 없어야 한다.
