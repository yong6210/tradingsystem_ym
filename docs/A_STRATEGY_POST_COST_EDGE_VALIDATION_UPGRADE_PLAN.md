# A Strategy Post-Cost Edge Validation Upgrade Plan

최종 갱신: 2026-03-24
상태: complete

## 1. 작업명
`A 전략 post-cost edge 검증`

## 2. 배경
- 현재 엔진은 control, governance, promotion, allocator, operator surface까지 거의 완성형이다.
- 다음 핵심 갭은 `A 전략(sweep_reversal / a_reversal anchor)`이 실제로 after-fee / after-slippage 기준에서도 안정적인 edge를 가지는지 증명하는 것이다.
- 이제 문제는 설계 추가보다 `실제 돈 기준 검증`이다.

## 3. 목표
1. `A 전략`의 post-cost edge를 family / regime / session / condition split 기준으로 읽는다.
2. gross outcome이 아니라 `post-cost EV`, `baseline_cost_profitable_rate`, execution drag까지 포함한 검증 language를 고정한다.
3. 이번 라운드는 validate / explain / compare 중심으로 시작하고, 자동 stop/kill authority는 이후 단계로 분리한다.

## 4. 핵심 개선 축
1. A-strategy validation contract
- 어떤 family를 `A 전략`으로 볼지, 어떤 metric만 허용할지 먼저 고정한다.

2. Post-cost derivation
- fee, slippage, execution drag를 포함한 핵심 지표와 bucket split 규칙을 정리한다.

3. Validation/report surface
- validation / checklist / dashboard / README에서 같은 `A edge` 언어를 읽게 만든다.

## 5. 구현 범위
포함:
1. contract / derivation / patch plan 문서
2. A-strategy post-cost summary helper
3. validation / checklist / dashboard / README 반영
4. 테스트와 문서 동기화

제외:
1. B continuation edge 검증
2. kill condition auto-stop 실행
3. sizing / approval authority 직접 변경
4. live rollout DB 자동 변경

## 6. 완료 기준
1. operator가 `A 전략이 실제 post-cost로 버티는지`를 한 summary로 읽을 수 있다.
2. family / regime / session / cost-condition split에서 취약 구간을 설명할 수 있다.
3. 기존 approval / rollout / allocator authority와 충돌하지 않는다.

## 7. 예상 산출물
- `A_STRATEGY_POST_COST_EDGE_VALIDATION_UPGRADE_CONTEXT_NOTE.md`
- `A_STRATEGY_POST_COST_EDGE_VALIDATION_UPGRADE_CHECKLIST.md`
- `A_STRATEGY_POST_COST_EDGE_VALIDATION_UPGRADE_CONTRACT.md`
- `A_STRATEGY_POST_COST_EDGE_VALIDATION_UPGRADE_DERIVATION_RULES.md`
- `A_STRATEGY_POST_COST_EDGE_VALIDATION_UPGRADE_PATCH_PLAN.md`
- A-strategy post-cost summary 관련 코드
- 관련 회귀 테스트
