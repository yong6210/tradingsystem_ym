# Forward Stress Regime Validation Upgrade Plan

최종 갱신: 2026-03-24
상태: complete

## 1. 작업명
`forward / stress / regime split 검증`

## 2. 배경
- 현재 엔진은 `walk_forward`, `strategy_v2_validation`, `strategy_v2_stress_validation`, `strategy_v2_stress_replay_assessment`, `strategy_v2_stress_replay_lineage`를 각각 읽을 수 있다.
- 하지만 operator가 `현재 edge가 forward-like proxy, stress approximation, regime/session split까지 버티는가`를 한 summary로 읽는 언어는 아직 없다.
- 다음 핵심 갭은 `raw validation artifact가 많다`는 문제보다 `generalization confidence`를 같은 운영 언어로 압축하지 못한다는 점이다.

## 3. 목표
1. `walk_forward + stress + regime/session split`을 하나의 generalization verdict로 읽는다.
2. replay lineage / replay replacement readiness를 stress robustness의 별도 context로 정리한다.
3. 이번 라운드는 validate / compare / explain 중심으로 시작하고, approval / rollout / auto-kill authority는 이후 단계로 분리한다.

## 4. 핵심 개선 축
1. Forward/stress/regime validation contract
- 어떤 raw source만 허용하고 어떤 verdict/state만 허용할지 먼저 고정한다.

2. Generalization derivation
- walk-forward, stress degradation, replay lineage readiness, regime/session split fragility를 같은 precedence로 정리한다.

3. Validation/report surface
- validation / checklist / dashboard / README에서 같은 `generalization confidence` 언어를 읽게 만든다.

## 5. 구현 범위
포함:
1. contract / derivation / patch plan 문서
2. forward-stress-regime summary helper
3. validation / checklist / dashboard / README 반영
4. 테스트와 문서 동기화

제외:
1. approval / sizing authority 직접 변경
2. rollout DB 자동 변경
3. scanner / candidate row direct field 추가
4. true market replay runner 자체 구현 변경
5. 새로운 walk-forward 엔진 재설계

## 6. 완료 기준
1. operator가 `current validation evidence가 generalization 측면에서 얼마나 믿을 만한지`를 한 summary로 읽을 수 있다.
2. walk-forward / stress / replay / regime / session 중 어디가 weakest axis인지 같은 layer에서 읽을 수 있다.
3. 기존 approval / promotion / execution authority와 충돌하지 않는다.

## 7. 예상 산출물
- `FORWARD_STRESS_REGIME_VALIDATION_UPGRADE_CONTEXT_NOTE.md`
- `FORWARD_STRESS_REGIME_VALIDATION_UPGRADE_CHECKLIST.md`
- `FORWARD_STRESS_REGIME_VALIDATION_UPGRADE_CONTRACT.md`
- `FORWARD_STRESS_REGIME_VALIDATION_UPGRADE_DERIVATION_RULES.md`
- `FORWARD_STRESS_REGIME_VALIDATION_UPGRADE_PATCH_PLAN.md`
- forward-stress-regime summary 관련 코드
- 관련 회귀 테스트
