# Promotion Clearance Tracker Upgrade Patch Plan

최종 갱신: 2026-03-23
상태: Item 3 baseline fixed

## 1. 목적
- `promotion_clearance_tracker`를 validation / checklist / dashboard / README에 같은 tracking language로 반영한다.
- 이 계층은 family별 clearance progress tracking만 담당하고, approval / sizing / rollout DB / candidate row authority는 바꾸지 않는다.

## 2. validation 반영안
추가 필드:
1. `promotion_clearance_tracker_available`
2. `promotion_clearance_tracker_summary`

마크다운 섹션:
1. `## Promotion Clearance Tracker`

summary object에는 아래만 노출한다.
1. `available`
2. `advisory_only`
3. `family`
4. `clearance_state`
5. `clearance_bias`
6. `confidence`
7. `summary`
8. `reason_codes`
9. `remaining_guardrail_domains`
10. `cleared_guardrail_domains`
11. `source_summary`

위치:
1. `## Promotion Remediation Queue` 뒤
2. `## Positive Evidence Expansion` 앞

## 3. checklist 반영안
새 item:
1. `Promotion Clearance Tracker`

원칙:
1. blocking item으로 만들지 않는다.
2. `blocked`, `partial_clear`는 `WARN` informational
3. `clearance_ready`, `observe_only`는 `PASS` informational
4. evidence는 validation summary 그대로 재사용한다.

핵심 evidence:
1. `clearance_state`
2. `clearance_bias`
3. `remaining_guardrail_domains`
4. `cleared_guardrail_domains`
5. `reason_codes`
6. `source_summary`

## 4. dashboard 반영안
추가 위치:
1. `signal_funnel.promotion_clearance_tracker`

원칙:
1. aggregate summary만 노출한다.
2. candidate row, recent intent, approval snapshot으로 퍼뜨리지 않는다.
3. remediation queue와 merge하지 않고 별도 key로 유지한다.

## 5. README 반영안
추가 위치:
1. `Promotion Remediation Queue` 뒤
2. `Positive Evidence Expansion` 앞

설명 원칙:
1. `promotion_governance`는 family review decision
2. `promotion_review_queue`는 cross-family review ordering
3. `promotion_remediation_queue`는 cross-family guardrail clearing ordering
4. `promotion_clearance_tracker`는 family별 clearance progress tracking

필수 설명:
1. states는 `blocked / partial_clear / clearance_ready / observe_only`
2. compare-only layer
3. approval / sizing / rollout DB mutation 없음

## 6. 비반영 surface
아래에는 추가하지 않는다.
1. `ExecutionApproval`
2. `approval_snapshot`
3. `plan.validity`
4. `/scanner/top`
5. `/portfolio/budget` candidate row
6. rollout policy DB row
7. `operator_action_priority` hard ordering
