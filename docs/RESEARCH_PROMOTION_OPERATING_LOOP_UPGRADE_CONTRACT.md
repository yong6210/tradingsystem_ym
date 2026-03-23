# Research Promotion Operating Loop Upgrade Contract

최종 갱신: 2026-03-23

## 1. 목적
- `alpha_research_pipeline`와 promotion stack을 하나의 operating loop language로 연결한다.
- research candidate가 `research -> tested -> probation -> promoted` 경로에서 어디에 있는지 compare-only summary로 읽게 만든다.

## 2. 허용 state
1. `research_backlog`
2. `shadow_test_ready`
3. `probation_candidate`
4. `promotion_followthrough`

## 3. 허용 bias
1. `queue_shadow_test`
2. `continue_shadow_test`
3. `prepare_probation_review`
4. `follow_promotion_path`
5. `observe_only`

## 4. 허용 target_stage
1. `research`
2. `tested`
3. `probation`
4. `promoted`

## 5. 입력 source
1. `alpha_research_pipeline`
2. `strategy_lifecycle`
3. `promotion_governance`
4. `promotion_review_queue`
5. `promotion_decision_brief`
6. `auto_promotion_rollout_execution`
7. `promotion_lifecycle_history`
8. `family_execution_degradation_advisory`
9. `multi_strategy_ab`

## 6. 출력 surface
1. `validation`
2. `operations/checklist`
3. `execution/operator-dashboard`
4. `README`

## 7. 비범위
1. `ExecutionApproval`
2. `approval_snapshot`
3. `plan.validity`
4. `/scanner/top`
5. `/portfolio/budget` candidate row
6. rollout DB direct write

## 8. guardrail
1. thin sample, family execution `manual_review`, `history_attention_required` 상태에서는 `probation_candidate`와 `promotion_followthrough`를 금지한다.
2. 이 layer는 compare-only operating loop summary이지 새로운 approval / sizing / rollout authority가 아니다.
