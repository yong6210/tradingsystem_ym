# Research Promotion Operating Loop Upgrade Derivation Rules

최종 갱신: 2026-03-23

## 1. family precedence
1. `promotion_decision_brief.family`
2. `promotion_governance.family`
3. `strategy_lifecycle.family`
4. `alpha_research_pipeline.summary.top_family`
5. `promotion_review_queue.headline_family`

## 2. source normalization
1. research action anchor는 `alpha_research_pipeline.recommended_action_summary`
2. test anchor는 `alpha_research_pipeline.top_shadow_experiment`
3. watch anchor는 `alpha_research_pipeline.promotion_watchlist.watch_items[0]`
4. promotion anchor는 `promotion_governance / promotion_decision_brief / auto_promotion_rollout_execution`
5. lineage anchor는 `promotion_lifecycle_history`

## 3. state precedence
1. `promotion_followthrough`
2. `probation_candidate`
3. `shadow_test_ready`
4. `research_backlog`

## 4. state rule
1. `promotion_followthrough`
   - `auto_promotion_rollout_execution.execution_stage in {dry_run_execution, semi_auto_candidate}`
   - and `promotion_governance.state == promotable`
   - and `promotion_decision_brief.brief_state != clearance_required`
   - and no `manual_review / history_attention_required / thin sample`
2. `probation_candidate`
   - `promotion_watchlist` top item exists with no `not_ready_reason`
   - and `promotion_governance.state in {hold, promotable}`
   - and no `manual_review / history_attention_required / thin sample`
3. `shadow_test_ready`
   - `top_shadow_experiment` exists
   - or `recommended_action_summary.recommended_action` exists
4. else `research_backlog`

## 5. target_stage rule
1. `promotion_followthrough`
   - `production` posture면 `promoted`
   - 그 외는 `probation`
2. `probation_candidate`는 `probation`
3. `shadow_test_ready`는 `tested`
4. `research_backlog`는 `research`

## 6. bias rule
1. `promotion_followthrough -> follow_promotion_path`
2. `probation_candidate -> prepare_probation_review`
3. `shadow_test_ready -> queue_shadow_test`
4. `research_backlog`
   - research candidate가 있으면 `continue_shadow_test`
   - 없으면 `observe_only`

## 7. support-only modifier
1. `promotion_lifecycle_history.history_state == history_stable`은 positive support다.
2. `multi_strategy_ab`는 family cluster status context로만 쓴다.
3. `family_execution_degradation_advisory`는 promotion/followthrough blocking guardrail로만 쓴다.
