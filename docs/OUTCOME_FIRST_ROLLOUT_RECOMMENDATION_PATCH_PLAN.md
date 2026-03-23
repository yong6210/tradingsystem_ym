# Outcome-First Rollout Recommendation Patch Plan

최종 갱신: 2026-03-23
상태: Item 3 baseline fixed

## 1. 목적
- rollout recommendation을 validation, checklist, dashboard에 같은 언어로 노출한다.
- 기존 `outcome_control_trace`, `mode_advisory`, `operator_action_priority`와 역할이 겹치지 않도록 반영 위치를 먼저 고정한다.

## 2. Validation Report 반영안
대상:
- `/Users/yumin/Documents/trading/app/services/validation_report.py`

반영 위치:
1. top-level payload summary
- 새 필드:
  - `rollout_recommendation_available`
  - `rollout_recommendation_summary`

2. markdown report body
- `operator_action_priority_lines`와 `outcome_control_trace_lines` 다음에
  - `rollout_recommendation_lines`
  - 제목 예시: `## Outcome-First Rollout Recommendation`

요약 문구 원칙:
- current policy와 suggested delta를 같이 보여준다.
- recommendation이 advisory-only라는 문장을 항상 포함한다.
- family recommendation을 headline으로 두고 regime/session modifier는 보조 줄로만 넣는다.

예상 summary shape:
```json
{
  "available": true,
  "family": "sweep_reversal",
  "recommendation": "hold",
  "confidence": "medium",
  "maturity": "usable",
  "summary": "family post-cost evidence is positive but not yet mature enough for expansion",
  "reason_codes": ["family_outcome:positive", "sample:usable_family_closed"],
  "current_policy": {
    "live_enabled": true,
    "max_execution_mode": "MICRO_LIVE",
    "max_risk_r": 1.0
  },
  "suggested_policy_delta": {
    "action": "no_change",
    "suggested_max_execution_mode": "MICRO_LIVE",
    "suggested_max_risk_r": 1.0,
    "change_hint": "keep_current_policy"
  },
  "top_modifier": {
    "axis": "session",
    "state": "positive"
  }
}
```

## 3. Operations Checklist 반영안
대상:
- `/Users/yumin/Documents/trading/app/services/operational_checklist.py`

반영 위치:
1. 새 item helper 추가
- item id:
  - `rollout_recommendation`

2. 체크 항목 순서
- `outcome_control_trace` 다음
- `pbo_dsr` 이전

상태 해석:
1. `PASS`
- recommendation이 `hold`
- 또는 `expand`지만 advisory-only/no-change 성격이고 current policy와 충돌 없음

2. `WARN`
- recommendation이 `reduce`
- 또는 `research_only`

3. `MANUAL`
- recommendation은 advisory-only이므로 이번 라운드에서 `FAIL`은 만들지 않는다.
- 다만 `reduce` + current policy가 live/micro_live 이상이면 operator review를 강하게 요구하는 `MANUAL` 후보로 둔다.

설명 문구 원칙:
- `current_policy -> suggested_policy_delta`를 한 줄로 보여준다.
- operator action은 `change now`가 아니라 `review` 문구를 사용한다.
- `outcome_control_trace`와 중복되는 approval/sizing/portfolio penalty detail은 다시 반복하지 않는다.

## 4. Execution Operator Dashboard 반영안
대상:
- `/Users/yumin/Documents/trading/app/services/execution_operator_dashboard.py`

반영 위치:
1. `signal_funnel` summary
- 새 필드:
  - `rollout_recommendation`

2. family-focused drill-down
- summary는 한 family headline만 보여주고
- candidate row나 recent intent row에는 recommendation을 직접 퍼뜨리지 않는다.

요약 문구 원칙:
- `recommendation`, `confidence`, `maturity`, `summary`, `reason_codes`
- `current_policy`, `suggested_policy_delta`
- optional `top_modifier`

경계:
- dashboard는 explanation surface다.
- rollout recommendation이 approval/sizing/portfolio ordering source-of-truth처럼 읽히지 않게 `advisory_only`를 유지한다.

## 5. 공통 wording 규칙
허용 표현:
- `compare-only`
- `advisory-only`
- `operator review`
- `current policy`
- `suggested delta`

피해야 할 표현:
- `auto promote`
- `auto expand`
- `policy changed`
- `runtime authority`

## 6. 기존 surface와의 역할 구분
1. `mode_advisory`
- family/regime/session별 mode evidence
- rollout recommendation의 입력 근거

2. `operator_action_priority`
- 지금 무엇을 우선 조치할지
- rollout recommendation보다 즉시성 우위

3. `outcome_control_trace`
- approval/sizing/portfolio control chain 설명
- rollout recommendation과 별개

4. `rollout_recommendation`
- current rollout policy를 어떻게 읽을지에 대한 compare-only suggestion

## 7. 구현 메모
예상 순서:
1. strategy layer에서 recommendation object 생성
2. validation payload에 summary 추가
3. checklist item 추가
4. dashboard signal_funnel 요약 추가
5. 테스트에서 wording/shape 고정

## 8. 완료 기준
1. 세 surface가 같은 recommendation object를 같은 의미로 보여준다.
2. advisory-only 성격이 문구상으로도 분명하다.
3. `outcome_control_trace`와 `rollout_recommendation`가 같은 뜻처럼 겹쳐 보이지 않는다.
