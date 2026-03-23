# Promotion Clearance Tracker Upgrade Context Note

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 왜 이 작업을 하는가
- 현재 시스템은 family별 `promotion_governance`, cross-family `promotion_review_queue`, cross-family `promotion_remediation_queue`를 읽을 수 있다.
- 하지만 operator는 여전히 `어느 family가 remediation을 실제로 얼마나 해소했고, review 재개에 얼마나 가까운가`를 직접 추론해야 한다.
- 이번 라운드 목적은 authority를 더 늘리는 것이 아니라, promotion clearance 진척도를 더 일관된 tracking language로 정리하는 것이다.

## 2. 절대 규칙
1. promotion clearance tracker는 compare-only summary여야 한다.
2. approval / sizing / rollout DB는 직접 바꾸지 않는다.
3. thin sample에서는 공격적 clearance wording 대신 `observe` 계열만 허용한다.
4. family는 계속 1차 축이고 condition bucket은 modifier로만 사용한다.
5. urgent control은 여전히 `operator_action_priority`가 우선이고, clearance tracker는 governance progress만 다룬다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `strategy_lifecycle`
2. `promotion_governance`
3. `promotion_review_queue`
4. `promotion_remediation_queue`
5. `positive_evidence_expansion`
6. `capital_allocator`
7. `outcome_bucket_granularity`

아직 약한 것:
1. family별 remediation clearance progress 공통 언어
2. `blocked / partial / cleared`를 같은 방식으로 읽는 operator summary
3. remediation ordering과 promotion re-open readiness의 직접 연결

## 4. 적용 원칙
1. clearance tracker는 `promotion_remediation_queue`와 별개다.
2. remediation queue는 cross-family guardrail clearing ordering, clearance tracker는 family별 clearance progress tracking이다.
3. validation / checklist / dashboard / README가 같은 clearance language를 써야 한다.

## 4A. Item 1 계약 결론
1. clearance state는 `blocked / partial_clear / clearance_ready / observe_only`로만 고정한다.
2. `clearance_bias`는 `continue_remediation / consider_reopen_review / observe`까지만 허용한다.
3. 직접 입력 source는 `promotion_governance / promotion_review_queue / promotion_remediation_queue / strategy_lifecycle / family_execution_degradation_advisory / rollout_recommendation / outcome_bucket_granularity / positive_evidence_expansion / capital_allocator`로 제한한다.
4. 직접 반영 surface는 validation / checklist / dashboard / README만 허용하고, approval / sizing / scanner / candidate row / rollout DB / operator_action_priority hard ordering override는 비범위로 둔다.
5. thin sample은 `observe_only`, family execution `manual_review`는 `clearance_ready` 금지, active rollout or condition drag는 cleared domain으로 계산하지 않는 guardrail을 계약으로 고정한다.

## 4B. Item 2 derivation 결론
1. `promotion_governance`를 family posture anchor로, `promotion_remediation_queue`를 current remediation domain anchor로, `promotion_review_queue`를 cross-family review context로 사용한다.
2. family 선택 우선순위는 `promotion_governance.family -> promotion_remediation_queue.headline_family -> promotion_review_queue.headline_family -> strategy_lifecycle.family -> positive_evidence_expansion.family -> capital_allocator.family_focus`로 고정한다.
3. execution / policy / condition domain을 각각 `blocked / partial / cleared / unknown`으로 먼저 정규화하고, `remaining_guardrail_domains`와 `cleared_guardrail_domains`를 그 결과에서 파생한다.
4. thin sample은 항상 `observe_only`, remaining blocked domain이 여러 개면 `blocked`, blocked domain이 없고 thin sample이 아니며 manual review도 아니면 `clearance_ready`, 그 사이를 `partial_clear`로 고정한다.
5. `positive_evidence_expansion`과 `capital_allocator`는 `clearance_ready` confidence를 높이는 support-only positive modifier로만 사용하고, standalone으로 state를 만들게 두지 않는다.

## 4C. Item 3 patch 결론
1. validation에는 `promotion_clearance_tracker_available`, `promotion_clearance_tracker_summary`, `## Promotion Clearance Tracker`를 추가한다.
2. checklist에는 blocking이 아닌 informational item `Promotion Clearance Tracker`만 추가한다.
3. dashboard에는 `signal_funnel.promotion_clearance_tracker` aggregate summary만 반영한다.
4. README에는 `Promotion Remediation Queue` 뒤, `Positive Evidence Expansion` 앞에 family별 clearance progress 설명을 넣는다.
5. approval / candidate row / rollout DB / operator_action_priority hard ordering에는 반영하지 않는다.

## 4D. Item 4 구현 결론
1. `promotion_clearance_tracker.py`를 추가해 `blocked / partial_clear / clearance_ready / observe_only`와 `remaining_guardrail_domains / cleared_guardrail_domains`를 family별로 계산하도록 구현했다.
2. strategy engine은 `promotion_governance`를 family posture anchor로, `promotion_remediation_queue`를 current remediation anchor로, `promotion_review_queue`를 review context로 묶어 clearance tracker summary를 생성하도록 배선했다.
3. validation report에는 `promotion_clearance_tracker_available`, `promotion_clearance_tracker_summary`, `## Promotion Clearance Tracker` 섹션을 추가했다.
4. operational checklist에는 non-blocking informational item `Promotion Clearance Tracker`를 추가했다.
5. dashboard에는 `signal_funnel.promotion_clearance_tracker` aggregate summary만 반영했고 approval / candidate row / rollout DB / operator_action_priority hard ordering에는 반영하지 않았다.

## 4E. Item 5 테스트 및 문서 동기화 결론
1. `test_promotion_clearance_tracker.py`를 추가해 `blocked` 상태와 `remaining_guardrail_domains` 계산을 helper 단위 테스트로 고정했다.
2. validation / checklist / dashboard / API smoke 테스트에 `promotion_clearance_tracker` 키와 핵심 semantics를 추가해 surface 계약을 고정했다.
3. README에 `Promotion Clearance Tracker` 섹션을 추가하고, `promotion_governance -> promotion_review_queue -> promotion_remediation_queue -> promotion_clearance_tracker` 역할 분리를 operator surface 설명까지 반영했다.
4. 이번 계층이 compare-only family progress tracking이라는 경계도 README와 테스트 양쪽에서 같이 못 박았다.

## 4F. Item 6 self-check 결론
1. `promotion_clearance_tracker`는 validation / checklist / dashboard / README에만 additive로 붙어 있고, approval / sizing / scanner / candidate row / rollout DB / operator_action_priority hard ordering으로는 번지지 않았다.
2. `promotion_governance`는 family review decision, `promotion_review_queue`는 cross-family review ordering, `promotion_remediation_queue`는 cross-family guardrail-clearing ordering, `promotion_clearance_tracker`는 family progress tracking이라는 역할 분리가 유지된다.
3. thin sample, family execution `manual_review`, active rollout / condition drag guardrail도 그대로 살아 있어서 성급한 `clearance_ready` wording이 기존 방어 규칙을 덮지 않는다.
4. helper unit test, surface 회귀, README 동기화까지 끝난 상태라 이번 라운드 범위 안에서 추가 수정이 필요한 충돌은 보이지 않는다.
