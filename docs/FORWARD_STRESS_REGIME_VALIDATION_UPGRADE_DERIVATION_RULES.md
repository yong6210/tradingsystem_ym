# Forward Stress Regime Validation Upgrade Derivation Rules

최종 갱신: 2026-03-24

## 1. 목적
- 이 문서는 `forward_stress_regime_validation`가 같은 입력에서 같은 generalization verdict를 내도록 derivation 규칙을 고정한다.
- 이번 라운드는 existing validation artifact를 묶는 compare-only evidence layer다.

## 2. primary source
1. `walk_forward`
2. `strategy_v2_validation`
3. `strategy_v2_stress_validation`
4. `strategy_v2_stress_replay_assessment`
5. `strategy_v2_stress_replay_lineage`

## 3. normalization
### 3.1 coverage
- `wf_trades = walk_forward.trades`
- `eligible_closed_trades = strategy_v2_validation.sample_counts.eligible_closed_trades`
- `execution_data_trades = strategy_v2_stress_validation.sample_counts.execution_data_trades`
- `coverage_state`
  - `thin_validation`
    - `wf_trades < 8`
    - or `eligible_closed_trades < 8`
  - `usable_validation`
    - `wf_trades < 20`
    - or `eligible_closed_trades < 20`
    - or `execution_data_trades < 8`
  - `mature_validation`
    - otherwise

### 3.2 walk-forward axis
- source:
  - `walk_forward.mean_ev`
  - `walk_forward.p5_ev`
  - `walk_forward.trades`
- `walk_forward_state`
  - `insufficient_walk_forward`
    - `wf_trades == 0`
  - `fragile_walk_forward`
    - `mean_ev <= 0`
    - or `p5_ev <= -0.8`
  - `validated_walk_forward`
    - `wf_trades >= 8`
    - and `mean_ev > 0`
    - and `p5_ev > -0.8`

### 3.3 stress axis
- source:
  - `strategy_v2_stress_validation.deployment_recommendation`
  - `strategy_v2_stress_validation.comparison`
  - `strategy_v2_stress_validation.sample_counts`
- `stress_state`
  - `insufficient_stress`
    - stress payload missing
    - or `eligible_closed_trades == 0`
  - `fragile_stress`
    - `stress_pass == false`
    - or `reason` starts with `scenario_catastrophic_drawdown`
    - or `reason` starts with `replay_divergence_fail`
    - or `reason` starts with `replay_divergence_warn`
    - or `reason` starts with `scenario_degraded`
  - `validated_stress`
    - otherwise

### 3.4 replay axis
- source:
  - `strategy_v2_stress_replay_assessment.deployment_recommendation`
  - `strategy_v2_stress_replay_assessment.full_replay_ready`
  - `strategy_v2_stress_replay_lineage.runtime_inputs_ready`
  - `strategy_v2_stress_replay_lineage.coverage`
- `replay_state`
  - `replay_lineage_thin`
    - lineage payload missing
    - or `runtime_inputs_ready == false`
    - or assessment reason == `insufficient_runtime_lineage`
  - `replay_followup_required`
    - assessment decision in `prepare_full_replay`, `promote_true_market_runner`
    - or `replacement_recommended == true`
    - or `true_runner_promotion_ready == true`
  - `approximation_confirmed`
    - otherwise

### 3.5 regime split axis
- source:
  - `strategy_v2_validation.regime_metrics`
  - `strategy_v2_validation.regime_summary`
- meaningful regime bucket:
  - `trades >= 3`
- `regime_split_state`
  - `insufficient_regime_split`
    - meaningful regime bucket count < 2
  - `fragile_regime_split`
    - any meaningful bucket has `ev <= 0`
    - or `p5_ev <= -0.8`
    - or `time_failure_ratio >= 0.35`
  - `validated_regime_split`
    - otherwise

### 3.6 session split axis
- source:
  - `strategy_v2_validation.session_metrics`
  - `strategy_v2_validation.session_summary`
- meaningful session bucket:
  - `trades >= 3`
- `session_split_state`
  - `insufficient_session_split`
    - meaningful session bucket count < 2
  - `fragile_session_split`
    - any meaningful bucket has `ev <= 0`
    - or `p5_ev <= -0.8`
    - or `time_failure_ratio >= 0.35`
  - `validated_session_split`
    - otherwise

## 4. verdict precedence
1. `insufficient_evidence`
2. `insufficient_generalization`
3. `fragile_generalization`
4. `validated_generalization`

## 5. verdict rule
### 5.1 insufficient_evidence
아래 중 하나면 먼저 고정:
1. `coverage_state == thin_validation`
2. `walk_forward_state == insufficient_walk_forward`
3. `stress_state == insufficient_stress`
4. `regime_split_state == insufficient_regime_split` and `session_split_state == insufficient_session_split`

### 5.2 insufficient_generalization
아래 중 하나면 insufficient:
1. `walk_forward_state == fragile_walk_forward` and `walk_forward.mean_ev <= 0`
2. stress reason starts with `scenario_catastrophic_drawdown`
3. stress reason starts with `replay_divergence_fail`
4. `replay_state == replay_lineage_thin` and `stress_state == fragile_stress`
5. `regime_split_state == fragile_regime_split` and `session_split_state == fragile_session_split`

### 5.3 fragile_generalization
아래 중 하나면 fragile:
1. `coverage_state == usable_validation`
2. `walk_forward_state == fragile_walk_forward`
3. `stress_state == fragile_stress`
4. `replay_state == replay_followup_required`
5. `regime_split_state == fragile_regime_split`
6. `session_split_state == fragile_session_split`

### 5.4 validated_generalization
아래를 모두 만족할 때만 validated:
1. `coverage_state != thin_validation`
2. `walk_forward_state == validated_walk_forward`
3. `stress_state == validated_stress`
4. `replay_state != replay_lineage_thin`
5. `regime_split_state == validated_regime_split`
6. `session_split_state == validated_session_split`

## 6. bias mapping
- `validated_generalization -> support_current_validation`
- `fragile_generalization -> monitor_regime_stress_fragility`
- `insufficient_generalization -> reduce_deployment_confidence`
- `insufficient_evidence -> gather_more_validation_evidence`

## 7. support fields
- `preferred_live_mode`
- `worst_scenario`
- `best_regime`
- `best_session`
- `weakest_axis`
- `reason_codes`
- `source_summary`

### 7.1 weakest_axis
- insufficient/fragile verdict를 만든 가장 강한 axis를 1개만 선택한다.
- 우선순위:
  1. `stress_state`
  2. `walk_forward_state`
  3. `replay_state`
  4. `regime_split_state`
  5. `session_split_state`
  6. `coverage_state`

### 7.2 reason_codes
- 예시:
  - `thin_validation_coverage`
  - `walk_forward_mean_ev_non_positive`
  - `stress_catastrophic_drawdown`
  - `stress_replay_divergence_fail`
  - `replay_lineage_thin`
  - `replay_followup_required`
  - `fragile_regime_bucket`
  - `fragile_session_bucket`

## 8. wording
- validated:
  - “Current forward, stress, and split evidence still supports the existing validation posture.”
- fragile:
  - “Generalization still holds directionally, but regime/stress/replay fragility is visible and should be monitored.”
- insufficient_generalization:
  - “Current forward or stress evidence is weak enough that deployment confidence should be treated as reduced.”
- insufficient_evidence:
  - “Validation evidence is still too thin to treat current generalization as stable.”

## 9. non-goals
1. approval / sizing / rollout DB 자동 변경
2. true market replay runner 직접 승격 실행
3. 새 walk-forward engine 재설계
