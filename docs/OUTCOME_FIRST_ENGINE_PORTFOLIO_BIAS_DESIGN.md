# Outcome-First Engine Portfolio Overlay Bias Design

최종 갱신: 2026-03-23
상태: Item 3 baseline fixed

## 1. 목적
- 현재 portfolio overlay는 `exposure / correlation / volatility / cap` 중심의 risk suppression layer다.
- 이번 설계의 목적은 이 위에 `outcome-weighted priority bias`를 얹어서, 같은 구조 품질이면 실제 post-cost outcome이 더 좋은 bucket을 앞에 두는 것이다.
- 기존 hard block과 cap 로직은 유지한다.

## 2. 현재 구조 인식
현재 overlay는 다음 순서로 동작한다.

1. `base_score = final_rank_score`
2. correlation / volatility / regime / exposure penalty 계산
3. `adjusted_rank_score = base_score - penalty`
4. `final_rank_score = adjusted_rank_score - session_penalty`
5. hard blocks 적용

즉 현재는 `좋아 보이는 후보를 얼마나 위험하게 담을지`는 계산하지만, `실제로 돈 되는 bucket에 우선권`을 주는 bias는 없다.

## 3. 설계 원칙
1. outcome bias는 새 hard gate가 아니다.
2. outcome bias는 `adjusted_rank_score` 이후, final ordering 전에 additive score bias로 붙인다.
3. score bias는 기존 risk penalty를 상쇄하지 못하게 제한한다.
4. family 신호를 최우선으로 보고, regime / session은 보조 bias로만 사용한다.
5. thin sample bucket에는 bias를 적용하지 않는다.

## 4. 신규 필드
candidate row / portfolio candidate row에 아래 필드를 추가한다.

1. `outcome_bias_score`
- additive numeric bias
- positive면 우선순위 상승
- negative면 우선순위 하락

2. `outcome_bias`

```json
{
  "available": true,
  "applied": true,
  "tier": "neutral|positive|negative",
  "score_delta": 2.5,
  "summary": "family post-cost conversion is stable and this session is not underperforming",
  "reason_codes": [
    "family_outcome:positive",
    "session_outcome:neutral"
  ],
  "source_summary": {
    "family_closed": 18,
    "family_baseline_cost_profitable_rate_from_closed": 0.44,
    "regime_closed": 9,
    "session_closed": 7
  }
}
```

3. `pre_outcome_final_rank_score`
- outcome bias 적용 전의 기존 `final_rank_score`

4. `post_outcome_final_rank_score`
- outcome bias 적용 후 최종 정렬 점수

## 5. 적용 위치
직접 적용:
1. `PortfolioRiskOverlayService.assess_rows()`
2. `/portfolio/budget` accepted / blocked candidate rows
3. portfolio budget report
4. operator dashboard의 portfolio / funnel surface

비적용:
1. `plan.validity`
2. `/scanner/top`
3. `ExecutionApproval`

scanner는 전략 후보 관점이고, outcome bias는 portfolio allocation layer의 의미가 더 크므로 이번 라운드에서는 portfolio 한정으로 둔다.

## 6. bias 계산 규칙
입력 소스:
1. `score_to_outcome_funnel_summary`
2. `family_execution_degradation_advisory_summary`
3. `mode_advisory_summary`

계산 순서:
1. family baseline cost conversion 평가
2. family degradation 상태 평가
3. regime baseline cost conversion 평가
4. session baseline cost conversion 평가
5. 결과를 하나의 `score_delta`로 합성

기본 규칙:
1. family positive
- post-cost conversion이 충분히 좋고 degradation이 healthy
- `+2.5`

2. family negative
- post-cost conversion이 약하거나 degradation이 watch/manual_review
- `-2.5`

3. regime/session positive
- family가 neutral 이상일 때만 보조 가산
- 각 `+0.5`

4. regime/session negative
- family가 negative가 아니어도 보조 감산 가능
- 각 `-0.5`

최종 clamp:
- `score_delta`는 `[-3.0, +3.0]`으로 제한

## 7. thin-sample 보호 규칙
다음이면 해당 축은 neutral 처리한다.
1. closed sample 부족
2. decomposition unavailable
3. baseline_cost_profitable_rate_from_closed unavailable

즉, 모르는 bucket을 좋다/나쁘다로 밀지 않는다.

## 8. 우선순위 규칙
1. risk penalty가 먼저
2. session penalty가 다음
3. outcome bias가 마지막 ordering bias

정확한 수식:

```text
base_score
  - portfolio_penalty
  - session_penalty
  + outcome_bias_score
= post_outcome_final_rank_score
```

단, outcome bias는 아래를 우회하지 못한다.
- thesis duplicate block
- cap reached
- sizing zero
- mode total risk exceeded
- shadow only

## 9. accepted/blocked 해석 규칙
1. accepted selection
- hard blocks 통과한 후보 사이에서 `post_outcome_final_rank_score`로 우선 정렬

2. blocked candidates
- accepted 여부는 그대로 block reason에 의해 결정
- 다만 blocked row에도 `outcome_bias`를 남겨 operator가 “좋았지만 cap에 막혔는지 / 원래 outcome도 약한지”를 읽을 수 있게 한다

## 10. report / dashboard 반영 원칙
portfolio budget report와 operator dashboard에는 아래만 노출한다.
1. `outcome_bias_score`
2. `outcome_bias.tier`
3. `outcome_bias.reason_codes`
4. `pre_outcome_final_rank_score`
5. `post_outcome_final_rank_score`

세부 decomposition row 전체를 복붙하지 않는다.

## 11. 비목표
이번 설계에서 하지 않는 것:
1. outcome bias 하나로 portfolio block
2. poor family 전면 disable
3. scanner ranking 자체 재정의
4. family/regime/session별 capital allocation quota 도입

## 12. 구현 포인트
예상 수정 위치:
- `/Users/yumin/Documents/trading/app/services/portfolio_risk_overlay.py`
- `/Users/yumin/Documents/trading/app/services/portfolio_budget_report.py`
- `/Users/yumin/Documents/trading/app/services/execution_operator_dashboard.py`
- `/Users/yumin/Documents/trading/app/schemas/api.py`

## 13. 완료 기준
1. hard-block을 건드리지 않고 accepted ordering이 outcome-aware가 된다.
2. operator가 outcome bias가 왜 붙었는지 읽을 수 있다.
3. thin-sample bucket은 neutral로 유지된다.
4. portfolio overlay가 여전히 risk-first 성격을 유지한다.
