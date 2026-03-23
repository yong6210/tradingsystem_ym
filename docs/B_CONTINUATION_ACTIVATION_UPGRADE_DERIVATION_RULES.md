# B Continuation Activation Upgrade Derivation Rules

최종 갱신: 2026-03-23
상태: baseline fixed

## 1. precedence
1. `A_ONLY / RESEARCH / compare_only` -> `research_only`
2. manual review / reduce rollout / research-degraded lifecycle / blocked clearance / auto blocked -> `blocked`
3. cleared guardrails + reopen-ready or semi-auto candidate -> `activation_ready`
4. 나머지 `A_PLUS_B` B family -> `guarded_probation`

## 2. source summary
1. cluster status는 `multi_strategy_ab.b_cluster`
2. family closed는 `score_to_outcome_funnel.decomposition.family`
3. execution status는 `family_execution_degradation_advisory`
4. rollout / lifecycle / governance / clearance / reopen / brief / execution stage / positive expansion은 기존 summary를 support source로만 쓴다.

## 3. row drill-down
1. scanner / portfolio row는 `trend_continuation`일 때만 `b_continuation_activation`을 붙인다.
2. row overlay는 symbol별 outcome input을 우선 사용한다.
