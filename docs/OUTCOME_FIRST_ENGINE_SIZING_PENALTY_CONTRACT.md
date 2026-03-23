# Outcome-First Engine Sizing Penalty Contract

최종 갱신: 2026-03-23
상태: Item 2 baseline fixed

## 1. 목적
- 현재 `recommended_risk_r`는 `position_sizing -> strategy_mode -> portfolio overlay` 순으로 계산된다.
- 이번 계약은 기존 sizing factor를 바꾸지 않고, 그 뒤에 `outcome-aware risk allowance`를 additive layer로 붙인다.
- 목표는 `구조적으로 좋아 보이지만 post-cost outcome / execution 상태가 나쁜 후보`의 size를 자동으로 보수화하는 것이다.

## 2. 기존 source-of-truth 유지
기존 source-of-truth는 유지한다.

1. 원본 sizing 계산:
- `PositionSizingService.evaluate()`
- grade / regime / reaction / thesis / entry_model factor

2. mode sizing:
- `StrategyModeService.apply_to_sizing()`

3. 최종 후보 risk:
- `strategy_sizing.final_risk_r`
- `recommended_risk_r`

이번 라운드에서는 위 구조를 없애지 않는다.
대신 아래 필드를 추가한다.

- `strategy_sizing.base_final_risk_r`
- `strategy_sizing.outcome_risk_adjustment`
- `strategy_sizing.final_risk_r`는 outcome penalty 반영 후 값으로 갱신

## 3. 입력 소스
sizing penalty는 아래 입력만 사용한다.

1. `family_execution_degradation_advisory_summary`
- family별 status / recommended_action / reason_codes

2. `mode_advisory_summary`
- bucket state / blocking_reasons / why

3. `score_to_outcome_funnel_summary`
- family / regime / session decomposition
- 특히 `baseline_cost_profitable_rate_from_closed`
- `profitable_rate_from_closed`
- `closed`

## 4. 적용 위치
직접 적용 위치:

1. `plan.validity.strategy_sizing`
2. `plan.validity.recommended_risk_r`
3. `/scanner/top` row의 `strategy_sizing`, `recommended_risk_r`
4. `/portfolio/budget` row의 `strategy_sizing`, `recommended_risk_r`
5. execution intent의 `quality_snapshot.recommended_risk_r`

이번 item에서 비적용:
- validation report top-level recommendation
- approval state 자체
- portfolio hard block reason

## 5. 신규 object shape
`strategy_sizing.outcome_risk_adjustment`

```json
{
  "available": true,
  "applied": true,
  "status": "healthy|watch|manual_review",
  "penalty_tier": "none|soft_clamp|hard_clamp",
  "base_final_risk_r": 0.5,
  "multiplier": 0.75,
  "final_risk_r": 0.375,
  "reason_codes": [
    "family_execution_degradation:watch",
    "post_cost_conversion:weak_family_alignment"
  ],
  "summary": "family execution quality is drifting and post-cost conversion is weak; reduce live risk allowance",
  "source_summary": {
    "family_status": "watch",
    "mode_state": "watch",
    "family_closed_count": 12,
    "family_baseline_cost_profitable_rate_from_closed": 0.25
  }
}
```

## 6. penalty tier 규칙
1. `none`
- 충분한 데이터가 없거나 adverse signal이 없음
- multiplier = `1.0`

2. `soft_clamp`
- `watch` 수준 adverse signal
- multiplier는 `0.75`
- 목적: auto block이 아니라 보수화

3. `hard_clamp`
- `manual_review` 수준 adverse signal 또는 family post-cost deterioration이 명확
- multiplier는 `0.5`
- 단, `0.0`으로 만들지는 않는다

## 7. thin-sample 보호 규칙
아래 경우에는 penalty를 적용하지 않는다.

1. decomposition bucket `closed < minimum_matured_closed`
2. funnel / degradation / mode advisory 중 핵심 입력이 unavailable
3. bucket은 나쁘지만 sample note가 `thin_sample`로 해석되는 경우

즉, sample이 얇은 구간에서는 `none`으로 남기고 reason만 남기지 않는다.

## 8. 우선순위 규칙
1. base sizing 계산
2. mode sizing 적용
3. outcome sizing penalty 적용
4. portfolio overlay / risk cap / block logic 적용

즉 outcome sizing penalty는 hard block보다 앞에서 risk allowance를 줄이지만, `block_reason` source-of-truth를 대체하지는 않는다.

## 9. penalty source 우선순위
1. family execution degradation
2. family post-cost outcome alignment
3. mode advisory
4. regime / session decomposition

해석 규칙:
- family 신호가 가장 우선
- regime / session은 family가 중립일 때만 clamp 강도를 보강
- 서로 충돌하면 더 보수적인 multiplier를 택한다

## 10. reason code 규칙
허용 prefix:
- `family_execution_degradation:`
- `post_cost_conversion:`
- `mode_advisory:`
- `session_outcome:`
- `regime_outcome:`

예시:
- `family_execution_degradation:manual_review`
- `post_cost_conversion:weak_family_alignment`
- `mode_advisory:watch`
- `session_outcome:london_underperforming`

## 11. 비목표
이번 계약에서 하지 않는 것:
1. outcome penalty로 `recommended_risk_r = 0` 강제
2. grade / regime / reaction factor 자체 재정의
3. portfolio cap을 outcome 하나로 대체
4. alpha research softened risk와 합쳐서 별도 source-of-truth 생성

## 12. 구현 포인트
예상 수정 위치:
- `/Users/yumin/Documents/trading/app/services/position_sizing.py`
- `/Users/yumin/Documents/trading/app/services/plan_generator.py`
- `/Users/yumin/Documents/trading/app/services/portfolio_risk_overlay.py`
- `/Users/yumin/Documents/trading/app/services/strategy_engine.py`
- `/Users/yumin/Documents/trading/app/schemas/api.py`

## 13. 완료 기준
1. outcome penalty가 `strategy_sizing`에 trace로 남는다.
2. `recommended_risk_r`가 penalty 반영 후 값으로 내려간다.
3. thin-sample 구간에서 과도한 clamp가 걸리지 않는다.
4. 기존 mode/hard-block semantics는 유지된다.
