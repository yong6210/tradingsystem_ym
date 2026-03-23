# Outcome-First Rollout Recommendation Contract

최종 갱신: 2026-03-23
상태: Item 1 baseline fixed

## 1. 목적
- 기존 family rollout policy는 그대로 source-of-truth로 유지한다.
- `score_to_outcome_funnel`, `family_execution_degradation_advisory`, `mode_advisory`, `operator_action_priority`를 종합해 `expand / hold / reduce / research_only` recommendation을 만든다.
- 이번 계약은 rollout policy를 자동 변경하지 않고, operator가 읽는 compare-only recommendation만 추가하도록 제한한다.

## 2. 입력 소스
rollout recommendation은 아래 입력만 사용한다.

1. `score_to_outcome_funnel_summary`
- source: validation / strategy engine summary
- 주 사용 필드:
  - `decomposition.family[*]`
  - `decomposition.regime[*]`
  - `decomposition.session[*]`
  - `historical_execution_outcomes.baseline_cost_profitable_rate_from_closed`

2. `family_execution_degradation_advisory_summary`
- source: validation / strategy engine summary
- 주 사용 필드:
  - `families[*].status`
  - `families[*].confidence`
  - `families[*].sample_note`
  - `families[*].reason_codes`

3. `mode_advisory_summary`
- source: validation / strategy engine summary
- 주 사용 필드:
  - `family[*].advisory_state`
  - `family[*].confidence`
  - `family[*].sample_note`
  - `family[*].blocking_signals`

4. `current rollout policy snapshot`
- source: rollout policy repository / bootstrap
- 주 사용 필드:
  - `live_enabled`
  - `max_execution_mode`
  - `max_risk_r`
  - `allowed_sessions`
  - `min_quality_score`

## 3. 출력 surface
이번 라운드에서 직접 노출하는 surface:

1. `validation_report`
- 새 top-level summary:
  - `rollout_recommendation_available`
  - `rollout_recommendation_summary`

2. `operations/checklist`
- 새 item:
  - `rollout_recommendation`

3. `execution/operator-dashboard`
- 새 summary:
  - `signal_funnel.rollout_recommendation`

비노출 surface:
- rollout policy DB row
- `ExecutionApproval`
- `approval_snapshot`
- `plan.validity`
- `/scanner/top`
- `/portfolio/budget`

즉 이번 recommendation은 `설명/제안` 계층이지 runtime authority가 아니다.

## 4. 신규 object shape
공통 이름:
- `rollout_recommendation`

```json
{
  "available": true,
  "advisory_only": true,
  "family": "trend_continuation",
  "recommendation": "expand|hold|reduce|research_only",
  "confidence": "low|medium|high",
  "maturity": "thin_sample|usable|mature",
  "summary": "family post-cost outcome is stable and execution degradation is healthy; keep expansion eligible but unchanged until more evidence accumulates",
  "reason_codes": [
    "family_outcome:positive",
    "family_execution:healthy",
    "mode_advisory:keep_current_mode"
  ],
  "current_policy": {
    "live_enabled": true,
    "max_execution_mode": "MICRO_LIVE",
    "max_risk_r": 1.0,
    "allowed_sessions": ["london", "new_york"],
    "min_quality_score": 75.0
  },
  "suggested_policy_delta": {
    "action": "keep|expand|reduce|research_only",
    "suggested_max_execution_mode": "MICRO_LIVE",
    "suggested_max_risk_r": 1.0,
    "change_hint": "no_change"
  },
  "source_summary": {
    "family_closed": 12,
    "family_baseline_cost_profitable_rate_from_closed": 0.58,
    "family_execution_status": "healthy",
    "family_mode_advisory_state": "keep_current_mode"
  }
}
```

## 5. recommendation 상태 해석
1. `expand`
- mature positive family post-cost evidence가 있고
- family execution degradation이 `healthy`
- family mode advisory가 `keep_current_mode` 또는 promotion-watch 성격
- 의미: 확대를 검토할 수는 있지만, 이번 라운드에서도 자동 변경은 하지 않는다

2. `hold`
- mixed evidence이거나
- thin sample이 아니지만 명확한 positive/negative가 아님
- 의미: 현재 rollout policy 유지가 기본

3. `reduce`
- family execution degradation이 `watch` 또는 `manual_review`
- 또는 family post-cost conversion이 weak
- 의미: rollout expansion을 멈추고 보수화를 검토

4. `research_only`
- family mode advisory가 `research_only`
- 또는 quality/advisory가 강하지만 rollout 확대 근거가 부족
- 의미: rollout policy 변경보다 research bucket 유지가 우선

## 6. 우선순위 규칙
recommendation 판단 순서는 아래로 고정한다.

1. `research_only`
- family mode advisory가 `research_only`
- 또는 sample이 얇고 negative/positive를 확정할 수 없음

2. `reduce`
- family execution degradation `watch/manual_review`
- family post-cost conversion weak

3. `expand`
- family mature positive post-cost evidence
- family execution healthy
- family mode advisory가 research-only가 아님

4. `hold`
- 위 세 조건에 해당하지 않는 기본 상태

즉 family 축이 최우선이고, regime/session은 family가 중립일 때만 summary 보조 근거로 사용한다.

## 7. suggested policy delta 규칙
`suggested_policy_delta`는 실제 변경값이 아니라 operator hint다.

허용 action:
- `no_change`
- `expand_consideration`
- `reduce_consideration`
- `keep_research_only`

허용 범위:
- `suggested_max_execution_mode`
- `suggested_max_risk_r`

비허용:
- DB 자동 upsert
- live_enabled 자동 토글
- allowed_sessions 자동 수정

## 8. thin-sample 보호 규칙
아래 중 하나면 기본 recommendation은 `hold` 또는 `research_only`만 허용한다.

1. family `closed < minimum_matured_closed`
2. family execution confidence `low`
3. mode advisory sample note가 thin sample

즉 얇은 표본에서는 `expand`나 강한 `reduce`를 과감하게 내리지 않는다.

## 9. reason code 규칙
허용 prefix:
- `family_outcome:`
- `family_execution:`
- `mode_advisory:`
- `sample:`
- `policy:`

예시:
- `family_outcome:positive`
- `family_execution:watch`
- `mode_advisory:research_only`
- `sample:thin_family_closed`
- `policy:micro_live_cap_active`

## 10. 비목표
이번 계약에서 하지 않는 것:
1. rollout policy 자동 변경
2. approval state 직접 수정
3. `recommended_risk_r` 직접 수정
4. scanner / portfolio row에 recommendation 재노출
5. family 전체 hard disable 자동화

## 11. 구현 포인트
예상 수정 위치:
- `/Users/yumin/Documents/trading/app/services/validation_report.py`
- `/Users/yumin/Documents/trading/app/services/operational_checklist.py`
- `/Users/yumin/Documents/trading/app/services/execution_operator_dashboard.py`
- `/Users/yumin/Documents/trading/app/services/strategy_engine.py`
- `/Users/yumin/Documents/trading/app/services/family_rollout.py`

## 12. 완료 기준
1. recommendation이 rollout policy source-of-truth를 건드리지 않는다.
2. validation/checklist/dashboard가 같은 recommendation 의미를 공유한다.
3. thin sample bucket에서 공격적 recommendation이 나오지 않는다.
4. operator가 현재 policy와 suggested delta를 함께 읽을 수 있다.
