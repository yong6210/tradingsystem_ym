# Capture-Aware Operator Priority Contract

최종 갱신: 2026-03-23
상태: Item 1 baseline fixed

## 1. 목적
- 기존 `operator_action_priority`의 source-of-truth 역할은 유지한다.
- `opportunity_capture`의 `dominant_bottleneck`, `family_focus`, `maturity`를 operator action language로 번역해 `무엇을 먼저 볼지`를 더 직접 보여준다.
- 이번 계약은 approval / sizing / rollout policy를 바꾸지 않고, `operator_action_priority` 설명 계층만 capture-aware로 확장하도록 제한한다.

## 2. 입력 소스
capture-aware priority는 아래 입력만 사용한다.

1. 기존 operator priority 입력
- source: `dashboard.signal_funnel`, `validation_report`, `operations checklist`
- 주 사용 필드:
  - `playbook_action`
  - `execution_degradation_advisory`
  - `family_execution_degradation_advisory`
  - `mode_advisory`
  - `alpha_research_recommended_action`
  - `alpha_research_softening_review`
  - `alpha_research_promotion_watchlist`

2. `opportunity_capture_summary`
- source: `dashboard.signal_funnel.opportunity_capture` 또는 `validation_report.opportunity_capture_summary`
- 주 사용 필드:
  - `dominant_bottleneck.stage`
  - `dominant_bottleneck.reason`
  - `family_focus.key`
  - `maturity`
  - `capture_gap`
  - `blocked_mix`

## 3. 출력 surface
이번 라운드에서 직접 반영하는 surface:

1. `operator_action_priority`
- 새 capture-aware 해석을 포함한 공통 summary object

2. `validation_report.operator_action_priority_summary`
- 기존 summary object에 capture-aware 필드 추가 가능

3. `operations/checklist`
- 기존 `Operator Action Priority` item이 capture-aware wording을 읽음

4. `execution/operator-dashboard`
- 기존 `signal_funnel.operator_action_priority`가 capture-aware summary를 읽음

비노출 surface:
- `ExecutionApproval`
- `approval_snapshot`
- `plan.validity`
- `/scanner/top`
- `/portfolio/budget`
- `rollout_recommendation`
- `opportunity_capture` 원본 object

즉 이번 계약은 기존 priority surface를 더 실무적으로 읽게 만드는 것이지, 새 authority object를 추가하는 것이 아니다.

## 4. 공통 object shape
기존 `operator_action_priority` summary shape는 유지하고, 아래 additive 필드만 허용한다.

```json
{
  "available": true,
  "top_action": "review_selection_bottleneck_before_threshold_changes",
  "top_reason": "runtime-to-submit throughput is constrained by quality blocking; family focus is trend_continuation",
  "priority_level": "watch",
  "priority_source": "opportunity_capture",
  "action_family": "selection_review",
  "supporting_signals": [
    "capture:runtime_to_submit:quality_blocking",
    "capture_family:trend_continuation",
    "execution:watch"
  ],
  "blocking_signals": [],
  "next_actions": [
    {
      "action": "review_execution_fill_shortage_before_strategy_changes",
      "reason": "submission-to-fill throughput remains below desired levels",
      "priority_level": "watch",
      "source": "opportunity_capture",
      "action_family": "execution_review",
      "advisory_only": true
    }
  ],
  "capture_context": {
    "available": true,
    "dominant_bottleneck": {
      "stage": "runtime_to_submit",
      "reason": "quality_blocking"
    },
    "family_focus": {
      "key": "trend_continuation"
    },
    "maturity": "usable_activity"
  },
  "advisory_only": true
}
```

새 additive 필드 의미:
- `priority_source`
  - 현재 top action이 어떤 계층에서 왔는지 명시
  - 허용값: `playbook|execution_degradation|family_execution_degradation|opportunity_capture|mode_advisory|alpha_research|monitor`
- `action_family`
  - top action의 operator action family
  - 허용값: `playbook|execution_review|selection_review|rollout_review|capacity_review|observe|mode_review|research|monitor`
- `capture_context`
  - top action이 capture-aware가 아니어도 summary 차원에서 보존되는 설명 객체

## 5. capture-aware action mapping
`opportunity_capture.dominant_bottleneck`는 아래 operator action으로 번역한다.

1. `stage = runtime_to_submit`, `reason = quality_blocking`
- `top_action`: `review_selection_bottleneck_before_threshold_changes`
- `action_family`: `selection_review`
- `priority_level`: `watch`

2. `stage = runtime_to_submit`, `reason = rollout_blocking`
- `top_action`: `review_rollout_constraints_before_threshold_changes`
- `action_family`: `rollout_review`
- `priority_level`: `watch`

3. `stage = runtime_to_submit`, `reason = structural_blocking`
- `top_action`: `review_structural_capacity_before_threshold_changes`
- `action_family`: `capacity_review`
- `priority_level`: `monitor`

4. `stage = runtime_to_submit`, `reason = selection_shortfall`
- `top_action`: `review_candidate_supply_before_threshold_changes`
- `action_family`: `selection_review`
- `priority_level`: `monitor`

5. `stage = submit_to_fill`, `reason = execution_fill_shortfall`
- `top_action`: `review_execution_fill_shortage_before_strategy_changes`
- `action_family`: `execution_review`
- `priority_level`: `watch`

6. `stage = submit_to_fill`, `reason = submission_to_fill_dropoff`
- `top_action`: `review_submission_to_fill_dropoff_before_strategy_changes`
- `action_family`: `execution_review`
- `priority_level`: `monitor`

7. `stage = fill_to_close`, `reason = fill_to_close_dropoff|position_resolution_delay`
- `top_action`: `review_position_resolution_delay_before_strategy_changes`
- `action_family`: `execution_review`
- `priority_level`: `monitor`

8. `reason = thin_activity_window`
- `top_action`: `observe_activity_window_before_threshold_changes`
- `action_family`: `observe`
- `priority_level`: `monitor`

## 6. 우선순위 규칙
top action 선택 우선순위는 아래로 고정한다.

1. `playbook`
- 기존 urgent playbook action이 있으면 최우선 유지

2. `execution_degradation`
- global execution `manual_review` / `watch`

3. `family_execution_degradation`
- family execution drag review

4. `opportunity_capture`
- capture-aware selection / rollout / execution / observe action

5. `mode_advisory`
- research-only / promotion-watch / watch

6. `alpha_research`
- softening / promotion watch / research action

7. `monitor`
- 더 강한 action이 없으면 `continue_runtime_monitoring`

즉 capture-aware priority는 `playbook`과 `execution degradation`을 덮지 않고, `mode/research`보다 앞에서 `실무 review order`를 제안하는 계층이다.

## 7. supporting / blocking signal 규칙
허용 signal prefix:
- `playbook:`
- `execution:`
- `family:`
- `mode:`
- `research:`
- `capture:`
- `capture_family:`
- `capture_maturity:`

예시:
- `capture:runtime_to_submit:quality_blocking`
- `capture_family:trend_continuation`
- `capture_maturity:usable_activity`

`blocking_signals`에는 hard authority를 암시하는 새 capture prefix를 넣지 않는다.
- capture-aware 계층은 action wording을 추가할 뿐, 새 block을 만들지 않는다.

## 8. thin-activity 보호 규칙
`maturity = thin_activity`이거나 `dominant_bottleneck.reason = thin_activity_window`면:

1. `priority_level`은 `monitor`까지만 허용
2. `action_family`는 `observe`
3. 요약 문구는 `observe / do not overreact` 성격으로 유지
4. `selection_shortfall`이나 `quality_blocking`으로 강한 해석을 내리지 않는다

즉 thin sample은 negative verdict가 아니라 `관측 부족`으로 처리한다.

## 9. 비목표
이번 계약에서 하지 않는 것:
1. capture-aware priority로 approval state 직접 수정
2. sizing / `recommended_risk_r` 직접 수정
3. rollout policy 자동 변경
4. `opportunity_capture` 원본 object를 candidate/intents row까지 재노출
5. throughput 부족을 이유로 threshold 자동 완화 제안

## 10. 구현 포인트
예상 수정 위치:
- `/Users/yumin/Documents/trading/app/services/operator_action_priority.py`
- `/Users/yumin/Documents/trading/app/services/strategy_engine.py`
- `/Users/yumin/Documents/trading/app/services/validation_report.py`
- `/Users/yumin/Documents/trading/app/services/operational_checklist.py`
- `/Users/yumin/Documents/trading/app/services/execution_operator_dashboard.py`
- `/Users/yumin/Documents/trading/tests/test_validation_report.py`
- `/Users/yumin/Documents/trading/tests/test_operational_checklist.py`
- `/Users/yumin/Documents/trading/tests/test_execution_operator_dashboard.py`

## 11. 완료 기준
1. `opportunity_capture`가 `operator_action_priority`의 review wording으로 연결된다.
2. operator는 `selection / rollout / execution / observe` action family를 구분해 읽을 수 있다.
3. thin activity는 negative verdict가 아니라 `observe`로 처리된다.
4. 기존 approval / sizing / rollout authority 경계는 유지된다.
