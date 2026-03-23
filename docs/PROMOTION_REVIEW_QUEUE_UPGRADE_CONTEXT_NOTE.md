# Promotion Review Queue Upgrade Context Note

최종 갱신: 2026-03-23
상태: Completed

## 1. 왜 이 작업을 하는가
- 현재 시스템은 family별 `promotion_governance`를 읽을 수 있다.
- 하지만 operator는 여전히 여러 family를 놓고 `무엇을 먼저 review해야 하는지`를 직접 정렬해야 한다.
- 이번 라운드 목적은 authority를 더 늘리는 것이 아니라, promotion review 순서를 더 일관된 queue language로 정리하는 것이다.

## 2. 절대 규칙
1. promotion review queue는 compare-only summary여야 한다.
2. approval / sizing / rollout DB는 직접 바꾸지 않는다.
3. thin sample에서는 공격적 promotion review ordering을 만들지 않는다.
4. family는 계속 1차 축이고 condition bucket은 modifier로만 사용한다.
5. urgent control은 여전히 `operator_action_priority`가 우선이고, review queue는 governance ordering만 다룬다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `strategy_lifecycle`
2. `promotion_governance`
3. `positive_evidence_expansion`
4. `capital_allocator`
5. `outcome_bucket_granularity`

아직 약한 것:
1. 여러 family 사이의 promotion review ordering
2. `promotable`과 `defer` family를 한 줄 queue로 읽는 layer
3. governance summary와 operator review 순서의 직접 연결

## 4. 적용 원칙
1. review queue는 `promotion_governance`와 별개다.
2. promotion governance는 family별 review decision, review queue는 cross-family ordering이다.
3. validation / checklist / dashboard / README가 같은 queue language를 써야 한다.

## 4A. Item 1 계약 결론
1. review action은 `promote_review / defer_review / hold_monitor` 셋으로만 고정한다.
2. top-level queue state는 `promotion_ready_queue / defer_first_queue / monitor_only_queue / empty_queue`만 허용한다.
3. 직접 반영 surface는 validation / checklist / dashboard / README만 허용한다.
4. approval / sizing / scanner / candidate row / rollout DB / operator_action_priority hard ordering override는 비범위로 둔다.
5. thin sample, family execution `manual_review` 상태에서는 `promote_review`를 금지한다.

## 4B. Item 2 derivation 결론
1. `promotion_governance`를 primary review decision source로, `strategy_lifecycle`를 posture anchor로 사용한다.
2. review action precedence는 `promote_review -> defer_review -> hold_monitor`로 고정한다.
3. priority rank는 base action rank 위에 lifecycle / positive expansion / allocator support를 소폭 보정하는 방식으로 정한다.
4. `queue_state`는 top row action만으로 `promotion_ready_queue / defer_first_queue / monitor_only_queue / empty_queue`를 판정한다.
5. thin sample, family execution `manual_review`, retired/degraded posture는 promote queue보다 defer/monitor 쪽을 우선하게 만든다.

## 4C. Item 3 patch 결론
1. validation에는 `promotion_review_queue_available`, `promotion_review_queue_summary`, `## Promotion Review Queue`를 추가한다.
2. checklist에는 blocking이 아닌 informational item `Promotion Review Queue`만 추가한다.
3. dashboard에는 `signal_funnel.promotion_review_queue` aggregate summary만 반영한다.
4. README에는 `Promotion Governance` 뒤, `Positive Evidence Expansion` 앞에 cross-family review ordering 설명을 넣는다.
5. approval / candidate row / rollout DB / operator_action_priority hard ordering에는 반영하지 않는다.

## 4D. Item 4 구현 결론
1. `promotion_review_queue.py`를 추가해 `promotion_ready_queue / defer_first_queue / monitor_only_queue / empty_queue`와 `promote_review / defer_review / hold_monitor` queue row를 계산하도록 구현했다.
2. strategy engine은 `promotion_governance`를 primary source로 사용하고, family execution / capital allocator / outcome funnel family row를 fallback/support signal로 묶어 review queue summary를 생성하도록 배선했다.
3. validation report에는 `promotion_review_queue_available`, `promotion_review_queue_summary`, `## Promotion Review Queue` 섹션을 추가했다.
4. operational checklist에는 non-blocking informational item `Promotion Review Queue`를 추가했다.
5. dashboard에는 `signal_funnel.promotion_review_queue` aggregate summary만 반영했고 approval / candidate row / rollout DB / operator_action_priority hard ordering에는 반영하지 않았다.

## 4E. Item 5 테스트 및 문서 동기화 결론
1. `test_promotion_review_queue.py`를 추가해 `promote_review` 우선 정렬과 fallback `defer_review`를 unit test로 고정했다.
2. validation / checklist / dashboard / API smoke 테스트에 `promotion_review_queue` surface 키와 핵심 semantics를 추가했다.
3. README에는 `Promotion Review Queue` 섹션과 operator surface 설명을 추가했다.
4. 이번 라운드의 review queue는 여전히 compare-only queue language이며 approval / sizing / rollout DB authority를 바꾸지 않는다.

## 4F. Item 6 self-check 결론
1. `promotion_review_queue`는 validation / checklist / dashboard / README에만 붙어 있고, approval / sizing / scanner / candidate row / rollout DB에는 번지지 않았다.
2. `promotion_governance`는 family별 review decision, `promotion_review_queue`는 cross-family ordering, `operator_action_priority`는 runtime urgent ordering이라는 역할 분리가 유지된다.
3. thin sample, family execution `manual_review`, degraded posture guardrail이 그대로 살아 있어서 `promote_review`가 과하게 앞서는 회귀는 보이지 않는다.
4. helper unit test와 surface 회귀 테스트, README 동기화까지 끝나 있어 이번 라운드는 여기서 닫아도 된다.
