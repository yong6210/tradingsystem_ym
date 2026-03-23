# Capture-Aware Operator Priority Patch Plan

최종 갱신: 2026-03-23
상태: Item 3 baseline fixed

## 1. 목적
- 기존 `operator_action_priority` surface를 capture-aware wording까지 읽도록 확장한다.
- `validation / checklist / dashboard`가 같은 `priority_source`, `action_family`, `capture_context`를 공유하게 만든다.
- `opportunity_capture` 원본 object는 throughput explanation layer로 그대로 남기고, priority surface만 실무 action 언어로 보강한다.

## 2. 반영 원칙
1. 새 top-level object를 만들지 않는다.
2. 기존 `operator_action_priority` summary shape를 유지하고 additive 필드만 추가한다.
3. `Opportunity Capture` item과 `Operator Action Priority` item의 역할을 분리한다.
4. capture-aware 필드는 hard block처럼 읽히지 않게 `supporting_signals`와 `capture_context` 중심으로 배치한다.

## 3. Validation Report 반영안
대상:
- `/Users/yumin/Documents/trading/app/services/validation_report.py`

기존 유지:
- `validation_report.operator_action_priority`
- `validation_report.operator_action_priority_summary`

추가 필드:
- `validation_report.operator_action_priority_summary.priority_source`
- `validation_report.operator_action_priority_summary.action_family`
- `validation_report.operator_action_priority_summary.capture_context`

markdown 반영:
- 기존 `## Operator Action Priority` 섹션 유지
- 아래 라인만 additive로 추가
  - `priority_source`
  - `action_family`
  - `capture_context.dominant_bottleneck`
  - `capture_context.family_focus`
  - `capture_context.maturity`

문구 원칙:
- top action이 capture-aware가 아니면:
  - `capture_context`는 supporting context로만 출력
- top action이 capture-aware면:
  - `top_reason`를 headline으로 유지
  - `priority_source = opportunity_capture`를 명시

## 4. Operations Checklist 반영안
대상:
- `/Users/yumin/Documents/trading/app/services/operational_checklist.py`

기존 유지:
- item id: `operator_action_priority`
- title: `Operator Action Priority`
- status mapping:
  - `urgent -> WARN`
  - `watch -> WARN`
  - `research -> PASS`
  - `monitor -> PASS`

evidence additive 필드:
- `priority_source`
- `action_family`
- `capture_context`

summary wording 규칙:
1. `priority_source = opportunity_capture`, `action_family = selection_review`
- 요약은 `selection bottleneck review` 성격

2. `priority_source = opportunity_capture`, `action_family = rollout_review`
- 요약은 `rollout bottleneck review` 성격

3. `priority_source = opportunity_capture`, `action_family = execution_review`
- 요약은 `execution fill / position resolution review` 성격

4. `priority_source = opportunity_capture`, `action_family = observe`
- 요약은 `activity window observe; do not overreact` 성격

guardrail:
- checklist는 새 separate item을 만들지 않는다.
- 기존 `Opportunity Capture` item은 그대로 informational throughput item으로 유지한다.

## 5. Operator Dashboard 반영안
대상:
- `/Users/yumin/Documents/trading/app/services/execution_operator_dashboard.py`

기존 유지:
- `signal_funnel.operator_action_priority`
- `signal_funnel.opportunity_capture`

추가 필드:
- `signal_funnel.operator_action_priority.priority_source`
- `signal_funnel.operator_action_priority.action_family`
- `signal_funnel.operator_action_priority.capture_context`

배치 원칙:
- `signal_funnel.operator_action_priority`는 action summary
- `signal_funnel.opportunity_capture`는 throughput summary
- 두 object를 merge하지 않는다

drill-down 금지:
- recent intents row
- portfolio candidate row
- approval snapshot

## 6. 테스트 반영안
대상:
- `/Users/yumin/Documents/trading/tests/test_validation_report.py`
- `/Users/yumin/Documents/trading/tests/test_operational_checklist.py`
- `/Users/yumin/Documents/trading/tests/test_execution_operator_dashboard.py`
- `/Users/yumin/Documents/trading/tests/test_api_smoke.py`

고정할 것:
1. validation summary에 `priority_source`, `action_family`, `capture_context` 존재
2. checklist evidence에 같은 필드 존재
3. dashboard `signal_funnel.operator_action_priority`에 같은 필드 존재
4. `Opportunity Capture` raw object는 별도 key로 계속 존재
5. top action이 execution/playbook일 때도 `capture_context`가 유지되는 케이스 1건

## 7. 비목표
이번 patch 단계에서 하지 않는 것:
1. 새 checklist item 추가
2. 새 validation top-level summary 추가
3. `Opportunity Capture` item 삭제 또는 merge
4. priority만 보고 approval/sizing/rollout state 변경

## 8. 완료 기준
1. validation / checklist / dashboard가 같은 capture-aware priority 필드를 공유한다.
2. `operator_action_priority`와 `opportunity_capture`의 역할이 섞이지 않는다.
3. operator가 `top action`과 `throughput context`를 한 화면에서 같이 읽을 수 있다.
