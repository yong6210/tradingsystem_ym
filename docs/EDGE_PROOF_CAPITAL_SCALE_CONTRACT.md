# Edge Proof Capital Scale Contract

최종 갱신: 2026-03-25
상태: Post-proof design contract

## 1. 목적
- 첫 verified edge가 나온 뒤 capital을 어떻게 늘릴지 보수적으로 정의한다.
- 이 계약은 `proof 이후`에만 열리며, proof 이전에는 review backlog로만 남는다.
- 목표는 수익 극대화보다 `verified edge를 drawdown으로 망치지 않는 것`이다.

## 2. 활성화 게이트
이 계약은 아래가 동시에 맞을 때만 review 가능하다.

1. `edge_experiment_review.operating_discipline.capital_scale_review_allowed == true`
2. `edge_experiment_review.edge_proof_posture.state == edge_claim_ready`
3. `edge_experiment_review.regime_dependency_state == stable_across_regimes`
4. `edge_experiment_review.experiment_sequence.execution_style_locked == true`
5. `edge_evolution_rule.recommended_action not in {reduce_baseline_allocation_review, review_edge_kill_condition}`
6. `kill_condition_automation.kill_condition_state`가 close-only 또는 kill-review 상태가 아님

즉 capital scale은 `proof 완료 + execution baseline lock + regime 안정` 이후에만 연다.

## 3. 비목표
이번 계약에서 하지 않는 것:

1. proof 이전 sizing 증가
2. approval authority 변경
3. rollout DB 자동 write
4. allocator hard block override
5. aggressive martingale / loss-recovery sizing

## 4. scale object
공통 이름:
- `post_proof_capital_scale`

권장 summary shape:

```json
{
  "available": true,
  "advisory_only": true,
  "scale_state": "baseline_locked|step_1_reviewable|step_2_reviewable|step_3_reviewable|scale_frozen|scale_reduced",
  "scale_bias": "hold|consider_step_up|freeze|reduce",
  "current_scale_multiplier": 1.0,
  "next_scale_multiplier": 1.1,
  "max_allowed_scale_multiplier": 1.5,
  "summary": "Edge proof is stable enough for the next conservative scale step, but only after drawdown and execution checks stay healthy.",
  "reason_codes": [
    "proof:edge_claim_ready",
    "regime:stable_across_regimes",
    "execution_style:locked",
    "drawdown:within_step_limit"
  ]
}
```

## 5. 적용 순서
capital scale은 기존 source-of-truth를 대체하지 않는다.

순서는 아래로 고정한다.

```text
base sizing
-> outcome clamp
= recommended_risk_r

recommended_risk_r
-> proof capital scale multiplier
= proof_scaled_risk_r

proof_scaled_risk_r
-> capital allocator multiplier
= allocated_risk_r
```

즉:
1. 전략 자체의 sizing 권한은 그대로 `recommended_risk_r`
2. proof 이후 family baseline scaling은 `capital scale`
3. scarce-capital family tilt는 `capital allocator`

## 6. conservative scale curve
증액은 단계형으로만 허용한다. 점프 업 금지.

### Step 0. Baseline Locked
- multiplier: `1.00x`
- 조건:
  - edge proof 직후
  - 아직 post-proof 운영 표본이 얇음
- 해석:
  - verified edge가 나와도 바로 size를 늘리지 않는다.

### Step 1. First Controlled Increase
- multiplier: `1.10x`
- 추가 조건:
  - proof 이후 추가 `20` closed trades
  - `true_edge_ratio >= 1.05`
  - drawdown deterioration 없음
  - execution quality 수동 검토 상태 아님

### Step 2. Reinforced Increase
- multiplier: `1.25x`
- 추가 조건:
  - Step 1 이후 추가 `30` closed trades
  - cumulative post-proof additional closes `>= 50`
  - `edge_decay_rate`가 악화되지 않음
  - `capital_allocator.tier in {neutral, boost}`

### Step 3. Max Safe Review
- multiplier: `1.50x`
- 추가 조건:
  - Step 2 이후 추가 `50` closed trades
  - cumulative post-proof additional closes `>= 100`
  - stress / friction / kill-condition warning 없음
  - operator review 통과

주의:
1. `1.50x`를 초과하는 scale은 이 계약 범위 밖이다.
2. 각 step은 최소 1 review cycle 이상 유지한다.
3. 한 번에 두 단계 이상 올리지 않는다.

## 7. drawdown control
증액보다 중요한 건 freeze / rollback 규칙이다.

### Freeze 조건
아래 중 하나면 다음 step review를 중단한다.

1. `true_edge_ratio < 1.0`
2. `edge_decay_rate <= -0.10`
3. `regime_dependency_state != stable_across_regimes`
4. execution advisory가 `manual_review`
5. kill-condition이 `close_only_review` 이상

### Reduce 조건
아래 중 하나면 직전 scale step으로 되돌린다.

1. recent post-proof sample에서 `true_edge_ratio < 0.95`
2. rolling drawdown이 직전 step 대비 명확히 확대
3. execution drag가 수익 개선보다 크게 증가
4. edge_evolution_rule가 `reduce_baseline_allocation_review`를 다시 권함

### Kill-Scale 조건
아래면 scale review 자체를 닫고 baseline 이하로 되돌린다.

1. `review_edge_kill_condition`
2. `KILL_REVIEW_ESCALATED`
3. replay/stress에서 catastrophic drawdown 근거가 다시 뜸

## 8. allocation rule
post-proof scale은 family baseline multiplier이고, allocator는 family tilt다.

권장 해석:
1. `capital scale`:
   - family baseline을 얼마나 늘릴지
2. `capital allocator`:
   - 현재 scarce capital을 어느 family에 상대적으로 더 줄지

예시:
```text
recommended_risk_r = 0.50R
capital_scale_multiplier = 1.10
capital_allocator_multiplier = 1.15

allocated_risk_r = 0.50 * 1.10 * 1.15 = 0.6325R
```

단, hard cap은 portfolio overlay가 계속 우선한다.

## 9. operator review order
capital scale review는 아래 순서로 본다.

1. `edge_experiment_review`
2. `edge_evolution_rule`
3. `execution_friction_measurement`
4. `forward_stress_regime_validation`
5. `positive_evidence_expansion`
6. `capital_allocator`
7. `promotion_decision_brief`

즉 `edge -> execution -> stress -> allocation` 순서다.

## 10. operator actions
권장 operator action language:

1. `hold_current_scale_review`
2. `promote_capital_scale_step_review`
3. `freeze_capital_scale_review`
4. `reduce_capital_scale_step_review`

이번 계약에서는 auto-write action을 열지 않는다.

## 11. one-line rule
`post-proof capital scale은 edge가 확인됐을 때 size를 키우는 절차가 아니라, verified edge를 drawdown 없이 천천히 확장하는 절차다.`
