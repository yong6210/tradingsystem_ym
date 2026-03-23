# Strategy Lifecycle Upgrade Patch Plan

최종 갱신: 2026-03-23
상태: Item 3 baseline fixed

## 1. 목적
- lifecycle summary를 validation / checklist / dashboard / README에 어떤 shape로 넣을지 먼저 고정한다.
- lifecycle을 새 authority로 번지지 않게 하고, 기존 rollout / research / capital allocator와 역할을 분리한다.

## 2. validation_report 반영안
반영 위치:
- existing operator/review summary cluster
- `outcome_control_trace`, `rollout_recommendation`, `opportunity_capture`, `capital_allocator`와 같은 레벨

추가 필드:
1. `strategy_lifecycle_available`
2. `strategy_lifecycle_summary`

markdown section:
- 제목: `## Strategy Lifecycle`
- 포함 필드:
  - `available`
  - `advisory_only`
  - `family`
  - `state`
  - `previous_state`
  - `transition_bias`
  - `confidence`
  - `summary`
  - `reason_codes`
  - `source_summary`

원칙:
- lifecycle은 rollout recommendation을 대체하지 않는다.
- lifecycle은 governance wording만 제공한다.
- `reason_codes`는 compact하게 유지하고 full decomposition은 다시 노출하지 않는다.

## 3. operations/checklist 반영안
반영 방식:
- 새 item 추가
- item id: `strategy_lifecycle`
- title: `Strategy Lifecycle`

성격:
- informational / governance review item
- 기본적으로 `blocking = false`

status rules:
1. unavailable
- `PASS`
- message: `strategy lifecycle unavailable; keep governance review informational only`

2. retired
- `WARN`
- message: live rotation off-ramp review 필요

3. degraded
- `WARN`
- message: probation/production family가 degraded governance state로 내려왔음을 review

4. probation
- `PASS`
- message: promotion 전 단계 관찰/운영 review

5. production
- `PASS`
- message: production governance posture 확인

6. research
- `PASS`
- message: research-led posture 확인

evidence fields:
- `available`
- `family`
- `state`
- `previous_state`
- `transition_bias`
- `confidence`
- `reason_codes`
- `source_summary`

source fields:
- `validation_report.strategy_lifecycle_available`
- `validation_report.strategy_lifecycle_summary.state`
- `validation_report.strategy_lifecycle_summary.transition_bias`
- `validation_report.strategy_lifecycle_summary.reason_codes`

## 4. dashboard 반영안
반영 위치:
- `signal_funnel.strategy_lifecycle`

원칙:
- aggregate summary만 노출
- candidate row, recent intents, portfolio drill-down으로는 퍼뜨리지 않음

포함 필드:
- `family`
- `state`
- `previous_state`
- `transition_bias`
- `confidence`
- `summary`
- `reason_codes`
- `source_summary`

역할:
- `rollout_recommendation`은 policy suggestion
- `strategy_lifecycle`은 governance posture
- `capital_allocator`는 scarce capital tilt

## 5. README 반영안
새 섹션:
- 제목: `Strategy Lifecycle`

삽입 위치:
- `Outcome-Aware Rollout Recommendation` 뒤
- `Opportunity Capture` 앞

요약 문장:
- ``alpha research + rollout recommendation + family execution + post-cost outcome -> strategy_lifecycle``

포함할 설명:
1. lifecycle state 집합
- `research / probation / production / degraded / retired`

2. transition bias 집합
- `promote / hold / degrade / retire / observe`

3. authority boundary
- governance layer only
- no direct approval / sizing / rollout DB mutation

4. operator surfaces
- validation, checklist, dashboard can expose `strategy_lifecycle_summary`

README Operator Surfaces 보강:
- `POST /validation/report`
  - `strategy_lifecycle_summary` 설명 1줄 추가
- `POST /operations/checklist`
  - `strategy_lifecycle` review item 추가
- `GET /execution/operator-dashboard`
  - `signal_funnel.strategy_lifecycle` 추가

## 6. 비반영 범위
이번 단계에서 넣지 않는 곳:

1. `ExecutionApproval`
2. `approval_snapshot`
3. `plan.validity`
4. `/scanner/top`
5. `/portfolio/budget` candidate rows
6. rollout policy DB row
7. capital allocator / opportunity capture object merge

## 7. wording guardrails
1. `retired`는 `family removal`이나 `delete` 언어로 쓰지 않는다.
2. `production`은 auto-expand처럼 읽히지 않게 한다.
3. `probation`은 `paper/live transition review` 성격으로 쓴다.
4. `research`는 failure가 아니라 evidence-collection posture로 쓴다.
5. lifecycle summary는 `rollout_recommendation`과 충돌하지 않게 `governance` 언어만 쓴다.
