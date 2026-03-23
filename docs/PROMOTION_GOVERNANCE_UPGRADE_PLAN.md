# Promotion Governance Upgrade Plan

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 작업명
`strategy v2`에 promotion governance 계층 추가

## 2. 배경
- 현재 엔진은 rollout recommendation, strategy lifecycle, positive evidence expansion, capital allocator까지는 갖췄다.
- 하지만 `research -> probation -> production` 승격을 operator가 같은 언어로 읽는 compare-only promotion governance 계층은 아직 없다.
- 지금 필요한 건 rollout policy DB 자동 변경이 아니라, promotion candidate와 hold/defer 이유를 더 명시적으로 정리하는 것이다.

## 3. 목표
1. family 기준 promotion candidate language를 정리한다.
2. lifecycle / rollout / positive evidence / bucket granularity를 promotion review language로 연결한다.
3. 이번 라운드는 `summary + recommendation + operator surface` 중심으로 시작한다.

## 4. 핵심 개선 축
1. Promotion contract
- 어떤 상태와 bias만 허용할지 먼저 고정한다.

2. Promotion derivation
- 같은 입력이면 같은 promotion review 결과가 나오도록 규칙을 정한다.

3. Promotion surface
- validation / checklist / dashboard / README에서 같은 governance language를 쓰게 한다.

## 5. 구현 범위
포함:
1. promotion governance contract / derivation
2. compare-only summary helper
3. validation / checklist / dashboard / README 반영
4. 테스트와 문서 동기화

제외:
1. rollout policy DB 자동 수정
2. approval / sizing source-of-truth 재정의
3. scanner / candidate row authority 변경
4. strategy family 추가

## 6. 완료 기준
1. operator가 family를 `promotable / hold / defer` 언어로 읽을 수 있다.
2. promotion review language가 lifecycle / rollout / expansion / condition split과 충돌하지 않는다.
3. thin sample 및 execution guardrail이 유지된다.

## 7. 예상 산출물
- `PROMOTION_GOVERNANCE_UPGRADE_CONTEXT_NOTE.md`
- `PROMOTION_GOVERNANCE_UPGRADE_CHECKLIST.md`
- `PROMOTION_GOVERNANCE_UPGRADE_CONTRACT.md`
- `PROMOTION_GOVERNANCE_UPGRADE_DERIVATION_RULES.md`
- `PROMOTION_GOVERNANCE_UPGRADE_PATCH_PLAN.md`
- promotion governance summary helper 구현
- promotion governance 테스트 및 README 동기화
- promotion governance 관련 코드 수정
- 회귀 테스트
