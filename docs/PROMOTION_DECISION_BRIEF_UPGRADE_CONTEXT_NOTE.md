# Promotion Decision Brief Upgrade Context Note

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 왜 이 작업을 하는가
- 현재 시스템은 family별 decision, cross-family review ordering, remediation ordering, clearance tracking, reopen ordering까지 읽을 수 있다.
- 하지만 operator는 여전히 `이 family를 지금 어떤 posture로 봐야 하는가`를 여러 summary에서 다시 조립해야 한다.
- 이번 라운드 목적은 authority를 더 늘리는 것이 아니라, promotion review case를 family 중심 decision brief로 압축하는 것이다.

## 2. 절대 규칙
1. promotion decision brief는 compare-only summary여야 한다.
2. approval / sizing / rollout DB는 직접 바꾸지 않는다.
3. thin sample에서는 공격적 decision wording 대신 observe/defer 계열만 허용한다.
4. family는 계속 1차 축이고 queue는 context source로만 사용한다.
5. urgent control은 여전히 `operator_action_priority`가 우선이고, decision brief는 governance review case만 다룬다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `strategy_lifecycle`
2. `promotion_governance`
3. `promotion_review_queue`
4. `promotion_remediation_queue`
5. `promotion_clearance_tracker`
6. `promotion_reopen_queue`
7. `positive_evidence_expansion`
8. `capital_allocator`

아직 약한 것:
1. top family promotion case를 한 summary로 읽는 common brief
2. review ordering / remediation / clearance / reopen 결과를 한 decision object로 묶는 언어
3. operator가 `지금 왜 review를 reopen할 수 있는지` 혹은 `왜 아직 defer인지`를 한눈에 읽는 압축층

## 4. 적용 원칙
1. decision brief는 `promotion_reopen_queue`와 별개다.
2. reopen queue는 cross-family ordering, decision brief는 single-family case compression이다.
3. validation / checklist / dashboard / README가 같은 decision brief language를 써야 한다.

## 4A. Item 1 계약 결론
1. brief state는 `reopen_candidate / clearance_required / observe_case`로만 고정한다.
2. decision bias는 `consider_reopen_review / continue_clearance / observe_only`로만 고정한다.
3. `target_posture`는 `probation / production / keep_current`만 허용한다.
4. 직접 입력 source는 `promotion_governance / promotion_review_queue / promotion_remediation_queue / promotion_clearance_tracker / promotion_reopen_queue / strategy_lifecycle / positive_evidence_expansion / capital_allocator / family_execution_degradation_advisory`로 제한한다.
5. 직접 반영 surface는 validation / checklist / dashboard / README만 허용하고, approval / sizing / scanner / candidate row / rollout DB / operator_action_priority hard ordering override는 비범위로 둔다.
6. thin sample, family execution `manual_review`, `promotion_clearance_tracker.clearance_state == blocked`는 `reopen_candidate` 금지 guardrail로 계약에 고정한다.

## 4B. Item 2 derivation 결론
1. headline family는 `promotion_reopen_queue -> promotion_clearance_tracker -> promotion_remediation_queue -> promotion_review_queue -> promotion_governance -> strategy_lifecycle -> positive_evidence_expansion -> capital_allocator` 순서로 고른다.
2. thin sample / `observe_only` clearance / research posture는 `observe_case`를 먼저 만든다.
3. `reopen_review + clearance_ready + no manual_review + no active remediation + governance hold/promotable` 조합일 때만 `reopen_candidate`를 허용한다.
4. 그 외는 기본적으로 `clearance_required`로 본다.
5. `positive_evidence_expansion`과 `capital_allocator`는 `reopen_candidate` confidence를 보조하는 support-only positive modifier로만 사용한다.

## 4C. Item 3 patch 결론
1. validation에는 `promotion_decision_brief_available`, `promotion_decision_brief_summary`, `## Promotion Decision Brief`를 추가한다.
2. checklist에는 blocking이 아닌 informational item `Promotion Decision Brief`만 추가한다.
3. dashboard에는 `signal_funnel.promotion_decision_brief` aggregate summary만 반영한다.
4. README에는 `Promotion Reopen Queue` 뒤, `Positive Evidence Expansion` 앞에 single-family decision brief 설명을 넣는다.
5. approval / candidate row / rollout DB / operator_action_priority hard ordering에는 반영하지 않는다.

## 4D. Item 4 구현 결론
1. `promotion_decision_brief.py`를 추가해 headline family, brief state, decision bias, target posture, source summary를 실제로 계산하게 했다.
2. `strategy_engine`는 `promotion_governance / promotion_review_queue / promotion_remediation_queue / promotion_clearance_tracker / promotion_reopen_queue`를 묶어 decision brief를 validation 과 dashboard 경로에 공통 배선한다.
3. validation report는 `promotion_decision_brief_available`, `promotion_decision_brief_summary`, `## Promotion Decision Brief`를 같은 wording으로 노출한다.
4. checklist는 새 informational item `Promotion Decision Brief`를 추가하고, dashboard는 `signal_funnel.promotion_decision_brief` aggregate summary만 보여준다.
5. approval / sizing / scanner / candidate row / rollout DB / operator_action_priority hard ordering은 그대로 비범위로 유지한다.

## 4E. Item 5 테스트 / 문서 결론
1. `test_promotion_decision_brief.py`로 `reopen_candidate`와 `clearance_required` precedence를 직접 고정한다.
2. validation / checklist / dashboard / API smoke는 `promotion_decision_brief_available`, `promotion_decision_brief_summary`, `signal_funnel.promotion_decision_brief` 계약을 같은 wording으로 검증한다.
3. README는 `Promotion Reopen Queue` 뒤에 `Promotion Decision Brief` 섹션을 추가해 reopen ordering과 single-family case compression의 역할 차이를 분리해서 설명한다.

## 4F. Item 6 self-check 결론
1. `promotion_decision_brief`는 `promotion_reopen_queue`와 분리된 single-family case compression layer로만 남아 있다.
2. 반영 surface도 validation / checklist / dashboard / README로 제한되어 있고, approval / sizing / scanner / candidate row / rollout DB / `operator_action_priority` hard ordering으로는 번지지 않았다.
3. thin sample, family execution `manual_review`, blocked clearance guardrail이 그대로 유지돼서 성급한 `reopen_candidate` wording이 기존 방어 규칙을 덮지 않는다.
