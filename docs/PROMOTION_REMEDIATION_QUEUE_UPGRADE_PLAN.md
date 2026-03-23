# Promotion Remediation Queue Upgrade Plan

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 작업명
`strategy v2`에 promotion remediation queue 계층 추가

## 2. 배경
- 현재 엔진은 `promotion_governance`와 `promotion_review_queue`까지 갖췄다.
- 하지만 operator는 여전히 `어떤 family를 먼저 승격 검토해야 하는가`는 읽을 수 있어도, `그 family를 위해 어떤 guardrail을 먼저 풀어야 하는가`는 여러 surface를 다시 합쳐 해석해야 한다.
- 지금 필요한 건 rollout DB 자동 변경이 아니라, defer/promotable family의 remediation 순서를 같은 언어로 정리하는 것이다.

## 3. 목표
1. family 기준 promotion remediation queue를 만든다.
2. `defer cause / guardrail cause / observe` 결과를 remediation ordering language로 연결한다.
3. 이번 라운드는 `summary + remediation queue + operator surface` 중심으로 시작한다.

## 4. 핵심 개선 축
1. Remediation queue contract
- 어떤 remediation action과 queue state만 허용할지 먼저 고정한다.

2. Remediation derivation
- 같은 입력이면 같은 remediation ordering이 나오도록 규칙을 정한다.

3. Remediation surface
- validation / checklist / dashboard / README에서 같은 remediation language를 쓰게 한다.

## 5. 구현 범위
포함:
1. promotion remediation queue contract / derivation
2. compare-only summary helper
3. validation / checklist / dashboard / README 반영
4. 테스트와 문서 동기화

제외:
1. rollout policy DB 자동 수정
2. approval / sizing source-of-truth 재정의
3. scanner / candidate row authority 변경
4. operator_action_priority hard ordering override

## 6. 완료 기준
1. operator가 family remediation order를 같은 queue language로 읽을 수 있다.
2. remediation queue가 `promotion_governance`, `promotion_review_queue`, `operator_action_priority`와 충돌하지 않는다.
3. thin sample 및 execution guardrail이 유지된다.

## 7. 예상 산출물
- `PROMOTION_REMEDIATION_QUEUE_UPGRADE_CONTEXT_NOTE.md`
- `PROMOTION_REMEDIATION_QUEUE_UPGRADE_CHECKLIST.md`
- `PROMOTION_REMEDIATION_QUEUE_UPGRADE_CONTRACT.md`
- `PROMOTION_REMEDIATION_QUEUE_UPGRADE_DERIVATION_RULES.md`
- `PROMOTION_REMEDIATION_QUEUE_UPGRADE_PATCH_PLAN.md`
- remediation queue contract / derivation / patch 문서
- promotion remediation queue summary helper 구현
- promotion remediation queue 관련 코드 수정
- 회귀 테스트
