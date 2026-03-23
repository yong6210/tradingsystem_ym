# Opportunity Capture Patch Plan

최종 갱신: 2026-03-23
상태: Item 3 baseline fixed

## 1. 목적
- `opportunity_capture`를 validation / checklist / dashboard에 같은 의미로 노출하되, 새 authority처럼 보이지 않게 배치한다.
- 기존 `outcome_control_trace`, `rollout_recommendation`과 역할이 겹치지 않게 경계를 고정한다.

## 2. 공통 문구 원칙
1. `advisory_only`, `compare_only`, `throughput explanation` 성격을 유지한다.
2. `threshold 완화/강화 제안`처럼 읽히는 문장은 쓰지 않는다.
3. family를 headline으로 두고 regime/session은 modifier로만 붙인다.
4. `quality weakness`와 `throughput weakness`를 한 문장에 섞지 않는다.

## 3. Validation Report 반영안
### 3.1 top-level payload
추가 필드:
- `opportunity_capture_available`
- `opportunity_capture_summary`

### 3.2 markdown section
새 섹션 제목:
- `## Opportunity Capture`

### 3.3 section line shape
아래 수준까지만 노출한다.
- `available`
- `advisory_only`
- `summary`
- `report_window_days`
- `trades_per_day`
- `capture_rates`
- `capture_gap`
- `dominant_bottleneck`
- `family_focus`
- `regime_modifier`
- `session_modifier`
- `blocked_mix`

### 3.4 validation 역할
- 목적: validation artifact에서 `quality는 괜찮은데 throughput이 얇은지`, `selection에서 많이 막히는지`, `execution shortage인지`를 빠르게 읽게 하는 것
- 금지:
  - approval state 변경 문구
  - sizing 변경 문구
  - rollout policy 변경 문구

## 4. Operations Checklist 반영안
### 4.1 new item
- `item_id = "opportunity_capture"`
- title: `Opportunity Capture`
- category: `execution`

### 4.2 status semantics
1. `PASS`
- summary unavailable이 아니고
- `thin_activity_window` 또는 informational summary일 때

2. `WARN`
- `dominant_bottleneck.stage = runtime_to_submit` 이고
  reason이 `quality_blocking`, `rollout_blocking`, `structural_blocking`
- 또는 `submit_to_fill` 이고 `execution_fill_shortfall`

3. `MANUAL` / `FAIL`
- 이번 라운드에서는 사용하지 않음

### 4.3 checklist wording
- `quality gate를 낮추라`가 아니라
  - `selection bottleneck review`
  - `rollout bottleneck review`
  - `execution fill bottleneck review`
  같은 operator action wording만 허용

### 4.4 source fields
- `validation_report.opportunity_capture_available`
- `validation_report.opportunity_capture_summary.dominant_bottleneck`
- `validation_report.opportunity_capture_summary.capture_gap`
- `validation_report.opportunity_capture_summary.family_focus`
- `validation_report.opportunity_capture_summary.blocked_mix`

## 5. Operator Dashboard 반영안
### 5.1 insertion point
- `signal_funnel.opportunity_capture`

### 5.2 dashboard 역할
- aggregate summary만 보여준다.
- candidate row, recent intent row, position row에는 붙이지 않는다.

### 5.3 dashboard shape
- `available`
- `advisory_only`
- `summary`
- `trades_per_day`
- `capture_rates`
- `capture_gap`
- `dominant_bottleneck`
- `family_focus`
- `regime_modifier`
- `session_modifier`
- `blocked_mix`

### 5.4 dashboard 경계
- `score_to_outcome_funnel` raw decomposition 전체를 중복 노출하지 않는다.
- `outcome_control_trace`는 control chain 설명
- `rollout_recommendation`은 policy suggestion
- `opportunity_capture`는 throughput explanation

## 6. Surface ordering
1. validation report
- `Outcome Control Trace`
- `Outcome-Aware Rollout Recommendation`
- `Opportunity Capture`

2. checklist
- `Outcome Control Trace`
- `Rollout Recommendation`
- `Opportunity Capture`

3. dashboard `signal_funnel`
- `score_to_outcome_funnel`
- `outcome_control_trace`
- `rollout_recommendation`
- `opportunity_capture`

## 7. 비범위
이번 패치 계획에서 하지 않는 것:
1. `ExecutionApproval` 반영
2. `/scanner/top` 반영
3. `/portfolio/budget` candidate row 반영
4. approval / sizing / rollout policy 자동 수정
5. blocked reason raw list 전체 복제

## 8. 구현 포인트
예상 수정 위치:
- `/Users/yumin/Documents/trading/app/services/validation_report.py`
- `/Users/yumin/Documents/trading/app/services/operational_checklist.py`
- `/Users/yumin/Documents/trading/app/services/execution_operator_dashboard.py`
- `/Users/yumin/Documents/trading/app/services/strategy_engine.py`
- 신규 helper service 추가 가능

## 9. 완료 기준
1. validation / checklist / dashboard가 같은 `opportunity_capture` 언어를 쓴다.
2. operator가 `selection bottleneck`, `execution fill shortage`, `thin activity`를 한눈에 구분할 수 있다.
3. 새 summary가 outcome control trace나 rollout recommendation 역할을 침범하지 않는다.
