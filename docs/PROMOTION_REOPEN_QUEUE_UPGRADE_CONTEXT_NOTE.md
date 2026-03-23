# Promotion Reopen Queue Upgrade Context Note

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 왜 이 작업을 하는가
- 현재 시스템은 family별 `promotion_governance`, cross-family `promotion_review_queue`, cross-family `promotion_remediation_queue`, family별 `promotion_clearance_tracker`를 읽을 수 있다.
- 하지만 operator는 여전히 여러 family를 놓고 `어느 family의 promotion review를 다시 열어야 하는가`를 직접 추론해야 한다.
- 이번 라운드 목적은 authority를 더 늘리는 것이 아니라, promotion review re-open ordering을 더 일관된 queue language로 정리하는 것이다.

## 2. 절대 규칙
1. promotion reopen queue는 compare-only summary여야 한다.
2. approval / sizing / rollout DB는 직접 바꾸지 않는다.
3. thin sample에서는 공격적 reopen wording 대신 `observe` 계열만 허용한다.
4. family는 계속 1차 축이고 condition bucket은 modifier로만 사용한다.
5. urgent control은 여전히 `operator_action_priority`가 우선이고, reopen queue는 governance review re-open ordering만 다룬다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `strategy_lifecycle`
2. `promotion_governance`
3. `promotion_review_queue`
4. `promotion_remediation_queue`
5. `promotion_clearance_tracker`
6. `positive_evidence_expansion`
7. `capital_allocator`

아직 약한 것:
1. 여러 family 사이의 promotion review re-open ordering
2. `clearance_ready / partial_clear / blocked`를 같은 reopen queue language로 읽는 공통 언어
3. family clearance progress와 review re-open order의 직접 연결

## 4. 적용 원칙
1. reopen queue는 `promotion_clearance_tracker`와 별개다.
2. clearance tracker는 family별 progress tracking, reopen queue는 cross-family review re-open ordering이다.
3. validation / checklist / dashboard / README가 같은 reopen language를 써야 한다.

## 4A. Item 1 계약 결론
1. reopen action은 `reopen_review / continue_clearance / observe_reopen`로만 고정한다.
2. top-level queue state는 `reopen_ready_queue / clearance_first_queue / observe_only_queue / empty_queue`만 허용한다.
3. 직접 입력 source는 `promotion_governance / promotion_review_queue / promotion_remediation_queue / promotion_clearance_tracker / strategy_lifecycle / positive_evidence_expansion / capital_allocator / family_execution_degradation_advisory`로 제한한다.
4. 직접 반영 surface는 validation / checklist / dashboard / README만 허용하고, approval / sizing / scanner / candidate row / rollout DB / operator_action_priority hard ordering override는 비범위로 둔다.
5. thin sample, family execution `manual_review`, `promotion_clearance_tracker.clearance_state == blocked`는 `reopen_review` 금지 guardrail로 계약에 고정한다.

## 4B. Item 2 derivation 결론
1. `promotion_clearance_tracker`를 primary re-open readiness source로, `promotion_governance`를 family posture anchor로, `promotion_review_queue`와 `promotion_remediation_queue`를 ordering/context source로 사용한다.
2. family universe는 clearance tracker / review queue / remediation queue / governance / lifecycle / positive expansion / allocator family들의 합집합으로 만든다.
3. thin sample 또는 `observe_only`는 `observe_reopen`, `clearance_ready + no manual_review + no active remediation`는 `reopen_review`, 그 외는 `continue_clearance`로 고정한다.
4. `positive_evidence_expansion`과 `capital_allocator`는 `reopen_review` confidence와 ordering을 보조하는 support-only positive modifier로만 사용한다.
5. `manual_review`, active remediation, blocked/partial clearance는 `continue_clearance` 쪽을 먼저 만들고, `reopen_review`는 현재 guardrail 압력이 비활성일 때만 허용한다.

## 4C. Item 3 patch 결론
1. validation에는 `promotion_reopen_queue_available`, `promotion_reopen_queue_summary`, `## Promotion Reopen Queue`를 추가한다.
2. checklist에는 blocking이 아닌 informational item `Promotion Reopen Queue`만 추가한다.
3. dashboard에는 `signal_funnel.promotion_reopen_queue` aggregate summary만 반영한다.
4. README에는 `Promotion Clearance Tracker` 뒤, `Positive Evidence Expansion` 앞에 cross-family review re-open ordering 설명을 넣는다.
5. approval / candidate row / rollout DB / operator_action_priority hard ordering에는 반영하지 않는다.

## 4D. Item 4 구현 결론
1. `promotion_reopen_queue.py`를 추가해 `reopen_review / continue_clearance / observe_reopen` queue summary를 실제로 계산하게 했다.
2. `strategy_engine`는 `promotion_governance / promotion_review_queue / promotion_remediation_queue / promotion_clearance_tracker`를 묶어 reopen summary를 validation 과 dashboard 경로에 공통 배선한다.
3. validation report는 `promotion_reopen_queue_available`, `promotion_reopen_queue_summary`, `## Promotion Reopen Queue`를 같은 wording으로 노출한다.
4. checklist는 새 informational item `Promotion Reopen Queue`를 추가하고, dashboard는 `signal_funnel.promotion_reopen_queue` aggregate summary만 보여준다.
5. approval / sizing / scanner / candidate row / rollout DB / operator_action_priority hard ordering은 그대로 비범위로 유지한다.

## 4E. Item 5 테스트 / 문서 결론
1. `test_promotion_reopen_queue.py`로 `reopen_review`와 `continue_clearance` guardrail precedence를 직접 고정한다.
2. validation / checklist / dashboard / API smoke는 `promotion_reopen_queue_available`, `promotion_reopen_queue_summary`, `signal_funnel.promotion_reopen_queue` 계약을 같은 wording으로 검증한다.
3. README는 `Promotion Clearance Tracker` 뒤에 `Promotion Reopen Queue` 섹션을 추가해 review ordering, remediation ordering, clearance tracking, reopen ordering의 역할 차이를 분리해서 설명한다.

## 4F. Item 6 self-check 결론
1. `promotion_reopen_queue`는 `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`, `promotion_clearance_tracker`와 역할이 분리된 compare-only re-open ordering layer로만 남아 있다.
2. 반영 surface도 validation / checklist / dashboard / README로 제한되어 있고, approval / sizing / scanner / candidate row / rollout DB / `operator_action_priority` hard ordering으로는 번지지 않았다.
3. thin sample, family execution `manual_review`, blocked clearance guardrail이 그대로 유지돼서 공격적 `reopen_review` wording이 기존 방어 규칙을 덮지 않는다.
