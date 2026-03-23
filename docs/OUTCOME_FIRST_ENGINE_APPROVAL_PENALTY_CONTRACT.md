# Outcome-First Engine Approval Penalty Contract

최종 갱신: 2026-03-23
상태: Item 1 baseline fixed

## 1. 목적
- 기존 approval pipeline의 hard gate는 유지한다.
- `score_to_outcome_funnel`, `execution_degradation_advisory`, `mode_advisory`를 approval 단계의 additive control layer로 연결한다.
- 이번 계약은 `deployment_go_no_go` source-of-truth를 바꾸지 않고, `approval_state / playbook surface / approval_reasons`에만 직접 영향을 주도록 제한한다.

## 2. 입력 소스
approval penalty는 아래 세 입력만 사용한다.

1. `execution_degradation_advisory_summary`
- source: strategy engine runtime bundle
- 주 사용 필드:
  - `status`
  - `recommended_action`
  - `reason_codes`
  - `sample_context`

2. `mode_advisory_summary`
- source: strategy engine runtime bundle
- 주 사용 필드:
  - `state`
  - `blocking_reasons`
  - `supporting_signals`
  - `why`

3. `score_to_outcome_funnel_summary`
- source: strategy engine runtime bundle
- 주 사용 필드:
  - `historical_execution_outcomes.baseline_cost_profitable_rate_from_closed`
  - `decomposition.family[*]`
  - `decomposition.regime[*]`
  - `decomposition.session[*]`

## 3. 출력 surface
이번 라운드에서 직접 노출하는 surface:

1. `ExecutionApproval`
- 새 additive object: `outcome_approval_penalty`
- 기존 `approval_reasons`에 outcome-related reason 추가 가능
- 기존 `approval_state`, `playbook_go_no_go`, `playbook_code`, `playbook_message`는 penalty 결과에 따라 downgrade 가능

2. `approval_snapshot`
- order intents / submissions / execution coordinator가 읽는 approval snapshot에 그대로 저장

비노출 surface:
- `/scanner/top`
- `/portfolio/budget`
- `plan.validity`
- `validation_report`
- `operations/checklist`

위 surface는 이번 item에서 shape만 확정하지 않는다. 이후 checklist item에서 별도 반영한다.

## 4. 신규 object shape
`ExecutionApproval.outcome_approval_penalty`

```json
{
  "available": true,
  "status": "healthy|watch|manual_review",
  "penalty_tier": "none|reason_only|downgrade_to_manual",
  "applied": true,
  "summary": "execution degradation and post-cost outcome signals require manual review before new live entries",
  "reason_codes": [
    "execution_degradation:manual_review",
    "mode_advisory:watch",
    "post_cost_conversion_weak"
  ],
  "source_summary": {
    "execution_degradation_status": "manual_review",
    "mode_advisory_state": "watch",
    "baseline_cost_profitable_rate_from_closed": 0.25
  }
}
```

## 5. 상태 해석 규칙
1. `healthy`
- penalty 없음
- base approval 결과 유지

2. `watch`
- 기본적으로 `reason_only`
- `approval_reasons`에는 추가되지만, base result가 `APPROVED_AUTO`여도 즉시 manual로 내리지는 않는다
- 단, 이후 sizing/overlay 단계에서 보수화 근거로 재사용할 수 있다

3. `manual_review`
- base result가 `APPROVED_AUTO`면 `APPROVED_MANUAL`로 downgrade
- base result가 이미 `BLOCKED`, `APPROVED_MANUAL`, `APPROVED_SHADOW`면 더 강한 제약을 유지한다
- `deployment_go_no_go`는 바꾸지 않고, approval/playbook layer만 manual review로 낮춘다

## 6. 우선순위 규칙
approval 판단 순서는 다음으로 고정한다.

1. 기존 hard block
- stale plan
- close-only
- safety lock
- runtime no-go
- operating lock closed
- portfolio hard block
- allowlist / rollout / validation hard block

2. 기존 soft approval downgrade
- rollout risk cap
- rollout min quality
- validation grade shortfall
- runtime manual review

3. outcome approval penalty
- base result가 `APPROVED_AUTO`인지 확인
- `manual_review` tier이면 `APPROVED_MANUAL`로 downgrade
- `watch` tier이면 reason only로 남긴다

즉 outcome penalty는 hard gate를 대체하지 않고, `auto-approval를 그대로 둘지`를 한 번 더 검토하는 계층이다.

## 7. reason code 규칙
허용 reason code prefix:
- `execution_degradation:`
- `mode_advisory:`
- `outcome_funnel:`
- `post_cost_conversion:`

예시:
- `execution_degradation:manual_review`
- `mode_advisory:watch`
- `outcome_funnel:low_closed_profit_rate`
- `post_cost_conversion:weak_baseline_conversion`

## 8. 비목표
이번 계약에서 하지 않는 것:
1. outcome penalty로 바로 `BLOCKED` 처리
2. `deployment_go_no_go` 원본 변경
3. `recommended_risk_r` 직접 수정
4. scanner / portfolio row에 approval penalty 재노출
5. family 전체를 hard disable하는 global kill switch 추가

## 9. 구현 포인트
예상 수정 위치:
- `/Users/yumin/Documents/trading/app/services/strategy_engine.py`
- `/Users/yumin/Documents/trading/app/services/execution_approval.py`
- `/Users/yumin/Documents/trading/app/schemas/api.py`
- `/Users/yumin/Documents/trading/app/schemas/execution.py`

## 10. 완료 기준
1. approval response가 outcome penalty trace를 포함한다.
2. `manual_review` tier는 auto-approved plan을 manual-approved로 낮춘다.
3. hard block semantics는 변하지 않는다.
4. order intent approval snapshot에도 동일 trace가 남는다.
