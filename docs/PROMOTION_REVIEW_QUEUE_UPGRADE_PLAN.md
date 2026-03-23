# Promotion Review Queue Upgrade Plan

최종 갱신: 2026-03-23
상태: Completed

## 1. 작업명
`strategy v2`에 promotion review queue 계층 추가

## 2. 배경
- 현재 엔진은 `strategy_lifecycle`, `promotion_governance`, `positive_evidence_expansion`까지 갖췄다.
- 하지만 여러 family 중 `어떤 family를 먼저 승격 검토해야 하는가`, `어떤 family는 먼저 defer 원인을 봐야 하는가`를 queue 언어로 읽는 계층은 아직 없다.
- 지금 필요한 건 rollout DB 자동 변경이 아니라, operator review 순서를 family 기준으로 더 명확히 정리하는 것이다.

## 3. 목표
1. family 기준 promotion review queue를 만든다.
2. `promotable / hold / defer` 결과를 review ordering language로 연결한다.
3. 이번 라운드는 `summary + queue + operator surface` 중심으로 시작한다.

## 4. 핵심 개선 축
1. Review queue contract
- 어떤 queue state와 priority만 허용할지 먼저 고정한다.

2. Review queue derivation
- 같은 입력이면 같은 review ordering이 나오도록 규칙을 정한다.

3. Review queue surface
- validation / checklist / dashboard / README에서 같은 queue language를 쓰게 한다.

## 5. 구현 범위
포함:
1. promotion review queue contract / derivation
2. compare-only summary helper
3. validation / checklist / dashboard / README 반영
4. 테스트와 문서 동기화

제외:
1. rollout policy DB 자동 수정
2. approval / sizing source-of-truth 재정의
3. scanner / candidate row authority 변경
4. operator_action_priority hard ordering override

## 6. 완료 기준
1. operator가 family review order를 `promote_review / defer_review / hold_monitor` 언어로 읽을 수 있다.
2. review queue가 `promotion_governance`, `strategy_lifecycle`, `positive_evidence_expansion`과 충돌하지 않는다.
3. thin sample 및 execution guardrail이 유지된다.

## 7. 예상 산출물
- `PROMOTION_REVIEW_QUEUE_UPGRADE_CONTEXT_NOTE.md`
- `PROMOTION_REVIEW_QUEUE_UPGRADE_CHECKLIST.md`
- `PROMOTION_REVIEW_QUEUE_UPGRADE_CONTRACT.md`
- `PROMOTION_REVIEW_QUEUE_UPGRADE_DERIVATION_RULES.md`
- `PROMOTION_REVIEW_QUEUE_UPGRADE_PATCH_PLAN.md`
- promotion review queue summary helper 구현
- review queue contract / derivation / patch 문서
- promotion review queue 관련 코드 수정
- 회귀 테스트
