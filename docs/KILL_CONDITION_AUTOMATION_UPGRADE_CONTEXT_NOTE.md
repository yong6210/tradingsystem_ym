# Kill Condition Automation Upgrade Context Note

최종 갱신: 2026-03-24
상태: complete

## 1. 왜 이 작업을 하는가
- 지금 시스템은 `문제가 있다`는 evidence는 충분히 만든 상태다.
- 하지만 `그래서 throttle / close-only / kill-switch 중 무엇을 해야 하는가`를 같은 language로 읽는 계층은 없다.
- 이번 라운드 목적은 evidence layer를 actual safety action review language로 연결하는 것이다.

## 2. 절대 규칙
1. first-wave는 `proposal / dry-run / explicit arm`을 기본으로 한다.
2. live stop은 `dry_run=false`만으로는 안 되고 별도 explicit arm이 필요하다.
3. `close_only`와 `kill_switch`는 existing `safety_locks` service를 통해서만 쓴다.
4. manual operator lock과 자동 action은 source와 reason_code를 분리해 추적 가능해야 한다.
5. approval / sizing penalty와 kill condition escalation은 역할을 분리한다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `risk_gate`
2. `safety_locks`
3. `execution_friction_measurement`
4. `a_strategy_post_cost_edge_validation`
5. `forward_stress_regime_validation`
6. `recent_reconciliation_summary`

아직 약한 것:
1. kill-condition proposal summary
2. escalation precedence
3. auto-clear / manual-override boundary

## 4. 적용 원칙
1. evidence layer와 stop authority를 한 단계씩 분리한다.
2. first-wave는 `auto_throttle / close_only / kill_switch`를 곧바로 남발하지 않는다.
3. `execution drag`, `generalization 붕괴`, `reconciliation break`가 동시에 높을 때만 상위 action을 검토한다.
4. system-wide stop은 family-level evidence 하나만으로는 트리거하지 않는다.

## 5. 첫 라운드에서 보고 싶은 것
1. 현재 조건이 throttle review인지 close-only review인지 kill-switch review인지
2. 어떤 axis가 escalation을 만들었는지
3. live write가 막혀 있는지, arm이 켜져 있는지
4. clear condition이 충족됐는지

## 6. 다음 작업
1. metric / derivation rule 정리

## 6A. Item 1 계약 결론
1. first-wave top-level state는 `observe_only / throttle_review / close_only_review / kill_switch_review`로만 고정한다.
2. bias는 `observe_only / propose_throttle / propose_close_only / propose_kill_switch`로만 허용한다.
3. write scope는 `none / proposal_only / armed_live_write`로 분리한다.
4. live write target은 existing `safety_locks.set_close_only`, `safety_locks.set_kill_switch`로만 제한한다.
5. live stop은 `dry_run=false`만으로는 불가능하고 explicit arm이 같이 있어야 한다.

## 6B. Item 2 derivation 결론
1. manual override active 상태는 새 escalation보다 먼저 읽고 `observe_only + write_scope=none`으로 고정한다.
2. single-axis negative는 `throttle_review` 또는 `close_only_review`부터 시작하고, `kill_switch_review`는 multi-axis failure에서만 허용한다.
3. `reconciliation_state == critical`, `risk_gate_state == closed`, `friction_state == degraded`, `generalization_state == insufficient`가 주요 escalation anchor다.
4. `risk_gate api_unhealthy/infra-unhealthy`와 hard reconciliation/friction break가 겹칠 때만 top-level kill-switch review를 허용한다.
5. first-wave는 auto-clear를 구현하지 않고 stop review proposal language만 고정한다.

## 6C. Item 3 patch 결론
1. validation에는 top-level `kill_condition_automation_available`, `kill_condition_automation_summary`, markdown section `## Kill Condition Automation`를 추가하는 방향으로 고정한다.
2. checklist는 informational item `Kill Condition Automation`으로만 반영하고 blocking authority는 만들지 않는다.
3. dashboard는 `signal_funnel.kill_condition_automation` aggregate summary만 허용하고 candidate row나 approval snapshot에는 퍼뜨리지 않는다.
4. live write path는 helper와 분리된 explicit executor wrapper에서만 허용하고, `proposal_only / explicit arm / armed_live_write` 경계를 먼저 고정한다.
5. operator UI는 first-wave에서 existing `Policy / Lock Inspector`를 재사용하고, 새 authority 패널은 구현 후 연결한다.

## 6D. Item 4 구현 결론
1. `kill_condition_automation` helper는 `risk_gate`, `safety_state`, `execution_friction_measurement`, `forward_stress_regime_validation`, `recent_reconciliation_summary`, `execution_degradation_advisory`, `family_execution_degradation_advisory`를 `observe_only / throttle_review / close_only_review / kill_switch_review`로 재압축한다.
2. active manual override가 있으면 `observe_only + write_scope=none + arm_required=false`로 고정해 기존 lock authority와 충돌하지 않게 했다.
3. validation/report/checklist/dashboard까지만 연결했고 scanner / candidate row / approval / sizing / rollout DB는 건드리지 않았다.
4. write scope는 first-wave에서 항상 `proposal_only` 또는 `none`으로만 남겼다.

## 6E. Item 5 테스트/문서 결론
1. helper unit test와 validation/checklist/dashboard/API smoke 회귀로 state, bias, trigger axis, surface key를 고정했다.
2. README에도 `kill_condition_automation`을 operator surface와 validation summary language로 동기화했다.
3. 이번 라운드 검증 기준은 `14 passed` targeted pytest 세트다.

## 6F. Item 6 self-check 결론
1. `kill_condition_automation`는 helper, validation, checklist, dashboard, README, tests, docs에만 있고 scanner / candidate row / approval / sizing / rollout DB로는 번지지 않았다.
2. helper는 proposal-only compare layer로 남아서 accidental live stop risk를 만들지 않는다.
3. 남은 live action은 별도 explicit-arm executor wrapper 단계에서만 열어야 한다.
