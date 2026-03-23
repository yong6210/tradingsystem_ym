# Promotion Decision Brief Upgrade Patch Plan

최종 갱신: 2026-03-23
상태: Item 3 baseline fixed

## 1. 목적
- `promotion_decision_brief`를 validation / checklist / dashboard / README에 같은 wording으로 반영한다.
- 이 계층은 `promotion_reopen_queue`의 다음 단계 설명층이지, 새 authority가 아니다.

## 2. validation 반영
validation report에는 아래 필드만 추가한다.
1. `promotion_decision_brief_available`
2. `promotion_decision_brief_summary`
3. `## Promotion Decision Brief`

summary object는 contract 필드만 그대로 노출한다.

배치 위치:
1. `## Promotion Reopen Queue` 뒤
2. `## Positive Evidence Expansion` 앞

## 3. checklist 반영
checklist에는 blocking이 아닌 informational item `Promotion Decision Brief`를 추가한다.

status rule:
1. unavailable -> `PASS`
2. `brief_state == clearance_required` -> `WARN`
3. `brief_state == observe_case` -> `PASS`
4. `brief_state == reopen_candidate` -> `PASS`

evidence는 아래만 노출한다.
1. `family`
2. `brief_state`
3. `decision_bias`
4. `target_posture`
5. `reason_codes`
6. `source_summary`
7. `advisory_only`

## 4. dashboard 반영
dashboard에는 `signal_funnel.promotion_decision_brief`만 추가한다.

원칙:
1. aggregate summary only
2. recent intent / candidate row / approval snapshot으로는 퍼뜨리지 않는다.
3. `promotion_reopen_queue`와 merge하지 않고 별도 key로 둔다.

## 5. README 반영
README에는 `Promotion Reopen Queue` 뒤, `Positive Evidence Expansion` 앞에 `Promotion Decision Brief` 섹션을 추가한다.

설명할 핵심:
1. `promotion_reopen_queue`는 cross-family ordering
2. `promotion_decision_brief`는 single-family case compression
3. `promotion_decision_brief_summary`는 compare-only layer
4. approval / sizing / rollout DB는 바꾸지 않음

## 6. 비범위
아래에는 직접 반영하지 않는다.
1. `ExecutionApproval`
2. `approval_snapshot`
3. `plan.validity`
4. `/scanner/top`
5. `/portfolio/budget` candidate row
6. rollout policy DB row
7. `operator_action_priority` hard ordering override
