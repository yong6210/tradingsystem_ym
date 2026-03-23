# Capture-Aware Operator Priority Plan

최종 갱신: 2026-03-23
상태: All checklist items completed

## 1. 작업명
`strategy v2`에 capture-aware operator priority 계층 추가

## 2. 배경
- outcome-first control loop, rollout recommendation, opportunity capture까지 연결됐다.
- 하지만 현재 `operator_action_priority`는 execution / research / mode 중심이고, `selection bottleneck`, `fill shortage`, `thin activity`를 top action으로 바로 읽지는 않는다.
- 다음 단계는 `opportunity_capture`를 operator action priority에 연결해, 운영자가 `무엇부터 봐야 하는지`를 throughput 기준으로도 읽게 만드는 것이다.

## 3. 목표
1. `opportunity_capture`를 `operator_action_priority`의 supporting signal로 연결한다.
2. selection bottleneck / fill shortage / thin activity를 operator action wording으로 번역한다.
3. recommendation이 아니라 `compare-only operator reading priority`로 먼저 추가한다.

## 4. 핵심 개선 축
1. Capture-aware priority contract
- `dominant_bottleneck`과 `family_focus`를 operator action language로 번역한다.

2. Surface alignment
- validation report, operations checklist, operator dashboard가 같은 priority wording을 사용한다.

3. Guardrail
- approval / sizing / rollout policy source-of-truth는 그대로 유지한다.
- 이번 라운드는 action wording만 추가하고 threshold 자동 변경은 하지 않는다.

## 5. 구현 범위
포함:
1. capture-aware priority contract / derivation
2. operator action priority 반영
3. validation/checklist/dashboard surface 동기화
4. 테스트와 README 동기화

제외:
1. approval state 직접 수정
2. sizing 직접 수정
3. rollout policy 자동 변경
4. threshold 자동 완화/강화

## 6. 완료 기준
1. operator가 `quality review`, `rollout review`, `execution fill review`, `thin activity observe`를 구분해 읽을 수 있다.
2. `opportunity_capture`와 `operator_action_priority`가 같은 bottleneck 언어를 쓴다.
3. 이번 계층이 source-of-truth를 바꾸지 않는다.

## 7. 예상 산출물
- `CAPTURE_AWARE_OPERATOR_PRIORITY_CONTEXT_NOTE.md`
- `CAPTURE_AWARE_OPERATOR_PRIORITY_CHECKLIST.md`
- `CAPTURE_AWARE_OPERATOR_PRIORITY_CONTRACT.md`
- `CAPTURE_AWARE_OPERATOR_PRIORITY_DERIVATION_RULES.md`
- `CAPTURE_AWARE_OPERATOR_PRIORITY_PATCH_PLAN.md`
- capture-aware priority derivation 문서
- patch plan 문서
- `app/services/operator_action_priority.py`
- validation/checklist/dashboard 코드 수정
- 회귀 테스트
