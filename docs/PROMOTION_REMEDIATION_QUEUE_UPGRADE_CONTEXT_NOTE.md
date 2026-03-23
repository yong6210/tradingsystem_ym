# Promotion Remediation Queue Upgrade Context Note

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 왜 이 작업을 하는가
- 현재 시스템은 family별 `promotion_governance`와 cross-family `promotion_review_queue`를 읽을 수 있다.
- 하지만 operator는 여전히 여러 family를 놓고 `무엇을 먼저 고쳐야 promotion review가 다시 열리는지`를 직접 해석해야 한다.
- 이번 라운드 목적은 authority를 더 늘리는 것이 아니라, promotion remediation 순서를 더 일관된 queue language로 정리하는 것이다.

## 2. 절대 규칙
1. promotion remediation queue는 compare-only summary여야 한다.
2. approval / sizing / rollout DB는 직접 바꾸지 않는다.
3. thin sample에서는 공격적 remediation wording 대신 `observe` 계열만 허용한다.
4. family는 계속 1차 축이고 condition bucket은 modifier로만 사용한다.
5. urgent control은 여전히 `operator_action_priority`가 우선이고, remediation queue는 governance remediation ordering만 다룬다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `strategy_lifecycle`
2. `promotion_governance`
3. `promotion_review_queue`
4. `positive_evidence_expansion`
5. `capital_allocator`
6. `outcome_bucket_granularity`
7. `alpha_research` promotion guardrails

아직 약한 것:
1. 여러 family 사이의 promotion remediation ordering
2. `defer` family를 어떤 remediation bucket으로 먼저 봐야 하는지에 대한 공통 언어
3. governance summary와 remediation action ordering의 직접 연결

## 4. 적용 원칙
1. remediation queue는 `promotion_review_queue`와 별개다.
2. promotion review queue는 cross-family review ordering, remediation queue는 cross-family guardrail clearing ordering이다.
3. validation / checklist / dashboard / README가 같은 remediation language를 써야 한다.

## 4A. Item 1 계약 결론
1. remediation action은 `execution_remediation / policy_remediation / condition_remediation / observe_guardrail`로만 고정한다.
2. top-level queue state는 `execution_first_queue / policy_first_queue / condition_first_queue / observe_only_queue / empty_queue`만 허용한다.
3. 직접 반영 surface는 validation / checklist / dashboard / README만 허용한다.
4. approval / sizing / scanner / candidate row / rollout DB / operator_action_priority hard ordering override는 비범위로 둔다.
5. thin sample에서는 active remediation action 대신 `observe_guardrail`까지만 허용하고, family execution `manual_review`는 `execution_remediation` 우선으로 제한한다.

## 4B. Item 2 derivation 결론
1. `promotion_governance`를 primary remediation context source로, `promotion_review_queue`를 cross-family ordering anchor로 사용한다.
2. remediation action precedence는 `execution_remediation -> policy_remediation -> condition_remediation -> observe_guardrail`로 고정한다.
3. thin sample은 어떤 경우에도 active remediation queue로 올리지 않고 `observe_guardrail`로만 남긴다.
4. family execution `manual_review`와 family-targeted execution guardrail은 `execution_remediation`을 policy/condition보다 우선하게 만든다.
5. rollout `reduce/research_only`, lifecycle `degraded/retired`는 `policy_remediation`으로, condition drag는 `condition_remediation`으로 정리하되 allocator와 alpha research는 support-only modifier로만 사용한다.

## 4C. Item 3 patch 결론
1. validation에는 `promotion_remediation_queue_available`, `promotion_remediation_queue_summary`, `## Promotion Remediation Queue`를 추가한다.
2. checklist에는 blocking이 아닌 informational item `Promotion Remediation Queue`만 추가한다.
3. dashboard에는 `signal_funnel.promotion_remediation_queue` aggregate summary만 반영한다.
4. README에는 `Promotion Review Queue` 뒤, `Positive Evidence Expansion` 앞에 cross-family guardrail clearing ordering 설명을 넣는다.
5. approval / candidate row / rollout DB / operator_action_priority hard ordering에는 반영하지 않는다.

## 4D. Item 4 구현 결론
1. `promotion_remediation_queue.py`를 추가해 `execution_first_queue / policy_first_queue / condition_first_queue / observe_only_queue / empty_queue`와 `execution_remediation / policy_remediation / condition_remediation / observe_guardrail` row를 계산하도록 구현했다.
2. strategy engine은 `promotion_governance`를 primary context로, `promotion_review_queue`를 ordering anchor로, family execution / rollout / lifecycle / condition drag / alpha research family guardrail을 support signal로 묶어 remediation queue summary를 생성하도록 배선했다.
3. validation report에는 `promotion_remediation_queue_available`, `promotion_remediation_queue_summary`, `## Promotion Remediation Queue` 섹션을 추가했다.
4. operational checklist에는 non-blocking informational item `Promotion Remediation Queue`를 추가했다.
5. dashboard에는 `signal_funnel.promotion_remediation_queue` aggregate summary만 반영했고 approval / candidate row / rollout DB / operator_action_priority hard ordering에는 반영하지 않았다.

## 4E. Item 5 테스트 및 문서 동기화 결론
1. `test_promotion_remediation_queue.py`를 추가해 `execution_remediation` 우선순위와 `condition_remediation` fallback ordering을 helper 단위 테스트로 고정했다.
2. validation / checklist / dashboard / API smoke 테스트에 `promotion_remediation_queue` 키와 핵심 semantics를 추가해 surface 계약을 고정했다.
3. README에 `Promotion Remediation Queue` 섹션을 추가하고, `promotion_governance -> promotion_review_queue -> promotion_remediation_queue` 역할 분리를 operator surface 설명까지 반영했다.
4. 이번 계층이 compare-only governance remediation ordering이라는 경계도 README와 테스트 양쪽에서 같이 못 박았다.

## 4F. Item 6 self-check 결론
1. `promotion_remediation_queue`는 validation / checklist / dashboard / README에만 additive로 붙어 있고, approval / sizing / scanner / candidate row / rollout DB / operator_action_priority hard ordering으로는 번지지 않았다.
2. `promotion_governance`는 family별 review decision, `promotion_review_queue`는 cross-family review ordering, `promotion_remediation_queue`는 cross-family guardrail-clearing ordering이라는 역할 분리가 유지된다.
3. thin sample, family execution `manual_review`, degraded posture guardrail도 그대로 살아 있어서 공격적 remediation wording이 기존 방어 규칙을 덮지 않는다.
4. helper unit test, surface 회귀, README 동기화까지 끝난 상태라 이번 라운드 범위 안에서 추가 수정이 필요한 충돌은 보이지 않는다.
