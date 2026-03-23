# Live Alpha Operating Routine

최종 갱신: 2026-03-24

## 1. 목적
- 이제 핵심 질문은 `설계가 좋은가`가 아니라 `after-cost 기준으로 실제 edge가 남아 있는가`다.
- 이 문서는 `A anchor`, `B diversification`, `execution friction`, `generalization`, `kill condition`을 같은 cadence로 점검하게 만든다.

## 2. 절대 KPI
운영자는 아래 3개를 먼저 본다.

1. `net pnl after cost`
2. `trade frequency`
3. `max drawdown`

설명이 필요할 때만 `regime/session split`, `execution friction`, `forward/stress/regime`, `kill condition`으로 내려간다.

## 3. Family Edge Review 명령
### 3.0 Combined Review
```bash
./.venv/bin/python scripts/run_live_alpha_operating_review.py --days 180
```

- 이 command는 A review, B review, 그리고 `한 달 운영하면 몇 R 구조인지`를 같은 report로 압축한다.
- report 기본 경로: `reports/validation/live_alpha_reviews/`

### 3.0A Replay Evidence Review
```bash
./.venv/bin/python scripts/run_replay_evidence_review.py \
  --symbol BTCUSDC \
  --days 180
```

- 이 command는 `historical closed plans + stress replay lineage/assessment`를 replay-proxy evidence로만 읽는다.
- `do_not_treat_as_live_confidence=true`가 기본 전제다.
- report 기본 경로: `reports/validation/replay_evidence_reviews/`

### 3.1 A Anchor
```bash
./.venv/bin/python scripts/run_strategy_family_edge_review.py \
  --family sweep_reversal \
  --peer-family trend_continuation \
  --days 45 \
  --no-write-report
```

### 3.2 B Diversification
```bash
./.venv/bin/python scripts/run_strategy_family_edge_review.py \
  --family trend_continuation \
  --peer-family sweep_reversal \
  --days 45 \
  --no-write-report
```

### 3.3 기록을 남길 때
```bash
./.venv/bin/python scripts/run_strategy_family_edge_review.py \
  --family sweep_reversal \
  --peer-family trend_continuation \
  --days 180

./.venv/bin/python scripts/run_strategy_family_edge_review.py \
  --family trend_continuation \
  --peer-family sweep_reversal \
  --days 180
```

- report 기본 경로: `reports/validation/edge_reviews/`
- `actual_money_basis`는 `post_cost_realized_r_baseline_adjusted`다.
- first-wave verdict는 `validated_edge / fragile_edge / insufficient_edge / insufficient_sample`만 허용한다.

## 4. Daily Routine
### 4.1 세션 시작
1. `GET /execution/operator-ui`와 `GET /execution/operator-dashboard`를 먼저 본다.
2. `Approval Divergence`, `Kill Condition Inspector`, `Runtime Quality Inspector`를 먼저 본다.
3. `POST /validation/report`, `POST /operations/checklist`로 최종 승인 posture를 확인한다.

### 4.2 짧은 edge 점검
매일은 `45d` 창만 본다.

- A review:
  - `edge_state`
  - `analysis_bias`
  - `target_metrics.ev`
  - `target_metrics.max_drawdown`
  - `trade_frequency.trades_per_30d`
- B review:
  - `edge_state`
  - `analysis_bias`
  - `diversification_proxy.correlation_state`
  - `diversification_proxy.drawdown_contribution_state`
  - `trade_frequency.trades_per_30d`

### 4.3 daily decision rule
- A가 `validated_edge`가 아니면 anchor 확대를 논하지 않는다.
- B가 `validated_edge`가 아니면 계속 guarded posture로 둔다.
- `execution_friction_measurement`가 `degraded_friction`이면 edge verdict보다 friction review를 먼저 한다.
- `kill_condition_automation`이 `observe_only`가 아니면 edge review보다 safety review를 먼저 한다.
- replay evidence는 참고만 하고, live 표본과 절대 합산하지 않는다.

## 5. Weekly Routine
주간 리뷰는 `90d` 창으로 한다.

1. A/B edge review report를 둘 다 생성한다.
2. `Execution Friction Measurement`를 다시 확인한다.
3. `Forward Stress Regime Validation`를 다시 확인한다.
4. `trade_frequency`, `post_cost ev`, `max drawdown`, `regime/session concentration`을 같이 본다.
5. 결론은 아래 4개 중 하나만 남긴다.
- `keep_a_anchor`
- `keep_b_guarded`
- `reduce_family_confidence`
- `gather_more_evidence`

주간 금지 규칙:
- threshold를 바꾸면서 mode도 같이 바꾸지 않는다.
- B를 한 번에 live anchor로 승격하지 않는다.
- friction/generalization이 나쁘면 family edge verdict 하나만 보고 확대하지 않는다.

## 6. Monthly Routine
월간 리뷰는 `180d` 창으로 한다.

1. combined live alpha operating review를 먼저 남긴다.
2. A/B edge review report를 둘 다 남긴다.
3. 필요하면 symbol별 replay evidence review를 같이 남긴다.
2. `promotion_governance`, `promotion_decision_brief`, `promotion_lifecycle_history`를 같이 본다.
3. `capital_allocator`, `strategy_cluster_balance`, `b_continuation_activation`까지 같이 본다.
4. 실제 운영 posture를 아래 중 하나로만 정리한다.
- `A anchor 유지`
- `B guarded continuation 유지`
- `family confidence 축소`
- `research / evidence accumulation 유지`

월간 금지 규칙:
- 한 달 안에 threshold를 두 번 이상 바꾸지 않는다.
- evidence 부족을 개선 신호로 오인하지 않는다.
- B diversification proxy를 exact correlation처럼 해석하지 않는다.

## 7. 운영 해석 원칙
- A review는 `anchor confidence`를 읽는 것이다. approval authority가 아니다.
- B review는 `diversification evidence`를 읽는 것이다. activation authority가 아니다.
- replay review는 `historical context`를 읽는 것이다. live confidence나 sizing authority가 아니다.
- `execution_friction_measurement`, `forward_stress_regime_validation`, `kill_condition_automation`은 edge verdict를 보완하는 safety layer다.
- `proposal_only`와 `explicit arm` 철학은 유지한다.

## 8. 추천 순서
1. `operator-ui`
2. `validation/checklist`
3. `execution_friction_measurement`
4. `forward_stress_regime_validation`
5. `live_alpha_operating_review`
6. `strategy_family_edge_review`
6. 필요할 때만 `kill condition live runbook`

## 9. 현재 기본 posture
- A는 `validated_edge`가 누적되기 전까지도 계속 post-cost 기준으로만 유지 여부를 판단한다.
- B는 `validated_edge + acceptable friction + acceptable generalization`이 동시에 유지되기 전까지 계속 guarded posture다.
- sample이 얇으면 해석보다 수집을 우선한다.
