# Execution Friction Measurement Upgrade Derivation Rules

최종 갱신: 2026-03-24

## 1. 목적
- 이 문서는 `execution friction measurement`가 같은 입력에서 같은 friction verdict를 내도록 derivation 규칙을 고정한다.
- 이번 라운드는 actual execution quality와 stress-cost context를 묶는 compare-only evidence layer다.

## 2. primary source
1. `execution_quality_summary`
2. `recent_reconciliation_summary`
3. `strategy_v2_stress_validation`
4. approval cap reference
   - `max_slippage_bps`
   - `expected_fee_bps`

## 3. normalization
### 3.1 measurement coverage
- `fills_matched = execution_quality.fills_matched`
- `fill_events_total = execution_quality.fill_events_total`
- `execution_fill_coverage = execution_quality.fill_sources.execution_fills / max(fills_matched, 1)`
- `measurement_coverage_state`
  - `thin_measurement`
    - `fills_matched < 4`
    - or `execution_fill_coverage < 0.50`
  - `partial_measurement`
    - `fills_matched < 8`
    - or `execution_fill_coverage < 0.70`
  - `mature_measurement`
    - otherwise

### 3.2 fill conversion
- primary metric: `fill_rate = execution_quality.fill_rate`
- support context:
  - `unfilled_reasons`
  - `information_failure_ratio`
  - `time_failure_ratio`
- `fill_conversion_state`
  - `degraded_fill_conversion`
    - `fill_rate < 0.30`
    - or `information_failure_ratio >= 0.25`
    - or `time_failure_ratio >= 0.35`
  - `watch_fill_conversion`
    - `fill_rate < 0.50`
    - or `information_failure_ratio >= 0.15`
    - or `time_failure_ratio >= 0.20`
  - `healthy_fill_conversion`
    - otherwise

### 3.3 slippage
- primary metric:
  - `avg_slippage_bps = execution_quality.slippage_bps.avg`
  - `p95_slippage_bps = execution_quality.slippage_bps.p95`
- cap reference:
  - `approval_slippage_cap_bps = max_slippage_bps`
- `slippage_state`
  - `degraded_slippage`
    - `p95_slippage_bps >= approval_slippage_cap_bps`
    - or `avg_slippage_bps >= approval_slippage_cap_bps * 0.75`
  - `watch_slippage`
    - `p95_slippage_bps >= approval_slippage_cap_bps * 0.50`
    - or `avg_slippage_bps >= approval_slippage_cap_bps * 0.50`
  - `healthy_slippage`
    - otherwise

### 3.4 latency
- raw source:
  - `entry_latency_seconds.avg/p95`
- normalized primary context:
  - `strategy_v2_stress_validation.scenario_summary.latency_penalty_r.avg/p95`
- `latency_state`
  - `degraded_latency`
    - `latency_penalty_r.p95 >= 0.20`
    - or `entry_latency_seconds.p95 >= 1800`
  - `watch_latency`
    - `latency_penalty_r.p95 >= 0.10`
    - or `entry_latency_seconds.p95 >= 900`
  - `healthy_latency`
    - otherwise

### 3.5 fee drag
- actual absolute fill fee는 symbol/notional normalization이 없으므로 support-only다.
- first-wave primary metric:
  - `fee_component_r.avg/p95 = strategy_v2_stress_validation.cost_summary.fee_component_r`
- `fee_state`
  - `degraded_fee_drag`
    - `fee_component_r.p95 >= 0.20`
    - or `fee_component_r.avg >= 0.10`
  - `watch_fee_drag`
    - `fee_component_r.p95 >= 0.10`
    - or `fee_component_r.avg >= 0.05`
  - `healthy_fee_drag`
    - otherwise

### 3.6 reconciliation integrity
- source:
  - `recent_reconciliation_summary.highest_severity`
  - `critical_count`
  - `lock_required_count`
- `reconciliation_state`
  - `degraded_reconciliation`
    - highest severity `CRITICAL`
    - or `critical_count > 0`
    - or `lock_required_count > 0`
  - `watch_reconciliation`
    - `degraded == True`
    - or highest severity `WARNING`
  - `healthy_reconciliation`
    - otherwise

### 3.7 stress drag context
- support-only source:
  - `strategy_v2_stress_validation.comparison`
  - `deployment_recommendation`
- first-wave simplified state:
  - `degraded_stress_drag`
    - recommendation in `reduce`, `research_only`, `hold`
  - `watch_stress_drag`
    - stressed comparison clearly worse but recommendation still `keep`
  - `healthy_stress_drag`
    - otherwise

## 4. verdict precedence
1. `insufficient_measurement`
2. `degraded_friction`
3. `watch_friction`
4. `healthy_friction`

## 5. verdict rule
### 5.1 insufficient_measurement
아래 중 하나면 먼저 고정:
1. `measurement_coverage_state == thin_measurement`
2. `execution_quality_summary`가 비어 있음
3. `fills_matched == 0`

### 5.2 degraded_friction
아래 중 하나면 degraded:
1. `reconciliation_state == degraded_reconciliation`
2. `slippage_state == degraded_slippage`
3. `latency_state == degraded_latency`
4. `fee_state == degraded_fee_drag`
5. `fill_conversion_state == degraded_fill_conversion` and `measurement_coverage_state != thin_measurement`
6. `watch` 이상의 friction axis가 3개 이상 동시 발생
7. `degraded_stress_drag` and (`watch_slippage` or `watch_latency` or `watch_fill_conversion`)

### 5.3 watch_friction
아래 중 하나면 watch:
1. `measurement_coverage_state == partial_measurement`
2. `reconciliation_state == watch_reconciliation`
3. `slippage_state == watch_slippage`
4. `latency_state == watch_latency`
5. `fee_state == watch_fee_drag`
6. `fill_conversion_state == watch_fill_conversion`
7. `watch_stress_drag`

### 5.4 healthy_friction
아래를 모두 만족할 때만 healthy:
1. `measurement_coverage_state == mature_measurement`
2. `fill_conversion_state == healthy_fill_conversion`
3. `slippage_state == healthy_slippage`
4. `latency_state == healthy_latency`
5. `fee_state == healthy_fee_drag`
6. `reconciliation_state == healthy_reconciliation`
7. `stress_drag_state != degraded_stress_drag`

## 6. bias mapping
- `healthy_friction -> keep_execution_confidence`
- `watch_friction -> monitor_execution_drag`
- `degraded_friction -> reduce_execution_confidence`
- `insufficient_measurement -> gather_more_execution_evidence`

## 7. support fields
- `weakest_axis`
- `confidence`
- `reason_codes`
- `source_summary`

### 7.1 weakest_axis
- degraded/watch verdict를 만든 가장 강한 axis를 1개만 선택한다.
- 우선순위:
  1. `reconciliation_state`
  2. `slippage_state`
  3. `latency_state`
  4. `fill_conversion_state`
  5. `fee_state`
  6. `measurement_coverage_state`

### 7.2 confidence
- `low`
  - `thin_measurement`
  - or stress source missing
- `medium`
  - `partial_measurement`
  - or `execution_fill_coverage < 0.85`
- `high`
  - mature measurement
  - execution fill coverage >= 0.85
  - reconciliation healthy

## 8. wording
- healthy:
  - “Measured execution friction remains within current operating tolerance.”
- watch:
  - “Execution drag is still manageable but needs monitoring before trusting current post-cost assumptions.”
- degraded:
  - “Measured execution friction is materially weakening live confidence and should be treated as a real drag source.”
- insufficient:
  - “Current fill-ledger coverage is too thin to treat execution friction as measured and stable.”

## 9. non-goals
1. actual live stop / throttle execution
2. approval / sizing / rollout DB 자동 변경
3. exact per-symbol fee normalization beyond current sources
