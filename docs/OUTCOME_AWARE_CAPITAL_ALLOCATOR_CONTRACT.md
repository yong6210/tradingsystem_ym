# Outcome-Aware Capital Allocator Contract

최종 갱신: 2026-03-23
상태: Item 1 baseline fixed

## 1. 목적
- 기존 `recommended_risk_r`와 `outcome_risk_adjustment`의 source-of-truth 역할은 유지한다.
- 그 위에 portfolio layer 전용 `capital allocator`를 추가해, scarce capital을 어느 family에 더 실을지 / 덜 실을지를 명시적으로 표현한다.
- 이번 계약은 approval / rollout policy를 바꾸지 않고, portfolio allocation layer와 operator surface에만 직접 영향을 주도록 제한한다.

## 2. 입력 소스
allocator는 아래 입력만 사용한다.

1. `score_to_outcome_funnel_summary`
- source: strategy engine / validation summary
- 주 사용 필드:
  - `decomposition.family[*]`
  - `decomposition.regime[*]`
  - `decomposition.session[*]`
  - `historical_execution_outcomes.baseline_cost_profitable_rate_from_closed`

2. `family_execution_degradation_advisory_summary`
- source: strategy engine / validation summary
- 주 사용 필드:
  - `families[*].status`
  - `families[*].confidence`
  - `families[*].sample_note`

3. `mode_advisory_summary`
- source: strategy engine / validation summary
- 주 사용 필드:
  - `family[*].advisory_state`
  - `regime[*].advisory_state`
  - `session[*].advisory_state`

4. 현재 portfolio runtime state
- source: portfolio overlay / budget report
- 주 사용 필드:
  - accepted candidate rows
  - blocked candidate rows
  - current positions / exposure summary
  - family별 current allocated risk

## 3. 출력 surface
이번 라운드에서 직접 반영하는 surface:

1. `/portfolio/budget` candidate rows
- 새 allocator object와 `allocated_risk_r` 노출

2. `portfolio budget report`
- allocator summary 및 candidate-level allocator evidence

3. `execution/operator-dashboard`
- portfolio summary / signal funnel에 allocator summary 추가

4. `validation_report`
- top-level `capital_allocator_summary`

5. `operations/checklist`
- 새 `capital_allocator` item 또는 existing portfolio item evidence 확장

비노출 surface:
- `ExecutionApproval`
- `approval_snapshot`
- `plan.validity`
- `/scanner/top`
- `rollout policy` DB row

즉 allocator는 portfolio allocation layer와 operator explanation layer의 결합이지, pre-trade approval authority가 아니다.

## 4. 신규 object shape
공통 이름:
- `capital_allocator`

candidate row additive shape:

```json
{
  "available": true,
  "applied": true,
  "tier": "reduce|neutral|boost",
  "family": "sweep_reversal",
  "allocation_weight": 1.15,
  "risk_multiplier": 1.1,
  "base_recommended_risk_r": 0.5,
  "allocated_risk_r": 0.55,
  "summary": "family post-cost outcome is stable and execution quality is healthy; modestly increase capital allowance",
  "reason_codes": [
    "family_outcome:positive",
    "family_execution:healthy",
    "family_mode:keep_current_mode"
  ],
  "source_summary": {
    "family_closed": 14,
    "family_baseline_cost_profitable_rate_from_closed": 0.57,
    "family_execution_status": "healthy",
    "family_mode_advisory_state": "keep_current_mode",
    "regime_modifier_state": "neutral",
    "session_modifier_state": "positive"
  }
}
```

aggregate summary shape:

```json
{
  "available": true,
  "advisory_only": false,
  "allocator_state": "active",
  "family_focus": "sweep_reversal",
  "capital_pressure": "neutral|underallocated_positive|overallocated_negative",
  "summary": "capital allowance is tilted toward mature positive families and away from degraded negative families",
  "family_weights": [
    {
      "family": "sweep_reversal",
      "tier": "boost",
      "allocation_weight": 1.15
    }
  ]
}
```

## 5. allocator 의미 규칙
1. `allocation_weight`
- family 중심 capital tilt
- neutral = `1.0`
- boost > `1.0`
- reduce < `1.0`

2. `risk_multiplier`
- candidate row에 실제 적용되는 allocator multiplier
- `recommended_risk_r` 이후 portfolio layer에서만 곱한다

3. `allocated_risk_r`
- `recommended_risk_r * risk_multiplier`
- portfolio layer에서만 의미가 있다

4. `tier`
- `boost`
  - mature positive family
- `neutral`
  - insufficient evidence or mixed evidence
- `reduce`
  - degraded or weak post-cost family

## 6. 적용 위치 규칙
allocator는 아래 순서 뒤에 붙는다.

1. base sizing
2. outcome risk adjustment
3. session penalty / ordering bias
4. capital allocator

즉 allocator는 `recommended_risk_r`를 만드는 전략/리스크 로직을 대체하지 않고, portfolio layer의 최종 capital allowance를 조정한다.

정확한 관계:

```text
base plan sizing
-> outcome risk clamp
= recommended_risk_r

recommended_risk_r
-> capital allocator multiplier
= allocated_risk_r
```

## 7. 우선순위 규칙
allocator 판단 우선순위는 아래로 고정한다.

1. family outcome / execution / mode
2. regime modifier
3. session modifier
4. current family capital pressure

즉 family가 1차 축이고, regime/session은 family가 neutral 또는 mixed일 때만 보조 수정값으로 사용한다.

## 8. thin-sample 보호 규칙
다음이면 기본 tier는 `neutral`만 허용한다.

1. family closed sample 부족
2. family execution confidence 낮음
3. mode advisory sample note가 thin sample

즉 thin sample에서는 `boost`도 `strong reduce`도 과감하게 주지 않는다.

## 9. 하드 가드레일
allocator는 아래를 우회하지 못한다.

1. existing portfolio hard blocks
2. thesis duplicate / cap reached / sizing zero
3. mode shadow-only
4. approval manual/block state

즉 allocator는 capital tilt이지, block override가 아니다.

## 10. reason code 규칙
허용 prefix:
- `family_outcome:`
- `family_execution:`
- `family_mode:`
- `regime_modifier:`
- `session_modifier:`
- `capital_pressure:`
- `sample:`

예시:
- `family_outcome:positive`
- `family_execution:manual_review`
- `family_mode:research_only`
- `capital_pressure:underallocated_positive`

## 11. 비목표
이번 계약에서 하지 않는 것:
1. approval state 직접 변경
2. rollout policy DB 자동 수정
3. scanner ranking 재정의
4. allocator만으로 신규 hard block 추가
5. family/regime/session별 정적 quota table 강제

## 12. 구현 포인트
예상 수정 위치:
- `/Users/yumin/Documents/trading/app/services/portfolio_risk_overlay.py`
- `/Users/yumin/Documents/trading/app/services/portfolio_budget_report.py`
- `/Users/yumin/Documents/trading/app/services/execution_operator_dashboard.py`
- `/Users/yumin/Documents/trading/app/services/validation_report.py`
- `/Users/yumin/Documents/trading/app/services/operational_checklist.py`
- `/Users/yumin/Documents/trading/app/schemas/api.py`

## 13. 완료 기준
1. candidate row가 `recommended_risk_r`와 별도로 `allocated_risk_r`를 가진다.
2. operator가 family 중심 capital tilt를 읽을 수 있다.
3. thin sample에서는 allocator가 neutral로 유지된다.
4. allocator가 approval / sizing / rollout authority를 대체하지 않는다.
