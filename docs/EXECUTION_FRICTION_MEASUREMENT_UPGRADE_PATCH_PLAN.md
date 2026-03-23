# Execution Friction Measurement Upgrade Patch Plan

최종 갱신: 2026-03-24

## 1. 목적
- `execution_friction_measurement`를 어디에 어떤 wording으로 넣을지 먼저 고정한다.
- 이번 단계는 execution quality raw metric을 대체하는 것이 아니라, live confidence verdict를 한 layer로 재압축하는 것이다.

## 2. validation report
추가 방향:
1. top-level `execution_friction_measurement_available`
2. top-level `execution_friction_measurement_summary`
3. markdown section `## Execution Friction Measurement`

`execution_friction_measurement_summary` 최소 필드:
1. `available`
2. `advisory_only`
3. `friction_state`
4. `friction_bias`
5. `fill_conversion_state`
6. `slippage_state`
7. `latency_state`
8. `fee_state`
9. `reconciliation_state`
10. `measurement_coverage_state`
11. `weakest_axis`
12. `confidence`
13. `summary`
14. `reason_codes`
15. `source_summary`

배치 원칙:
1. existing `execution_quality_summary` 설명 뒤에 둔다.
2. `A/B edge`나 promotion stack보다 앞에 둔다.
3. raw execution quality metric과 verdict를 분리해서 읽히게 한다.

## 3. checklist
추가 방향:
1. informational item `Execution Friction Measurement`

원칙:
1. blocking은 금지한다.
2. `degraded_friction`과 `watch_friction`에서만 `WARN` informational을 허용한다.
3. `insufficient_measurement`는 `WARN` 또는 informational wording으로만 남기고 authority를 만들지 않는다.

## 4. dashboard
추가 방향:
1. `signal_funnel.execution_friction_measurement`

원칙:
1. aggregate summary만 허용한다.
2. candidate row, recent intent row, approval snapshot drill-down으로 퍼뜨리지 않는다.
3. existing `execution_quality_summary`와 `recent_reconciliation_summary`는 raw source card로 유지하고, 새 layer는 verdict card로만 둔다.

## 5. README
배치 방향:
1. `Execution Quality` 설명 뒤
2. `A Strategy Post-Cost Edge Validation`이나 promotion stack보다 앞

핵심 문구:
1. `execution_friction_measurement`는 compare-only execution drag verdict다.
2. raw source는 `execution_quality`, `recent_reconciliation_summary`, `strategy_v2_stress_validation`, approval fee/slippage cap reference다.
3. approval / sizing / rollout authority를 직접 바꾸지 않는다.

## 6. 비범위
1. approval snapshot direct mutation
2. sizing authority direct mutation
3. scanner / portfolio candidate row direct field
4. rollout DB direct mutation
5. auto-throttle / auto-stop direct execution
