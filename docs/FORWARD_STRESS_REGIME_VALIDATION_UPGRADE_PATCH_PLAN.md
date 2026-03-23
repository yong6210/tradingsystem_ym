# Forward Stress Regime Validation Upgrade Patch Plan

최종 갱신: 2026-03-24

## 1. 목적
- `forward_stress_regime_validation`를 어디에 어떤 wording으로 넣을지 먼저 고정한다.
- 이번 단계는 raw validation artifact를 대체하는 것이 아니라, generalization confidence verdict를 한 layer로 재압축하는 것이다.

## 2. validation report
추가 방향:
1. top-level `forward_stress_regime_validation_available`
2. top-level `forward_stress_regime_validation_summary`
3. markdown section `## Forward Stress Regime Validation`

`forward_stress_regime_validation_summary` 최소 필드:
1. `available`
2. `advisory_only`
3. `validation_state`
4. `validation_bias`
5. `coverage_state`
6. `walk_forward_state`
7. `stress_state`
8. `replay_state`
9. `regime_split_state`
10. `session_split_state`
11. `preferred_live_mode`
12. `worst_scenario`
13. `best_regime`
14. `best_session`
15. `weakest_axis`
16. `summary`
17. `reason_codes`
18. `source_summary`

배치 원칙:
1. existing `strategy_v2_validation_summary` / `strategy_v2_stress_validation_summary` 설명 뒤에 둔다.
2. `A/B edge`나 promotion stack보다 앞에 둔다.
3. raw validation artifact와 synthesized verdict를 분리해서 읽히게 한다.

## 3. checklist
추가 방향:
1. informational item `Forward Stress Regime Validation`

원칙:
1. blocking은 금지한다.
2. `fragile_generalization`과 `insufficient_generalization`에서만 `WARN` informational을 허용한다.
3. `insufficient_evidence`는 `WARN` 또는 informational wording으로만 남기고 authority를 만들지 않는다.

## 4. dashboard
추가 방향:
1. `signal_funnel.forward_stress_regime_validation`

원칙:
1. aggregate summary만 허용한다.
2. candidate row, recent intent row, approval snapshot drill-down으로 퍼뜨리지 않는다.
3. existing `strategy_v2_validation_summary`, `strategy_v2_stress_validation_summary`, `strategy_v2_stress_replay_assessment_summary`는 raw source card로 유지하고, 새 layer는 verdict card로만 둔다.

## 5. README
배치 방향:
1. `Execution Friction Measurement` 설명 뒤
2. `A Strategy Post-Cost Edge Validation` 앞

핵심 문구:
1. `forward_stress_regime_validation`는 compare-only generalization confidence verdict다.
2. raw source는 `walk_forward`, `strategy_v2_validation`, `strategy_v2_stress_validation`, `strategy_v2_stress_replay_assessment`, `strategy_v2_stress_replay_lineage`다.
3. approval / sizing / rollout authority를 직접 바꾸지 않는다.

## 6. 비범위
1. approval snapshot direct mutation
2. sizing authority direct mutation
3. scanner / portfolio candidate row direct field
4. rollout DB direct mutation
5. true replay runner direct promotion
