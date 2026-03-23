# Opportunity Capture Contract

최종 갱신: 2026-03-23
상태: Item 1 baseline fixed

## 1. 목적
- `quality only` 해석을 보완하기 위해, 현재 엔진이 실제로 얼마나 기회를 포착하고 놓치는지 요약한다.
- 이번 계약은 approval, sizing, rollout policy를 바꾸지 않고 `관측/설명 계층`만 추가하도록 제한한다.

## 2. 입력 소스
opportunity capture는 아래 입력만 사용한다.

1. `score_to_outcome_funnel`
- source: validation / strategy engine summary
- 주 사용 필드:
  - `report_window_days`
  - `snapshot_selection.runtime_candidates`
  - `snapshot_selection.accepted_candidates`
  - `snapshot_selection.blocked_candidates`
  - `snapshot_selection.accept_rate`
  - `snapshot_selection.blocked_reason_counts`
  - `snapshot_selection.blocked_gate_group_counts`
  - `historical_execution_outcomes.submitted`
  - `historical_execution_outcomes.filled`
  - `historical_execution_outcomes.closed`
  - `historical_execution_outcomes.fill_rate_from_submitted`
  - `historical_execution_outcomes.close_rate_from_filled`
  - `decomposition.family[*]`
  - `decomposition.regime[*]`
  - `decomposition.session[*]`

2. `portfolio_budget`
- source: runtime portfolio report / operator dashboard
- 주 사용 필드:
  - `blocked_reason_counts`
  - `accepted_count`
  - `blocked_count`
- 목적:
  - validation summary에 없는 runtime blocked mix를 dashboard/checklist 설명에 보조로 붙일 때만 사용

3. `execution_quality_summary`
- source: dashboard / validation
- 주 사용 필드:
  - `fill_rate`
  - `fill_events_total`
- 목적:
  - throughput 부족이 단순히 signal scarcity인지 execution shortage인지 구분하는 보조 근거

## 3. 출력 surface
이번 라운드에서 직접 노출하는 surface:

1. `validation_report`
- 새 top-level summary:
  - `opportunity_capture_available`
  - `opportunity_capture_summary`

2. `operations/checklist`
- 새 item:
  - `opportunity_capture`

3. `execution/operator-dashboard`
- 새 summary:
  - `signal_funnel.opportunity_capture`

비노출 surface:
- `ExecutionApproval`
- `approval_snapshot`
- `plan.validity`
- `/scanner/top`
- `/portfolio/budget` candidate row
- rollout policy DB row

## 4. 신규 object shape
공통 이름:
- `opportunity_capture`

```json
{
  "available": true,
  "advisory_only": true,
  "summary": "throughput is constrained more by blocking than by fill failure; family signal flow remains thin",
  "report_window_days": 30,
  "trades_per_day": {
    "submitted": 0.30,
    "filled": 0.23,
    "closed": 0.20
  },
  "capture_rates": {
    "accept_rate": 0.42,
    "submit_rate_from_runtime": 0.25,
    "fill_rate_from_submitted": 0.78,
    "close_rate_from_filled": 0.86
  },
  "capture_gap": {
    "runtime_to_submit_gap": 0.17,
    "submit_to_fill_gap": 0.22,
    "fill_to_close_gap": 0.14
  },
  "blocked_mix": {
    "quality": 3,
    "structural": 2,
    "rollout": 2,
    "risk": 0,
    "safety": 0
  },
  "dominant_bottleneck": {
    "stage": "runtime_to_submit",
    "reason": "quality_blocking"
  },
  "family_focus": {
    "key": "trend_continuation",
    "runtime_candidates": 6,
    "accepted_candidates": 2,
    "submitted": 4,
    "filled": 3,
    "closed": 3,
    "accept_rate": 0.3333,
    "submit_rate_from_runtime": 0.6667,
    "fill_rate_from_submitted": 0.75
  },
  "regime_modifier": {
    "key": "range",
    "state": "positive"
  },
  "session_modifier": {
    "key": "dead_session",
    "state": "negative"
  }
}
```

## 5. 해석 원칙
1. `opportunity_capture`는 recommendation이 아니다.
- 의미:
  - `기회를 얼마나 잡는가`
  - `어디서 많이 막히는가`
  - `체결 부족이 진짜 execution issue인가`

2. `quality weakness`와 `throughput weakness`를 분리한다.
- 예:
  - accept_rate가 낮고 blocked mix가 quality 중심이면 `selection bottleneck`
  - accept_rate는 괜찮은데 fill_rate가 낮으면 `execution bottleneck`

3. thin activity는 자동으로 negative 해석하지 않는다.
- `submitted`, `filled`, `closed` 표본이 작으면 explanatory wording을 완화한다.

## 6. 주요 지표 정의
1. `trades_per_day`
- `submitted / report_window_days`
- `filled / report_window_days`
- `closed / report_window_days`

2. `submit_rate_from_runtime`
- `submitted / runtime_candidates`
- runtime candidate 대비 실제 submit throughput

3. `capture_gap`
- `runtime_to_submit_gap = 1 - submit_rate_from_runtime`
- `submit_to_fill_gap = 1 - fill_rate_from_submitted`
- `fill_to_close_gap = 1 - close_rate_from_filled`

4. `blocked_mix`
- 기본 source는 `blocked_gate_group_counts`
- 없는 경우 `blocked_reason_counts`를 gate group으로 재분류해 채운다

## 7. family / regime / session 우선순위
1. family를 headline으로 사용한다.
2. regime/session은 modifier로만 사용한다.
3. family headline 후보는 아래 우선순위로 선택한다.
- runtime_candidates가 가장 많은 bucket
- 그중 `capture_gap`이 큰 bucket
- 동률이면 `closed`가 더 많은 bucket 우선

## 8. dominant bottleneck 규칙
아래 중 gap이 가장 큰 stage를 `dominant_bottleneck.stage`로 둔다.

1. `runtime_to_submit`
- accept는 됐지만 submit까지 이어지지 않는 부족

2. `submit_to_fill`
- order submission 이후 fill shortage

3. `fill_to_close`
- filled 이후 close throughput 부족

reason 예시:
- `quality_blocking`
- `rollout_blocking`
- `execution_fill_shortfall`
- `thin_activity_window`

## 9. guardrails
이번 계약에서 하지 않는 것:
1. approval state 직접 수정
2. `recommended_risk_r` 직접 수정
3. rollout policy 직접 변경
4. threshold 자동 완화/강화

즉 `opportunity_capture`는 compare-only explanatory object다.

## 10. 구현 포인트
예상 수정 위치:
- `/Users/yumin/Documents/trading/app/services/validation_report.py`
- `/Users/yumin/Documents/trading/app/services/operational_checklist.py`
- `/Users/yumin/Documents/trading/app/services/execution_operator_dashboard.py`
- `/Users/yumin/Documents/trading/app/services/strategy_engine.py`
- 신규 helper service 추가 가능

## 11. 완료 기준
1. operator가 `signal scarcity`, `blocking-heavy selection`, `execution fill shortage`를 구분해서 읽을 수 있다.
2. quality 지표와 throughput 지표가 같은 surface에 공존한다.
3. 새 summary가 source-of-truth를 바꾸지 않는다.
