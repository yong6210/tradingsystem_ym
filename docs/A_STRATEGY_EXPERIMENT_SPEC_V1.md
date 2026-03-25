# A Strategy Experiment Spec v1

최종 갱신: 2026-03-25
상태: First verified-edge experiment baseline

## 1. 목적
- 현재 A 전략의 첫 verified edge를 찾기 위한 실험 스펙을 고정한다.
- 구조 자체는 바꾸지 않고 `entry timing -> execution style -> exit review` 순서만 실험한다.
- live 결과를 `edge_experiment_review`, `edge_evolution_rule`, `review_followup_ledger`에 같은 vocabulary로 남긴다.
- 이 문서는 시스템을 fail-safe로 가정하지 않는다. 성패는 계속 `market_edge + execution_quality + operating_discipline`에 달려 있다고 본다.

## 2. 현재 문제 정의
현재 A 전략의 약점은 다음 3가지다.
1. `reaction_confirmed` 뒤에 들어가서 진입이 늦다.
2. 늦은 진입 때문에 손절 폭 대비 기대 보상이 줄어든다.
3. chop 구간에서 뒤늦은 confirm entry가 비용과 noise를 더 많이 먹는다.

이번 v1의 핵심 가설은 다음 한 줄이다.

`reaction을 기다려서 진입하지 말고, 좋은 location/liquidity에서 작게 먼저 들어가고, reaction으로 유지 여부를 검증한다.`

## 3. 범위
이번 v1에서 live로 바꾸는 것은 `entry timing`과 그 다음 `execution style`뿐이다.

포함:
1. `sweep_reversal` anchor family의 entry timing split
2. `passive_limit vs market` execution style split
3. split review packet, ledger, validation, dashboard 해석 규칙

제외:
1. exit 최적화 live 변경
2. signal density tuning
3. multi-strategy expansion
4. B family 활성화
5. 구조 rewrite

## 4. 실험 순서
현재 엔진 contract와 동일하게 순서를 고정한다.

1. `entry_timing`
   - `early_limit`
   - `reaction_confirmed`
2. `execution_style`
   - `passive_limit`
   - `market`
3. `exit optimization`
   - live 변경 금지
   - shadow review만 허용

`edge_experiment_review.experiment_sequence.exit_optimization_allowed == false`면 exit 아이디어는 기록만 하고 live rule은 바꾸지 않는다.

## 5. 대상 전략군
우선 적용 family:
1. `sweep_reversal`

보류:
1. `trend_continuation`
2. `range_rotation`
3. `breakout_acceptance`

이 문서는 `A_ONLY` anchor edge를 먼저 증명하기 위한 스펙이다. multi-strategy mix 실험 문서가 아니다.

## 6. Setup Eligibility
다음 조건이 같이 맞을 때만 A 전략 실험 대상으로 본다.

1. `strategy_family == sweep_reversal`
2. HTF extreme 또는 session liquidity edge에서 설명 가능한 위치가 있다.
3. liquidity narrative가 명확하다.
4. invalidation이 zone 밖으로 짧게 정의된다.
5. `transition` / `shock`는 기본적으로 skip 또는 compare-only다.
6. session quality가 허용 구간이다.
7. thesis dedupe에 걸리지 않는다.
8. 비용 포함 기대값이 음수가 아니다.

추가 해석 규칙:
1. `OB/FVG`는 독립 신호가 아니라 execution zone이다.
2. `BOS/CHoCH`는 authority가 아니라 reaction evidence다.
3. session box는 location 보조 정보이지 독립 entry 이유가 아니다.

## 7. Branch Contract
### 7.1 Entry Timing Axis
axis 이름:
- `entry_timing`

variant:
1. `reaction_confirmed`
2. `early_limit`

packet action:
1. `run_entry_timing_split_review`
2. `promote_entry_timing_branch_review`

#### Control: `reaction_confirmed`
- 목적: 현재 confirm-after-reaction baseline 유지
- 진입 성격: reaction evidence가 나온 뒤 들어간다.
- runtime mapping:
  - `entry_timing_variant = reaction_confirmed`
  - `reaction_classification = rejection_confirmed`
  - `entry_model in {CONFIRM, SWEEP_CONFIRM}`

#### Treatment: `early_limit`
- 목적: 좋은 위치에서 먼저 들어가 RR을 키운다.
- 진입 성격: full confirm 이전에 zone 안쪽 limit로 먼저 배치한다.
- runtime mapping:
  - `entry_timing_variant = early_limit`
  - `entry_model = LIMIT`
  - `reaction_classification in {rejection_tentative, rejection_confirmed}`
- 금지:
  - `acceptance_confirmed`
  - `acceptance_tentative`
  - `mixed`

### 7.2 Execution Style Axis
axis 이름:
- `execution_style`

variant:
1. `passive_limit`
2. `market`

packet action:
1. `run_execution_style_split_review`
2. `promote_execution_style_branch_review`

실행 순서:
1. `entry_timing`이 directionally locked 되기 전에는 execution style split을 live로 열지 않는다.
2. `edge_experiment_review.experiment_sequence.state == execution_style_second`일 때만 이 축을 연다.

## 8. Entry Rules
### 8.1 `early_limit`
필수 조건:
1. HTF location alignment
2. liquidity sweep 또는 sweep 직전 유동성 접근
3. zone width와 invalidation이 짧게 정의됨
4. session quality 허용
5. thesis 중복 없음

실행 원칙:
1. entry는 zone 내부 passive limit
2. stop은 zone 바깥 invalidation
3. size는 baseline보다 공격적으로 늘리지 않는다
4. first objective는 win rate가 아니라 `avg_win / avg_loss` 개선이다

### 8.2 `reaction_confirmed`
필수 조건:
1. sweep 이후 reclaim/displacement 확인
2. `reaction_classification = rejection_confirmed`
3. same thesis still valid

실행 원칙:
1. current baseline을 유지한다
2. 비교축 역할을 하므로 임의 보정 없이 기록한다

## 9. Risk Rules
이번 v1에서 리스크 규칙은 보수적으로 유지한다.

1. `single_experiment_only`
2. `profit_claim_allowed == false` until proof posture is ready
3. `structure_change_review_allowed == false` until proof posture is ready
4. `early_loss_rewrite_embargo_active == true` while closed trades < 50
5. `rollout_expansion_allowed == false` until regime stability is confirmed

추가 운영 원칙:
1. `early_limit`가 더 공격적이더라도 initial risk cap은 baseline보다 높이지 않는다.
2. 초기 50 closes 전 손실만으로 variant를 rewrite하지 않는다.
3. `100` closed trades 전 edge claim을 하지 않는다.

## 10. Exit Handling
이번 v1에서 exit는 live 변경 대상이 아니다.

live:
1. 현재 runtime exit engine 유지
2. exit rule rewrite 금지

shadow-only hypotheses:
1. `fail_fast_no_reaction_within_3_bars`
2. `tp1_at_1r_then_scale`
3. `runner_after_internal_liquidity_take`

이 3개는 log/review 대상일 뿐이다. `experiment_sequence.exit_optimization_allowed == true`가 되기 전까지 live로 승격하지 않는다.

## 11. Evaluation Contract
primary KPI:
1. `true_edge_ratio`

secondary KPI:
1. `edge_decay_rate`
2. `regime_dependency_state`
3. `cost_adjusted_survival_rate`
4. `closed_trades_per_day`

success:
1. `true_edge_ratio > 1.10`
2. post-cost 기준
3. `closed_trade_count >= 100`
4. `regime_dependency_state != regime_dependent`

watch:
1. `1.00 <= true_edge_ratio <= 1.10`
2. sample still thin
3. strongest regime only improvement

fail:
1. `true_edge_ratio < 1.00` after meaningful sample
2. decay keeps worsening
3. weakest regime remains structurally negative

## 12. Operator Loop
daily:
1. `operator_action_priority`
2. `score_to_outcome_funnel_summary.operating_kpis`
3. `edge_experiment_review_summary.daily_edge_kpis`
4. `review_followup_ledger_summary`

packet generation:
```bash
./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_entry_timing_split_review
```

after entry timing lock:
```bash
./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --action run_execution_style_split_review
```

decision transition examples:
```bash
./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --transition-status ACKED
```

```bash
./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --universe usdc_perp_top30 --days 30 --transition-status PROMOTE_CONFIRMED
```

## 13. Runtime Tags
이미 runtime에서 읽히는 필드:
1. `strategy_family`
2. `entry_model`
3. `reaction_classification`
4. `entry_timing_variant`
5. `execution_style`
6. `recommended_risk_r`

이번 스펙의 해석용 권장 tag:
1. `strategy_spec_id = a_strategy_experiment_v1`
2. `entry_validation_mode = early_limit_pre_reaction` or `reaction_confirmed_post_reclaim`
3. `exit_review_deferred = true`

마지막 3개는 구현 시작 시 추가하면 되고, 현재 문서만으로도 split review/validation 해석은 가능하다.

## 14. Non-Negotiables
1. 한 번에 하나의 실험만
2. 100 closes 전 결론 금지
3. 초기 손실만으로 구조 rewrite 금지
4. regime stable 전 확장 금지
5. exit 최적화 선행 금지

## 15. Post-Proof Backlog
이 문서가 다루지 않는 v2 항목은 다음 4개다.

1. `alpha_generator_layer`
2. `capital_scale_curve`
3. `signal_density_controller`
4. `execution_strategy_automation`
5. `multi_strategy_activation`

이 4개는 `edge_experiment_review.operating_discipline.next_system_stage == post_first_verified_edge`일 때만 review 대상이 된다. 지금은 backlog이지 live 우선순위가 아니다.

## 16. 한 줄 요약
`A 전략 실험 v1은 sweep_reversal anchor에서 early_limit가 reaction_confirmed보다 after-cost true edge를 더 높일 수 있는지 검증하는 첫 edge-proof contract다.`
