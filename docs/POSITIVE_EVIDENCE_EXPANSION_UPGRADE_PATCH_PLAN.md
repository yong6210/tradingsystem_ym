# Positive Evidence Expansion Upgrade Patch Plan

최종 갱신: 2026-03-23
상태: Item 3 baseline fixed

## 1. 목적
- `positive_evidence_expansion`을 validation / checklist / dashboard / README에 어떤 shape로 넣을지 먼저 고정한다.
- positive expansion을 approval / sizing / rollout authority로 번지지 않게 하고, 기존 rollout / lifecycle / allocator와 역할을 분리한다.

## 2. validation_report 반영안
반영 위치:
- existing operator/review summary cluster
- `rollout_recommendation`, `strategy_lifecycle`, `opportunity_capture`, `capital_allocator`와 같은 레벨

추가 필드:
1. `positive_evidence_expansion_available`
2. `positive_evidence_expansion_summary`

markdown section:
- 제목: `## Positive Evidence Expansion`
- 포함 필드:
  - `available`
  - `advisory_only`
  - `family`
  - `state`
  - `expansion_bias`
  - `confidence`
  - `summary`
  - `reason_codes`
  - `source_summary`

원칙:
- positive expansion은 rollout recommendation을 대체하지 않는다.
- positive expansion은 controlled review wording만 제공한다.
- `reason_codes`는 compact하게 유지하고 full family decomposition은 다시 노출하지 않는다.

## 3. operations/checklist 반영안
반영 방식:
- 새 item 추가
- item id: `positive_evidence_expansion`
- title: `Positive Evidence Expansion`

성격:
- informational / operator-review item
- 기본적으로 `blocking = false`

status rules:
1. unavailable
- `PASS`
- message: `positive evidence expansion unavailable; keep expansion review informational only`

2. `not_ready`
- `WARN`
- message: positive expansion language를 쓰기엔 guardrail이 남아 있음을 review

3. `hold`
- `PASS`
- message: positive evidence는 있으나 아직 controlled expansion review 이전 단계임을 확인

4. `expandable`
- `PASS`
- message: controlled expansion review candidate로 볼 수 있으나 auto-expand가 아님을 확인

evidence fields:
- `available`
- `family`
- `state`
- `expansion_bias`
- `confidence`
- `reason_codes`
- `source_summary`

source fields:
- `validation_report.positive_evidence_expansion_available`
- `validation_report.positive_evidence_expansion_summary.state`
- `validation_report.positive_evidence_expansion_summary.expansion_bias`
- `validation_report.positive_evidence_expansion_summary.reason_codes`

## 4. dashboard 반영안
반영 위치:
- `signal_funnel.positive_evidence_expansion`

원칙:
- aggregate summary만 노출
- candidate row, recent intents, approval snapshot, portfolio drill-down으로는 퍼뜨리지 않음

포함 필드:
- `family`
- `state`
- `expansion_bias`
- `confidence`
- `summary`
- `reason_codes`
- `source_summary`

역할:
- `rollout_recommendation`은 policy suggestion
- `strategy_lifecycle`은 governance posture
- `capital_allocator`는 scarce capital tilt
- `positive_evidence_expansion`은 controlled positive review language

## 5. README 반영안
새 섹션:
- 제목: `Positive Evidence Expansion`

삽입 위치:
- `Strategy Lifecycle` 뒤
- `Opportunity Capture` 앞

요약 문장:
- ``rollout recommendation + strategy lifecycle + family post-cost outcome + family execution -> positive_evidence_expansion``

포함할 설명:
1. state 집합
- `expandable / hold / not_ready`

2. expansion bias 집합
- `consider_expand / hold / do_not_expand`

3. authority boundary
- compare-only
- no direct approval / sizing / rollout DB mutation

4. operator surfaces
- validation, checklist, dashboard can expose `positive_evidence_expansion_summary`

README Operator Surfaces 보강:
- `POST /validation/report`
  - `positive_evidence_expansion_summary` 설명 1줄 추가
- `POST /operations/checklist`
  - `positive_evidence_expansion` review item 추가
- `GET /execution/operator-dashboard`
  - `signal_funnel.positive_evidence_expansion` 추가

## 6. 비반영 범위
이번 단계에서 넣지 않는 곳:

1. `ExecutionApproval`
2. `approval_snapshot`
3. `plan.validity`
4. `/scanner/top`
5. `/portfolio/budget` candidate rows
6. rollout policy DB row
7. capital allocator / rollout recommendation / lifecycle object merge

## 7. wording guardrails
1. `expandable`도 `auto-expand`처럼 쓰지 않는다.
2. `hold`는 positive evidence가 일부 있으나 아직 guardrail이 남았음을 명시한다.
3. `not_ready`는 failure보다 guardrail / evidence 부족 언어를 우선한다.
4. positive expansion summary는 rollout recommendation과 충돌하지 않게 `controlled review` 언어만 쓴다.
5. `capital_allocator`가 boost여도 positive expansion을 authority처럼 설명하지 않는다.
