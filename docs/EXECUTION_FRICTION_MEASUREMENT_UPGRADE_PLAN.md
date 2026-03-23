# Execution Friction Measurement Upgrade Plan

최종 갱신: 2026-03-24
상태: complete

## 1. 작업명
`execution friction 실측`

## 2. 배경
- 현재 엔진은 `execution_quality`, `recent_reconciliation_summary`, `strategy_v2_stress_validation`, approval의 `expected_fee_bps / max_slippage_bps`를 각각 읽을 수 있다.
- 하지만 실제 체결 품질이 post-cost edge를 얼마나 훼손하는지, friction이 `watch` 수준인지 `degraded` 수준인지, 현재 실측이 충분한지까지를 한 summary로 읽는 language는 아직 없다.
- 다음 핵심 갭은 `좋은 전략처럼 보인다`와 `실제로 체결 friction을 버틴다`를 분리해서 읽는 것이다.

## 3. 목표
1. fill-rate, slippage, latency, fee, reconciliation을 같은 `execution friction evidence` language로 묶는다.
2. 실측 기반 friction verdict와 stress-cost context를 함께 읽어, post-cost edge 검증의 현실성을 올린다.
3. 이번 라운드는 validate / compare / explain 중심으로 시작하고, auto-throttle / auto-stop authority는 이후 단계로 분리한다.

## 4. 핵심 개선 축
1. execution friction measurement contract
- 어떤 metric만 허용할지, 어떤 상태만 surface에 노출할지 먼저 고정한다.

2. friction derivation
- fill conversion, slippage, latency, fee drag, reconciliation integrity, measurement coverage 해석 규칙을 정리한다.

3. validation/report surface
- validation / checklist / dashboard / README에서 같은 `execution_friction_measurement` language를 읽게 만든다.

## 5. 구현 범위
포함:
1. contract / derivation / patch plan 문서
2. execution friction measurement helper
3. validation / checklist / dashboard / README 반영
4. 테스트와 문서 동기화

제외:
1. auto-throttle / auto-stop authority 직접 변경
2. approval / sizing / rollout DB 직접 변경
3. kill condition 자동 실행
4. live order routing logic 변경

## 6. 완료 기준
1. operator가 현재 execution drag를 한 summary로 읽을 수 있다.
2. fill-rate / slippage / latency / fee / reconciliation / coverage를 같은 evidence layer에서 읽을 수 있다.
3. 기존 approval / sizing / rollout authority와 충돌하지 않는다.

## 7. 예상 산출물
- `EXECUTION_FRICTION_MEASUREMENT_UPGRADE_CONTEXT_NOTE.md`
- `EXECUTION_FRICTION_MEASUREMENT_UPGRADE_CHECKLIST.md`
- `EXECUTION_FRICTION_MEASUREMENT_UPGRADE_CONTRACT.md`
- `EXECUTION_FRICTION_MEASUREMENT_UPGRADE_DERIVATION_RULES.md`
- `EXECUTION_FRICTION_MEASUREMENT_UPGRADE_PATCH_PLAN.md`
- execution friction measurement 관련 코드
- 관련 회귀 테스트
