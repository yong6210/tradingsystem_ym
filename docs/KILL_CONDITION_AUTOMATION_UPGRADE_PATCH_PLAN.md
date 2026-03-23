# Kill Condition Automation Upgrade Patch Plan

최종 갱신: 2026-03-24

## 1. 목적
- `kill_condition_automation`을 어디에 어떤 wording으로 넣을지 먼저 고정한다.
- 이번 단계는 live stop을 바로 발사하는 것이 아니라 `proposal / dry-run / arm-required` 경계를 먼저 surface에 고정하는 것이다.

## 2. validation report
추가 방향:
1. top-level `kill_condition_automation_available`
2. top-level `kill_condition_automation_summary`
3. markdown section `## Kill Condition Automation`

`kill_condition_automation_summary` 최소 필드:
1. `available`
2. `advisory_only`
3. `kill_condition_state`
4. `automation_bias`
5. `write_scope`
6. `trigger_axis`
7. `active_manual_override`
8. `arm_required`
9. `summary`
10. `reason_codes`
11. `source_summary`

배치 원칙:
1. `Execution Friction Measurement`, `Forward Stress Regime Validation` 뒤에 둔다.
2. raw risk/safety source를 대체하지 않고 stop review verdict로만 읽히게 한다.
3. promotion / allocation / research stack보다 앞에 둔다.

## 3. checklist
추가 방향:
1. informational item `Kill Condition Automation`

원칙:
1. blocking은 금지한다.
2. `throttle_review / close_only_review / kill_switch_review`에서만 `WARN` informational을 허용한다.
3. active manual override는 `PASS informational` 또는 `WARN informational`로만 남기고 새 authority를 만들지 않는다.

## 4. dashboard
추가 방향:
1. `signal_funnel.kill_condition_automation`

원칙:
1. aggregate summary만 허용한다.
2. candidate row, approval snapshot, recent intent row에는 퍼뜨리지 않는다.
3. existing `kill_switch_active`, `close_only_active`, `active_locks`, `new_entries_allowed`는 raw state card로 유지한다.

## 5. live write path
first-wave 원칙:
1. helper는 기본적으로 `proposal_only`
2. live write는 별도 arm이 없으면 금지
3. live write target은 `safety_locks.set_close_only`, `safety_locks.set_kill_switch`만 허용
4. auto-throttle는 first-wave에서 direct write 없이 proposal language로만 남겨도 된다

권장 경로:
1. helper summary 생성
2. explicit executor wrapper에서 `dry_run`, `allow_live_write`, `arm_token/env` 검증
3. 통과 시 `close_only` 또는 `kill_switch` 적용
4. reason code는 `auto_kill_condition_close_only`, `auto_kill_condition_kill_switch`

## 6. README
배치 방향:
1. `Execution Friction Measurement`, `Forward Stress Regime Validation` 뒤
2. `A Strategy Post-Cost Edge Validation`이나 promotion stack보다 앞

핵심 문구:
1. `kill_condition_automation`은 compare-first stop review layer다.
2. single-axis weakness는 throttle/close-only review로만 시작하고, kill-switch는 multi-axis failure에서만 검토한다.
3. live stop은 `explicit arm` 없이는 금지된다.

## 7. operator UI
first-wave:
1. existing `Policy / Lock Inspector` 재사용
2. 새 상세 패널은 helper contract가 구현된 뒤 붙인다.

## 8. 비범위
1. scanner / portfolio candidate row direct stop flag
2. approval direct override
3. sizing direct override
4. rollout DB direct mutation
5. auto-clear / unlock direct execution
