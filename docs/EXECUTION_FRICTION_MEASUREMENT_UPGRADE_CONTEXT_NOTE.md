# Execution Friction Measurement Upgrade Context Note

최종 갱신: 2026-03-24
상태: complete

## 1. 왜 이 작업을 하는가
- 지금 시스템은 `execution_quality_summary`, `recent_reconciliation_summary`, `strategy_v2_stress_validation`까지는 올라와 있다.
- 하지만 실제 체결 friction이 현재 전략 edge를 얼마나 깎고 있는지, 이 실측을 얼마나 신뢰할 수 있는지, friction verdict를 어떤 language로 읽을지까지는 아직 분리돼 있지 않다.
- 이번 라운드 목적은 `실제 execution drag`를 compare-only evidence layer로 만드는 것이다.

## 2. 절대 규칙
1. raw source-of-truth는 계속 `execution_fills`, `zone_outcomes` fallback, `execution_reconciliation_events`, `strategy_v2_stress_validation`이다.
2. gross plan quality가 아니라 actual fill-rate / slippage / latency / fee / reconciliation / coverage를 우선한다.
3. thin measurement coverage는 공격적으로 해석하지 않는다.
4. 이번 라운드는 validate / compare / report 중심이고 auto-throttle authority는 나중에 분리한다.
5. `execution_quality_summary`와 `execution_friction_measurement`는 역할을 분리한다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `execution_quality`
2. `recent_reconciliation_summary`
3. `strategy_v2_stress_validation`
4. approval의 `expected_fee_bps`, `max_slippage_bps`
5. `outcome_control_trace`

아직 약한 것:
1. 실제 friction verdict를 한 summary로 읽는 operator language
2. fill-rate / slippage / latency / fee / reconciliation을 같은 layer로 묶는 구조
3. measurement coverage가 충분한지 읽는 공통 verdict

## 4. 적용 원칙
1. execution friction measurement는 새 authority가 아니라 evidence layer다.
2. validation / checklist / dashboard / README가 같은 `execution friction` language를 써야 한다.
3. friction이 나빠도 바로 approval / sizing / rollout DB를 자동 변경하지 않는다.
4. existing execution quality report를 대체하지 않고, 그 위의 summary verdict로만 추가한다.

## 5. 첫 라운드에서 보고 싶은 것
1. fill-rate가 현재 live confidence를 훼손하는 수준인가
2. slippage / latency / fee가 stress cost와 합쳐져 post-cost edge를 약하게 만드는가
3. reconciliation mismatch가 execution integrity를 흔드는가
4. 실제 실측 coverage가 충분한가

## 6. 다음 작업
1. 전체 완료

## 6A. Item 1 계약 결론
1. first-wave raw source는 `execution_quality`, `recent_reconciliation_summary`, `strategy_v2_stress_validation`, approval의 fee/slippage cap으로만 제한한다.
2. verdict state는 `healthy_friction / watch_friction / degraded_friction / insufficient_measurement` 네 개로만 고정한다.
3. friction bias는 `keep_execution_confidence / monitor_execution_drag / reduce_execution_confidence / gather_more_execution_evidence`로만 고정한다.
4. 세부 axis는 `fill_conversion_state`, `slippage_state`, `latency_state`, `fee_state`, `reconciliation_state`, `measurement_coverage_state`로만 제한한다.
5. direct surface는 validation / checklist / dashboard / README만 허용하고 approval / sizing / scanner / candidate row / rollout DB는 비범위로 둔다.
6. thin fill coverage, severe reconciliation mismatch, high slippage, high latency가 동시에 있는 상태에서는 공격적 `keep_execution_confidence` wording을 금지한다.

## 6B. Item 2 derivation 결론
1. measurement coverage는 `fills_matched`와 `execution_fill_coverage`를 같이 읽고 `thin / partial / mature`로 정규화한다.
2. slippage는 actual `slippage_bps.avg/p95`를 approval `max_slippage_bps` cap과 비교해 `healthy / watch / degraded`로 나눈다.
3. latency는 raw `entry_latency_seconds`보다 stress `latency_penalty_r`를 primary context로 두고, raw p95 seconds는 support-only threshold로 쓴다.
4. fee는 absolute fill fee가 아니라 stress `fee_component_r`를 primary metric으로 사용해 symbol/notional 왜곡을 피한다.
5. reconciliation은 `highest_severity`, `critical_count`, `lock_required_count`를 기준으로 integrity axis를 먼저 세우고, verdict precedence는 `insufficient_measurement -> degraded_friction -> watch_friction -> healthy_friction`로 고정한다.

## 6C. Item 3 patch 결론
1. validation에는 top-level `execution_friction_measurement_available`, `execution_friction_measurement_summary`, markdown section `## Execution Friction Measurement`를 추가하는 방향으로 고정한다.
2. checklist는 blocking이 아닌 informational item `Execution Friction Measurement`로만 반영하고, `watch_friction`과 `degraded_friction`에서만 `WARN` informational을 허용한다.
3. dashboard는 `signal_funnel.execution_friction_measurement` aggregate summary만 노출하고 candidate row나 approval snapshot으로 퍼뜨리지 않는다.
4. README는 existing execution quality 설명 뒤에 두어 `raw execution quality -> friction verdict -> strategy edge/promotion` 순서가 되게 정리한다.
5. 이번 단계에서도 approval / sizing / scanner / portfolio candidate row / rollout DB는 비범위로 유지한다.

## 6D. Item 4 구현 결론
1. 새 helper는 `execution_quality`, `recent_reconciliation_summary`, `strategy_v2_stress_validation`, approval fee/slippage cap reference를 읽고 `healthy_friction / watch_friction / degraded_friction / insufficient_measurement` verdict를 계산한다.
2. fill conversion, slippage, latency, fee drag, reconciliation, measurement coverage를 각각 정규화하고, stress drag는 support-only context로만 추가한다.
3. validation에는 top-level summary와 markdown section `## Execution Friction Measurement`가 추가되고, checklist에는 informational item, dashboard에는 `signal_funnel.execution_friction_measurement`가 추가된다.
4. approval / sizing / scanner / portfolio candidate row / rollout DB는 이번 단계에서도 건드리지 않는다.

## 6E. Item 5 테스트/문서 결론
1. helper unit test는 mature measured-drag 기준 `healthy_friction` case와 `degraded_reconciliation` precedence case를 직접 고정한다.
2. validation / checklist / dashboard / API smoke 테스트는 `execution_friction_measurement` 키 존재와 핵심 semantics(`friction_state`, `friction_bias`, `weakest_axis`)를 회귀로 묶는다.
3. README에는 `Execution Friction Measurement` 섹션과 operator surface 설명을 추가해 raw execution quality 뒤에 compare-only drag verdict를 명시한다.
4. 이번 단계도 approval / sizing / scanner / portfolio candidate row / rollout DB는 비범위로 유지한다.

## 6F. Item 6 self-check 결론
1. `execution_friction_measurement`는 helper, strategy engine wiring, validation report, checklist, dashboard, README, tests에만 존재하고 scanner / candidate row / approval / sizing / rollout DB로는 번지지 않았다.
2. raw source-of-truth는 계속 `execution_quality`, `recent_reconciliation_summary`, `strategy_v2_stress_validation`, approval fee/slippage cap reference로 유지된다.
3. `execution_quality_summary`는 raw operational metric, `execution_friction_measurement`는 live-confidence verdict라는 역할 분리가 유지된다.
4. helper unit test, surface 회귀, README 동기화까지 끝나 있어 이번 라운드는 compare-only execution drag evidence layer로 안전하게 닫아도 된다.
