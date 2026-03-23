# Strategy Lifecycle Upgrade Plan

최종 갱신: 2026-03-23
상태: All checklist items completed

## 1. 작업명
`strategy v2`에 strategy lifecycle 관리 계층 추가

## 2. 배경
- 현재 시스템은 outcome-first control loop, rollout recommendation, opportunity capture, capital allocator까지 연결됐다.
- 하지만 `research -> probation -> production -> degraded -> retired` 같은 명시적 전략 생애주기 계층은 아직 없다.
- 그래서 좋은 family가 언제 승격 가능한지, 나빠진 family가 언제 downgrade/retire 대상인지가 여러 surface에 흩어져 있다.

## 3. 목표
1. family 중심 strategy lifecycle state를 정의한다.
2. alpha research / rollout recommendation / execution degradation / post-cost outcome을 같은 lifecycle 언어로 묶는다.
3. 이번 라운드는 lifecycle state와 recommendation layer를 먼저 추가하고, DB 자동 mutation은 하지 않는다.

## 4. 핵심 개선 축
1. Lifecycle contract
- `research`, `probation`, `production`, `degraded`, `retired` 상태와 전이 조건을 정규화한다.

2. Runtime integration
- validation / checklist / dashboard / rollout review에서 lifecycle state를 같은 summary object로 읽게 한다.

3. Promotion governance
- `alpha_research -> probation -> production` 승격 기준과
  `production -> degraded -> retired` 하향 기준을 정리한다.

## 5. 구현 범위
포함:
1. lifecycle contract / derivation
2. lifecycle summary helper
3. validation/checklist/dashboard surface 반영
4. 테스트와 README 동기화

제외:
1. strategy family 신규 추가
2. rollout policy DB 자동 수정
3. approval hard block 재정의
4. allocator/sizing formula 재정의

## 6. 완료 기준
1. operator가 family별 현재 lifecycle state를 한 눈에 읽을 수 있다.
2. promotion / downgrade / retire recommendation이 alpha research, rollout, degradation과 충돌하지 않는다.
3. lifecycle state가 authority 경계를 넘지 않고 compare-only/operator-review layer로 유지된다.

## 7. 예상 산출물
- `STRATEGY_LIFECYCLE_UPGRADE_CONTEXT_NOTE.md`
- `STRATEGY_LIFECYCLE_UPGRADE_CHECKLIST.md`
- `STRATEGY_LIFECYCLE_UPGRADE_CONTRACT.md`
- `STRATEGY_LIFECYCLE_UPGRADE_DERIVATION_RULES.md`
- `STRATEGY_LIFECYCLE_UPGRADE_PATCH_PLAN.md`
- lifecycle contract / derivation / patch plan 문서
- lifecycle summary 관련 코드 수정
- 회귀 테스트
- README lifecycle section 동기화
