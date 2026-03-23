# Outcome-First Rollout Recommendation Context Note

최종 갱신: 2026-03-23
상태: All checklist items completed

## 1. 왜 이 작업을 하는가
- 현재 엔진은 approval, sizing, portfolio ordering까지 outcome-first control을 반영한다.
- 하지만 rollout policy 자체는 여전히 정적 정책과 수동 operator 판단 비중이 크다.
- 이번 라운드 목적은 `rollout policy 자동 변경`이 아니라, operator가 읽는 `outcome-aware rollout recommendation`을 추가하는 것이다.

## 2. 절대 규칙
1. rollout policy repository는 계속 source-of-truth다.
2. recommendation은 compare-only / advisory-only다.
3. `APPROVED_AUTO`, `APPROVED_MANUAL`, `BLOCKED` semantics를 새로 바꾸지 않는다.
4. thin sample bucket은 공격적 recommendation을 내리지 않는다.
5. family 우선, regime/session은 보조 근거로만 쓴다.
6. alpha research promotion watchlist와 rollout recommendation은 같은 뜻처럼 섞지 않는다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `score_to_outcome_funnel`
2. `execution_degradation_advisory`
3. `family_execution_degradation_advisory`
4. `mode_advisory`
5. `operator_action_priority`
6. outcome-first approval / sizing / portfolio ordering

아직 약한 것:
1. rollout expansion / hold / reduction 추천의 명시적 summary
2. validation/checklist/dashboard에서 읽는 rollout recommendation 공통 언어
3. promotion watchlist와 rollout recommendation의 경계 설명

## 4. 적용 원칙
1. `expand`는 mature positive post-cost evidence가 있을 때만 허용한다.
2. `hold`는 mixed evidence 또는 thin sample 기본 상태다.
3. `reduce`는 execution degradation 또는 weak post-cost alignment가 분명할 때만 사용한다.
4. `research_only`는 quality/advisory가 강하지만 rollout 확대 근거가 부족할 때만 사용한다.

## 5. 참고 기준
- `/Users/yumin/Documents/trading/app/services/score_to_outcome_funnel.py`
- `/Users/yumin/Documents/trading/app/services/family_execution_degradation_advisory.py`
- `/Users/yumin/Documents/trading/app/services/mode_advisory.py`
- `/Users/yumin/Documents/trading/app/services/operator_action_priority.py`
- `/Users/yumin/Documents/trading/docs/OUTCOME_FIRST_ENGINE_UPGRADE_CONTEXT_NOTE.md`

## 6. Item 1 계약 결론
1. rollout recommendation은 새 policy authority가 아니라 compare-only advisory object다.
2. 출력 surface는 validation / checklist / dashboard로 제한하고, approval/sizing/DB row는 비노출로 둔다.
3. recommendation 값은 `expand / hold / reduce / research_only`로 고정한다.
4. family 축을 최우선으로 보고 regime/session은 보조 근거로만 사용한다.
5. current policy와 suggested policy delta를 함께 보여주되 자동 변경은 하지 않는다.

## 7. Item 2 규칙 결론
1. 우선순위는 `research_only -> reduce -> expand -> hold`로 고정한다.
2. `expand`는 mature positive family evidence와 healthy family execution이 동시에 있을 때만 허용한다.
3. `reduce`는 family execution `watch/manual_review` 또는 negative family post-cost evidence가 분명할 때만 허용한다.
4. regime/session은 family recommendation을 보조하는 modifier로만 사용한다.
5. `suggested_policy_delta`는 mode 한 단계 상향/하향 또는 유지 hint만 제공하고 DB 자동 변경은 하지 않는다.

## 8. Item 3 surface 반영 결론
1. validation은 top-level summary와 markdown section으로 rollout recommendation을 보여준다.
2. checklist는 `rollout_recommendation` item을 따로 두고, current policy 대비 operator review 필요 여부만 요약한다.
3. dashboard는 `signal_funnel.rollout_recommendation` 요약만 추가하고 candidate/intents row로는 퍼뜨리지 않는다.
4. `outcome_control_trace`는 approval/sizing/portfolio control chain 설명이고, rollout recommendation은 policy suggestion이라는 경계를 유지한다.
5. wording은 `advisory-only`, `compare-only`, `current policy`, `suggested delta`로 고정한다.

## 9. Item 4 구현 결론
1. rollout recommendation은 새 helper service에서 family별로 계산하고, 가장 action-worthy family headline만 surface에 노출한다.
2. validation report에는 `rollout_recommendation_available`, `rollout_recommendation_summary`, markdown section이 추가됐다.
3. operations checklist에는 `rollout_recommendation` item이 추가됐고, live family `reduce`는 `MANUAL` review로 올린다.
4. dashboard는 `signal_funnel.rollout_recommendation`에 advisory-only summary만 노출한다.
5. rollout policy DB, approval state, sizing source-of-truth는 그대로 유지한다.

## 10. Item 5 검증 결론
1. rollout recommendation은 validation report, operations checklist, operator dashboard, API smoke 경로에서 모두 key 존재와 핵심 값을 테스트로 고정했다.
2. README에는 compare-only rollout recommendation 계층과 operator surface 반영 내용을 동기화했다.
3. checklist의 live-family `reduce` recommendation은 `MANUAL` review를 통해 `NO_GO`로 이어지는 현재 semantics를 테스트에서 명시적으로 고정했다.

## 11. Item 6 self-check 결론
1. rollout recommendation은 여전히 compare-only / advisory-only이고 rollout policy DB row를 자동 변경하지 않는다.
2. approval, sizing, portfolio ordering source-of-truth는 그대로 유지되고, 새 recommendation은 validation/checklist/dashboard 설명 계층에만 머문다.
3. 새 `MANUAL` escalation은 operator checklist에서만 적용되며 runtime approval/sizing semantics를 직접 바꾸지 않는다.
4. 관련 테스트와 README 동기화까지 끝났고, 추가 수정이 필요한 누락이나 회귀는 현재 기준에서 보이지 않는다.
