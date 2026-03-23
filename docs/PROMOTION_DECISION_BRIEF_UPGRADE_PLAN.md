# Promotion Decision Brief Upgrade Plan

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 작업명
`strategy v2`에 promotion decision brief 계층 추가

## 2. 배경
- 현재 엔진은 `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`, `promotion_clearance_tracker`, `promotion_reopen_queue`까지 갖췄다.
- 하지만 operator는 여전히 `지금 이 family를 왜 다시 검토해야 하는가`, `무엇이 아직 남아 있는가`, `다음 review posture가 무엇인가`를 여러 summary를 다시 합쳐 읽어야 한다.
- 지금 필요한 건 새 authority가 아니라, review/reopen/remediation/clearance 결과를 한 family 중심 decision brief로 압축하는 compare-only layer다.

## 3. 목표
1. headline family 기준 promotion decision brief를 만든다.
2. `governance -> review queue -> remediation -> clearance -> reopen` 흐름을 한 문장/한 객체로 읽게 만든다.
3. 이번 라운드는 `summary + operator brief + surface wording` 중심으로 시작한다.

## 4. 핵심 개선 축
1. Decision brief contract
- 어떤 brief field와 decision language만 허용할지 먼저 고정한다.

2. Decision brief derivation
- 같은 입력이면 같은 family brief가 나오도록 precedence를 정한다.

3. Decision brief surface
- validation / checklist / dashboard / README에서 같은 decision brief language를 쓰게 한다.

## 5. 구현 범위
포함:
1. promotion decision brief contract / derivation
2. compare-only summary helper
3. validation / checklist / dashboard / README 반영
4. 테스트와 문서 동기화

제외:
1. rollout policy DB 자동 수정
2. approval / sizing source-of-truth 재정의
3. scanner / candidate row authority 변경
4. operator_action_priority hard ordering override

## 6. 완료 기준
1. operator가 top family에 대한 promotion case를 한 brief language로 읽을 수 있다.
2. decision brief가 `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`, `promotion_clearance_tracker`, `promotion_reopen_queue`와 충돌하지 않는다.
3. thin sample 및 execution guardrail이 유지된다.

## 7. 예상 산출물
- `PROMOTION_DECISION_BRIEF_UPGRADE_CONTEXT_NOTE.md`
- `PROMOTION_DECISION_BRIEF_UPGRADE_CHECKLIST.md`
- `PROMOTION_DECISION_BRIEF_UPGRADE_CONTRACT.md`
- `PROMOTION_DECISION_BRIEF_UPGRADE_DERIVATION_RULES.md`
- `PROMOTION_DECISION_BRIEF_UPGRADE_PATCH_PLAN.md`
- promotion decision brief contract / derivation / patch 문서
- promotion decision brief summary helper 구현
- promotion decision brief 관련 코드 수정
- 회귀 테스트
