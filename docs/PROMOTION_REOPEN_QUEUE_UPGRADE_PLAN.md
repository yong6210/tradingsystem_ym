# Promotion Reopen Queue Upgrade Plan

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 작업명
`strategy v2`에 promotion reopen queue 계층 추가

## 2. 배경
- 현재 엔진은 `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`, `promotion_clearance_tracker`까지 갖췄다.
- 하지만 operator는 여전히 `어느 family의 promotion review를 다시 열어야 하는가`를 여러 summary를 다시 합쳐 해석해야 한다.
- 지금 필요한 건 rollout DB 자동 변경이 아니라, clearance 이후 review re-open ordering을 같은 언어로 읽게 만드는 것이다.

## 3. 목표
1. family 기준 promotion reopen queue를 만든다.
2. `clearance_ready / partial_clear / blocked` 결과를 cross-family re-open ordering language로 연결한다.
3. 이번 라운드는 `summary + reopen queue + operator surface` 중심으로 시작한다.

## 4. 핵심 개선 축
1. Reopen queue contract
- 어떤 reopen action과 queue state만 허용할지 먼저 고정한다.

2. Reopen derivation
- 같은 입력이면 같은 reopen ordering이 나오도록 규칙을 정한다.

3. Reopen surface
- validation / checklist / dashboard / README에서 같은 reopen language를 쓰게 한다.

## 5. 구현 범위
포함:
1. promotion reopen queue contract / derivation
2. compare-only summary helper
3. validation / checklist / dashboard / README 반영
4. 테스트와 문서 동기화

제외:
1. rollout policy DB 자동 수정
2. approval / sizing source-of-truth 재정의
3. scanner / candidate row authority 변경
4. operator_action_priority hard ordering override

## 6. 완료 기준
1. operator가 cross-family review re-open order를 같은 queue language로 읽을 수 있다.
2. reopen queue가 `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`, `promotion_clearance_tracker`와 충돌하지 않는다.
3. thin sample 및 execution guardrail이 유지된다.

## 7. 예상 산출물
- `PROMOTION_REOPEN_QUEUE_UPGRADE_CONTEXT_NOTE.md`
- `PROMOTION_REOPEN_QUEUE_UPGRADE_CHECKLIST.md`
- `PROMOTION_REOPEN_QUEUE_UPGRADE_CONTRACT.md`
- `PROMOTION_REOPEN_QUEUE_UPGRADE_DERIVATION_RULES.md`
- `PROMOTION_REOPEN_QUEUE_UPGRADE_PATCH_PLAN.md`
- reopen queue contract / derivation / patch 문서
- promotion reopen queue summary helper 구현
- promotion reopen queue 관련 코드 수정
- 회귀 테스트
