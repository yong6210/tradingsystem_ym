# Promotion Remediation Queue Upgrade Patch Plan

최종 갱신: 2026-03-23
상태: Item 3 baseline fixed

## 1. 목적
- `promotion_remediation_queue`를 어떤 surface에 어떤 wording으로 보여줄지 먼저 고정한다.
- `promotion_governance`, `promotion_review_queue`, `operator_action_priority`와 역할이 섞이지 않도록 반영 위치와 문구를 제한한다.

## 2. Validation Report 반영안
추가:
1. top-level `promotion_remediation_queue_available`
2. top-level `promotion_remediation_queue_summary`
3. markdown section `## Promotion Remediation Queue`

`promotion_remediation_queue_summary` 최소 필드:
1. `queue_state`
2. `headline_family`
3. `top_remediation_action`
4. `summary`
5. `reason_codes`
6. `remediation_queue`
7. `source_summary`

표현 원칙:
1. `review execution drag and exit or fill guardrails before reopening promotion review`
2. `review rollout and lifecycle posture before promotion review`
3. `review condition drag buckets before promotion review`
4. `keep in observe queue while evidence accumulates`
5. auto-unlock / auto-promote / auto-reduce language는 금지한다.

## 3. Operations Checklist 반영안
추가:
1. informational item `Promotion Remediation Queue`

동작:
1. blocking item이 아니다.
2. `queue_state in {execution_first_queue, policy_first_queue, condition_first_queue}`는 `WARN` informational 허용
3. `queue_state=observe_only_queue`는 `PASS` informational 허용
4. checklist wording은 `review execution remediation first`, `review policy remediation first`, `review condition remediation first`, `observe queue only` 정도로 제한한다.

## 4. Operator Dashboard 반영안
추가:
1. `signal_funnel.promotion_remediation_queue`

제한:
1. aggregate summary만 노출한다.
2. `remediation_queue`는 top 5 row까지만 포함한다.
3. candidate row, recent intent row, approval snapshot에는 퍼뜨리지 않는다.
4. `promotion_governance`, `promotion_review_queue`, `operator_action_priority`와 merge하지 않는다.

## 5. README 반영안
추가 위치:
1. `Promotion Review Queue` 뒤
2. `Positive Evidence Expansion` 앞

핵심 설명:
1. `promotion_governance`는 family별 review decision, `promotion_review_queue`는 cross-family review ordering, `promotion_remediation_queue`는 cross-family guardrail clearing ordering이라는 점
2. `execution_remediation / policy_remediation / condition_remediation / observe_guardrail`가 compare-only remediation queue라는 점
3. approval, sizing, rollout DB를 직접 바꾸지 않는다는 점

## 6. 비반영 Surface
추가 금지:
1. `ExecutionApproval`
2. `approval_snapshot`
3. `plan.validity`
4. `/scanner/top`
5. `/portfolio/budget` candidate row
6. rollout policy DB row
7. `operator_action_priority` hard ordering

## 7. 구현 단계 가이드
1. summary helper는 `promotion_governance`를 primary context로 읽고, `promotion_review_queue`를 ordering anchor로 사용한다.
2. remediation row는 family별 aggregate summary만 만들고 candidate row와 연결하지 않는다.
3. top-level remediation queue는 `promotion_governance`, `promotion_review_queue`와 별도 key로 유지한다.
4. `operator_action_priority`는 urgent runtime control ordering 그대로 두고, remediation queue는 governance remediation ordering만 다룬다.
