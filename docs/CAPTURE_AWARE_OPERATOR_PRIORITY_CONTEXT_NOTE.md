# Capture-Aware Operator Priority Context Note

최종 갱신: 2026-03-23
상태: All checklist items completed

## 1. 왜 이 작업을 하는가
- 현재 엔진은 `무슨 문제가 있는가`는 잘 보여주지만, `그래서 운영자가 지금 무엇부터 봐야 하는가`는 throughput 기준으로는 아직 약하다.
- 이번 라운드 목적은 `opportunity_capture`를 action language로 번역해서 operator priority를 더 실무적으로 만드는 것이다.

## 2. 절대 규칙
1. operator action priority는 explanation / review priority 계층으로 유지한다.
2. `opportunity_capture`를 approval / sizing / rollout authority로 승격하지 않는다.
3. thin activity는 negative verdict가 아니라 `observe` 성격으로 처리한다.
4. family 우선, regime/session은 modifier로만 쓴다.
5. `quality weakness`와 `throughput weakness`를 같은 action으로 섞지 않는다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `operator_action_priority`
2. `outcome_control_trace`
3. `rollout_recommendation`
4. `opportunity_capture`

아직 약한 것:
1. `opportunity_capture` -> `operator_action_priority` 직접 연결
2. bottleneck별 top action wording
3. throughput issue가 checklist next action과 바로 이어지는 구조

## 3A. Item 1 계약 결론
1. capture-aware priority는 새 authority가 아니라 기존 `operator_action_priority`의 additive 확장이다.
2. `opportunity_capture`는 `priority_source = opportunity_capture`, `action_family`, `capture_context`를 통해서만 연결한다.
3. 우선순위는 `playbook -> execution degradation -> family execution -> opportunity capture -> mode -> research -> monitor`로 고정한다.
4. thin activity는 `observe_activity_window_before_threshold_changes`와 `monitor`까지만 허용한다.
5. approval / sizing / rollout policy는 이번 라운드에서도 직접 수정하지 않는다.

## 3B. Item 2 derivation 결론
1. capture-aware action은 `dominant_bottleneck` 기준으로 최대 1개의 primary candidate만 만든다.
2. top action 정렬은 `priority_level -> source precedence -> action name` 순서로 고정한다.
3. capture-aware candidate는 `playbook / execution / family execution`보다 뒤, `mode / research`보다 앞에 둔다.
4. `capture_context`는 top action source와 무관하게 summary에 유지한다.
5. `blocking_signals`에는 capture prefix를 넣지 않고, capture-related 정보는 `supporting_signals`에만 남긴다.

## 3C. Item 3 patch 결론
1. capture-aware 반영은 새 object 추가가 아니라 기존 `operator_action_priority` summary 확장으로 처리한다.
2. validation / checklist / dashboard가 공통으로 `priority_source`, `action_family`, `capture_context`를 읽는다.
3. 기존 `Opportunity Capture` item과 summary는 그대로 유지하고, priority surface와 merge하지 않는다.
4. checklist는 새 item을 만들지 않고 기존 `Operator Action Priority` item evidence만 확장한다.
5. recent intents / portfolio candidate / approval snapshot에는 capture-aware priority를 퍼뜨리지 않는다.

## 3D. Item 4 구현 결론
1. `operator_action_priority`는 `opportunity_capture`를 읽어 capture-aware candidate를 생성한다.
2. capture-aware candidate는 기존 urgent control을 덮지 않고 `mode / research`보다 앞의 review order로만 들어간다.
3. `priority_source`, `action_family`, `capture_context`가 validation / checklist / dashboard summary에 공통 노출된다.
4. `Opportunity Capture` 원본 summary는 그대로 유지되고, `operator_action_priority`는 action layer로만 확장됐다.
5. 관련 회귀 세트는 통과했고, 기존 surface contract는 additive 변경만 생겼다.

## 3E. Item 5 테스트/문서 동기화 결론
1. validation/checklist/dashboard/API smoke 테스트가 `priority_source`, `action_family`, `capture_context`를 명시적으로 요구하도록 고정됐다.
2. `capture_context`는 top action source와 무관하게 유지된다는 점을 fixture 수준에서 검증한다.
3. README는 `Capture-Aware Operator Priority` 섹션과 operator surface 설명을 현재 runtime 언어에 맞춰 동기화했다.
4. `Opportunity Capture`와 `operator_action_priority`의 역할 분리는 README에서도 그대로 유지했다.

## 3F. Item 6 self-check 결론
1. capture-aware priority는 `operator_action_priority` summary에만 additive로 붙었고, approval / sizing / rollout authority는 건드리지 않았다.
2. `Opportunity Capture` 원본 object는 throughput explanation layer로 그대로 남아 있고, priority layer와 merge되지 않았다.
3. `priority_source`, `action_family`, `capture_context`는 validation / checklist / dashboard / README에서 같은 의미로 정렬됐다.
4. 관련 회귀 세트가 통과했고, 추가 수정이 필요한 충돌이나 계약 위반은 보이지 않았다.

## 4. 적용 원칙
1. `operator_action_priority`는 recommendation보다 `reading order`에 가깝게 유지한다.
2. `quality / rollout / execution fill / thin activity`를 다른 action family로 구분한다.
3. `opportunity_capture`는 operator priority를 보강할 뿐, 기존 execution/advisory signal을 대체하지 않는다.

## 5. 참고 기준
- `/Users/yumin/Documents/trading/app/services/operator_action_priority.py`
- `/Users/yumin/Documents/trading/app/services/opportunity_capture.py`
- `/Users/yumin/Documents/trading/app/services/operational_checklist.py`
- `/Users/yumin/Documents/trading/app/services/execution_operator_dashboard.py`
- `/Users/yumin/Documents/trading/docs/OPPORTUNITY_CAPTURE_UPGRADE_CONTEXT_NOTE.md`
- `/Users/yumin/Documents/trading/docs/CAPTURE_AWARE_OPERATOR_PRIORITY_CONTRACT.md`
- `/Users/yumin/Documents/trading/docs/CAPTURE_AWARE_OPERATOR_PRIORITY_DERIVATION_RULES.md`
- `/Users/yumin/Documents/trading/docs/CAPTURE_AWARE_OPERATOR_PRIORITY_PATCH_PLAN.md`
