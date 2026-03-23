# Promotion Clearance Tracker Upgrade Plan

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 작업명
`strategy v2`에 promotion clearance tracker 계층 추가

## 2. 배경
- 현재 엔진은 `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`까지 갖췄다.
- 하지만 operator는 여전히 `어느 family가 remediation을 실제로 얼마나 해소했는가`를 여러 summary를 다시 합쳐 해석해야 한다.
- 지금 필요한 건 rollout DB 자동 변경이 아니라, remediation 이후 clearance 진척도를 같은 언어로 읽게 만드는 것이다.

## 3. 목표
1. family 기준 promotion clearance tracker를 만든다.
2. remediation active / partial clear / clearance ready 상태를 같은 summary language로 연결한다.
3. 이번 라운드는 `summary + clearance tracker + operator surface` 중심으로 시작한다.

## 4. 핵심 개선 축
1. Clearance tracker contract
- 어떤 clearance state와 review bias만 허용할지 먼저 고정한다.

2. Clearance derivation
- 같은 입력이면 같은 clearance 상태가 나오도록 규칙을 정한다.

3. Clearance surface
- validation / checklist / dashboard / README에서 같은 clearance language를 쓰게 한다.

## 5. 구현 범위
포함:
1. promotion clearance tracker contract / derivation
2. compare-only summary helper
3. validation / checklist / dashboard / README 반영
4. 테스트와 문서 동기화

제외:
1. rollout policy DB 자동 수정
2. approval / sizing source-of-truth 재정의
3. scanner / candidate row authority 변경
4. operator_action_priority hard ordering override

## 6. 완료 기준
1. operator가 family별 remediation clearance 진척도를 같은 language로 읽을 수 있다.
2. clearance tracker가 `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`와 충돌하지 않는다.
3. thin sample 및 execution guardrail이 유지된다.

## 7. 예상 산출물
- `PROMOTION_CLEARANCE_TRACKER_UPGRADE_CONTEXT_NOTE.md`
- `PROMOTION_CLEARANCE_TRACKER_UPGRADE_CHECKLIST.md`
- `PROMOTION_CLEARANCE_TRACKER_UPGRADE_CONTRACT.md`
- `PROMOTION_CLEARANCE_TRACKER_UPGRADE_DERIVATION_RULES.md`
- `PROMOTION_CLEARANCE_TRACKER_UPGRADE_PATCH_PLAN.md`
- clearance tracker contract / derivation / patch 문서
- promotion clearance tracker summary helper 구현
- promotion clearance tracker 관련 코드 수정
- 회귀 테스트
