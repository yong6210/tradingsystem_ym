# Kill Condition Automation Upgrade Plan

최종 갱신: 2026-03-24
상태: complete

## 1. 작업명
`kill condition 자동화`

## 2. 배경
- 현재 엔진은 `risk_gate`, `safety_locks`, `execution_friction_measurement`, `a_strategy_post_cost_edge_validation`, `forward_stress_regime_validation`, `recent_reconciliation_summary`를 각각 읽을 수 있다.
- 하지만 이 evidence를 `auto_throttle / close_only / kill_switch` 같은 kill-condition action language로 번역하는 공통 계층은 아직 없다.
- 다음 핵심 갭은 `문제가 보인다`와 `무엇을 자동으로 막아야 하는가` 사이를 연결하지 못한다는 점이다.

## 3. 목표
1. execution drag, generalization 붕괴, reconciliation break, repeated guardrail failure를 같은 kill-condition review language로 묶는다.
2. first-wave는 `proposal / dry-run / explicit arm` 중심으로 시작하고, live authority는 단계적으로 연다.
3. `close_only -> kill_switch` escalation 순서와 해제 조건을 같은 contract로 읽게 만든다.

## 4. 핵심 개선 축
1. Kill-condition contract
- 어떤 source만 읽고 어떤 action/state만 허용할지 먼저 고정한다.

2. Escalation derivation
- throttle, close-only, kill-switch로 올라가는 precedence와 clear 조건을 정리한다.

3. Safe write path
- proposal-only, dry-run, explicit arm, live write를 분리한다.

## 5. 구현 범위
포함:
1. contract / derivation / patch plan 문서
2. kill condition proposal/summary helper
3. validation / checklist / dashboard / README 반영
4. 필요 시 explicit-arm 기반 live write path
5. 테스트와 문서 동기화

제외:
1. approval / sizing 로직 전체 재설계
2. 새로운 alert transport 자체 구현
3. 브로커 라우팅 / 주문 엔진 자체 변경
4. 임의 family별 bespoke stop logic 추가

## 6. 완료 기준
1. operator가 `왜 throttle/close-only/kill-switch가 필요한지`를 한 summary로 읽을 수 있다.
2. proposal-only와 live action이 분리되어 accidental stop risk가 없다.
3. 기존 manual safety control과 충돌하지 않는다.

## 7. 예상 산출물
- `KILL_CONDITION_AUTOMATION_UPGRADE_CONTEXT_NOTE.md`
- `KILL_CONDITION_AUTOMATION_UPGRADE_CHECKLIST.md`
- `KILL_CONDITION_AUTOMATION_UPGRADE_CONTRACT.md`
- `KILL_CONDITION_AUTOMATION_UPGRADE_DERIVATION_RULES.md`
- `KILL_CONDITION_AUTOMATION_UPGRADE_PATCH_PLAN.md`
- kill condition summary / automation 관련 코드
- 관련 회귀 테스트
