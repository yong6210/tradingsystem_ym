# Outcome-First Engine Validation And Operator Penalty Trace Design

최종 갱신: 2026-03-23
상태: Item 4 baseline fixed

## 1. 목적
- 현재 validation report, operational checklist, operator dashboard는 outcome / degradation / advisory를 각각 보여준다.
- 하지만 `이 신호가 approval / sizing / portfolio ordering에 어떻게 반영됐는지`를 한 덩어리로 보여주는 trace는 없다.
- 이번 설계의 목적은 같은 penalty chain을 세 surface에서 일관되게 읽게 만드는 것이다.

## 2. trace 원칙
1. trace는 새로운 source-of-truth가 아니다.
2. trace는 `설명 객체`다.
3. trace는 approval / sizing / portfolio 각 단계가 어떤 penalty를 적용했는지와 그 이유를 묶어 보여준다.
4. trace는 요약만 노출하고, 원본 decomposition payload 전체를 복붙하지 않는다.

## 3. 공통 object shape
공통 이름:
- `outcome_control_trace`

```json
{
  "available": true,
  "summary": "execution degradation triggered approval downgrade; family post-cost weakness reduced risk allowance; portfolio ordering bias stayed negative",
  "approval_penalty": {
    "status": "manual_review",
    "tier": "downgrade_to_manual",
    "applied": true,
    "reason_codes": [
      "execution_degradation:manual_review",
      "mode_advisory:watch"
    ]
  },
  "sizing_penalty": {
    "status": "watch",
    "tier": "soft_clamp",
    "applied": true,
    "multiplier": 0.75,
    "reason_codes": [
      "family_execution_degradation:watch",
      "post_cost_conversion:weak_family_alignment"
    ]
  },
  "portfolio_bias": {
    "tier": "negative",
    "applied": true,
    "score_delta": -2.5,
    "reason_codes": [
      "family_outcome:negative"
    ]
  },
  "source_summary": {
    "execution_degradation_status": "manual_review",
    "mode_advisory_state": "watch",
    "baseline_cost_profitable_rate_from_closed": 0.25
  }
}
```

## 4. surface별 반영
### 4A. validation report
반영 위치:
- `validation_report` payload top-level summary block

추가 필드:
- `outcome_control_trace_available`
- `outcome_control_trace_summary`

`outcome_control_trace_summary` 최소 필드:
- `approval_penalty_status`
- `approval_penalty_tier`
- `sizing_penalty_status`
- `sizing_penalty_tier`
- `sizing_multiplier`
- `portfolio_bias_tier`
- `portfolio_bias_score_delta`
- `top_reason_codes`
- `summary`

반영 이유:
- validation report는 최종 승인 전 문서이므로, operator가 penalty chain을 한 눈에 읽어야 한다.

### 4B. operational checklist
반영 위치:
- 새 checklist item `outcome_control_trace`

status 규칙:
1. approval penalty가 `downgrade_to_manual`이면 `WARN`
2. sizing penalty가 `hard_clamp`면 `WARN`
3. portfolio bias만 negative인 경우 `PASS` 또는 `WARN`이 아니라 evidence-only로 `PASS`

source:
- `/validation/report`

evidence:
- 위 summary object의 핵심 필드

반영 이유:
- checklist는 operator action surface라서 `지금 보수적으로 봐야 하는가`를 명확히 보여줘야 한다.

### 4C. operator dashboard
반영 위치:
1. `signal_funnel` 아래 새 summary `outcome_control_trace`
2. `portfolio_summary.accepted_candidates[*]`
3. `portfolio_summary.blocked_candidates[*]`

dashboard summary 최소 필드:
- `available`
- `approval_penalty_status`
- `sizing_penalty_status`
- `portfolio_bias_distribution`
- `top_reason_codes`
- `summary`

candidate row 최소 필드:
- `outcome_bias`
- `strategy_sizing.outcome_risk_adjustment`

approval penalty는 candidate row가 아니라 recent intents / approval snapshot 쪽에서 읽도록 한다.

## 5. 노출 우선순위
1. validation report: 전체 bucket 수준 요약
2. checklist: operator action 여부
3. dashboard: aggregate + candidate drill-down

즉 같은 정보를 surface 목적에 맞게 압축해서 보여주되, wording은 최대한 통일한다.

## 6. wording 규칙
항상 아래 표현을 사용한다.
1. `approval downgraded`
2. `risk allowance reduced`
3. `portfolio ordering bias`
4. `post-cost outcome weak`
5. `execution degradation elevated`

피해야 하는 표현:
1. `bad strategy`
2. `disable family`
3. `do not trade this family again`

이번 라운드는 hard-disable이 아니라 outcome-first control 강화 단계이기 때문이다.

## 7. 비목표
이번 설계에서 하지 않는 것:
1. validation report에 decomposition 테이블 전체 노출
2. checklist에서 세부 numeric threshold 전부 노출
3. dashboard에서 explanation object를 source-of-truth처럼 승격

## 8. 구현 포인트
예상 수정 위치:
- `/Users/yumin/Documents/trading/app/services/validation_report.py`
- `/Users/yumin/Documents/trading/app/services/operational_checklist.py`
- `/Users/yumin/Documents/trading/app/services/execution_operator_dashboard.py`
- `/Users/yumin/Documents/trading/app/schemas/api.py`

## 9. 완료 기준
1. validation report가 penalty chain 요약을 가진다.
2. checklist가 penalty chain을 운영 행동으로 번역한다.
3. dashboard가 aggregate summary와 candidate drill-down을 둘 다 제공한다.
4. 같은 penalty가 surface마다 다른 의미로 읽히지 않는다.
