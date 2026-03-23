# Forward Stress Regime Validation Upgrade Contract

최종 갱신: 2026-03-24
상태: Item 1 baseline fixed

## 1. 목적
- `forward_stress_regime_validation`은 current validation evidence가 forward-like proxy, stress approximation, replay lineage, regime/session split까지 포함해 얼마나 일반화 가능해 보이는지 읽는 compare-only summary다.
- 이 계층은 approval / rollout / sizing authority를 직접 바꾸지 않고, generalization confidence를 같은 operator language로 읽게 만드는 것이 목적이다.
- 이 계층은 `walk_forward`, `strategy_v2_validation`, `strategy_v2_stress_validation`, `strategy_v2_stress_replay_assessment`, `strategy_v2_stress_replay_lineage`를 대체하지 않고 그 결과를 압축한다.

## 2. 허용 overall state
허용값은 아래 넷으로만 고정한다.
1. `validated_generalization`
2. `fragile_generalization`
3. `insufficient_generalization`
4. `insufficient_evidence`

추가로 validation bias는 아래 넷만 허용한다.
1. `support_current_validation`
2. `monitor_regime_stress_fragility`
3. `reduce_deployment_confidence`
4. `gather_more_validation_evidence`

`coverage_state`는 아래 셋만 허용한다.
1. `mature_validation`
2. `usable_validation`
3. `thin_validation`

## 3. required field
summary object는 아래 필드만 허용한다.
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

## 4. 직접 입력 source 범위
직접 입력 source는 아래 범위만 허용한다.
1. `walk_forward`
2. `strategy_v2_validation`
3. `strategy_v2_stress_validation`
4. `strategy_v2_stress_replay_assessment`
5. `strategy_v2_stress_replay_lineage`

원칙:
1. `walk_forward`는 current runtime에 이미 있는 forward-like proxy source-of-truth다.
2. `strategy_v2_validation`은 regime/session split과 preferred live mode context의 primary source다.
3. `strategy_v2_stress_validation`은 stressed downside와 replay divergence gate context의 primary source다.
4. `strategy_v2_stress_replay_assessment`는 approximation 유지 가능 여부와 replay follow-up pressure의 primary source다.
5. `strategy_v2_stress_replay_lineage`는 replay lineage coverage와 runtime-input thinness를 읽는 guardrail source다.

## 5. 직접 반영 surface
직접 반영 가능한 surface는 아래만 허용한다.
1. `validation_report`
2. `operations/checklist`
3. `execution/operator-dashboard`
4. `README`

## 6. 비반영 surface
아래에는 직접 반영하지 않는다.
1. `ExecutionApproval`
2. `approval_snapshot`
3. `recommended_risk_r`
4. `/scanner/top`
5. `/portfolio/budget` candidate row
6. rollout policy DB row
7. `operator_action_priority` hard ordering override

## 7. guardrail
1. `walk_forward.trades == 0` 또는 validation/stress payload가 비어 있으면 `validated_generalization`을 금지한다.
2. stress or replay weakness가 있어도 이 계층이 곧바로 live stop authority가 되지는 않는다.
3. `replay_followup_required`는 true market replay runner 즉시 전환을 뜻하지 않고, approximation confidence가 제한적이라는 뜻이다.
4. regime/session split이 특정 bucket 편향으로만 좋아 보여도 공격적 `support_current_validation` wording은 금지한다.
5. 현재 `walk_forward`는 simple proxy이므로, 이번 라운드의 `validated_generalization`은 future full walk-forward engine을 대체하지 않는다.

## 8. language boundary
1. `execution_friction_measurement`는 live drag language다.
2. `forward_stress_regime_validation`은 generalization confidence language다.
3. `A/B edge validation`은 family-level alpha language다.
4. promotion stack은 governance / review language다.
5. 이 계층들은 서로 대체 관계가 아니다.
