# Execution Friction Measurement Upgrade Contract

최종 갱신: 2026-03-24

## 1. 목적
- `execution friction measurement`는 실제 체결 품질과 execution integrity가 현재 live confidence를 얼마나 훼손하는지 읽는 compare-only evidence summary다.
- 이 계층은 approval / sizing / rollout authority를 직접 바꾸지 않고, actual friction을 같은 operator language로 읽게 만드는 것이 목적이다.

## 2. raw source-of-truth
1. primary source는 `execution_quality.generate(...)` payload다.
2. integrity source는 `recent_reconciliation_summary`다.
3. stress context source는 `strategy_v2_stress_validation` payload다.
4. live approval cap reference는 `expected_fee_bps`, `max_slippage_bps`다.
5. `execution_friction_measurement`는 위 source를 요약할 뿐, raw report나 ledger를 대체하지 않는다.

## 3. 허용 상태
### 3.1 friction state
- `healthy_friction`
- `watch_friction`
- `degraded_friction`
- `insufficient_measurement`

### 3.2 friction bias
- `keep_execution_confidence`
- `monitor_execution_drag`
- `reduce_execution_confidence`
- `gather_more_execution_evidence`

### 3.3 axis
- `fill_conversion_state`
- `slippage_state`
- `latency_state`
- `fee_state`
- `reconciliation_state`
- `measurement_coverage_state`

## 4. 허용 input source
1. `execution_quality_summary`
2. `recent_reconciliation_summary`
3. `strategy_v2_stress_validation`
4. `outcome_control_trace` support-only context
5. approval fee/slippage cap reference

## 5. direct surface
허용:
1. validation
2. operational checklist
3. execution operator dashboard
4. README

비범위:
1. approval snapshot direct mutation
2. sizing authority direct mutation
3. scanner / portfolio candidate row direct field
4. rollout DB direct mutation
5. auto-throttle / auto-stop direct execution

## 6. wording 원칙
1. `healthy_friction`은 actual execution drag가 현재 허용 범위 안에 있고 integrity가 안정적일 때만 사용한다.
2. `watch_friction`은 fill conversion weakness, moderate slippage/latency, partial reconciliation noise, thin coverage를 뜻한다.
3. `degraded_friction`은 high drag 또는 integrity break를 뜻하지만, live stop authority 자체를 의미하지는 않는다.
4. `insufficient_measurement`는 execution이 healthy하다는 뜻이 아니라 evidence가 부족하다는 뜻이다.

## 7. guardrail
1. fill coverage가 thin하면 `healthy_friction`을 금지한다.
2. severe reconciliation mismatch가 있으면 다른 축이 좋아도 `healthy_friction`을 금지한다.
3. stress validation이 actual quality보다 보조 source가 더 많아도 `healthy_friction` confidence를 낮춘다.
4. approval cap reference는 support-only context이며, cap과 raw measured drag를 혼동하지 않는다.
5. 이번 라운드는 compare-only evidence layer이고, kill condition 자동화는 이후 단계로 분리한다.

## 8. operator interpretation
1. `execution quality summary`는 raw operational metrics다.
2. `execution friction measurement`는 그 raw metrics를 live confidence verdict로 재압축한 summary다.
3. 이 verdict는 전략 edge 검증을 보완하지만, approval / sizing / rollout authority를 직접 대체하지 않는다.
