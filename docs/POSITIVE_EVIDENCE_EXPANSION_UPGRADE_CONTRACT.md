# Positive Evidence Expansion Upgrade Contract

최종 갱신: 2026-03-23
상태: Item 1 baseline fixed

## 1. 목적
- strong positive family cluster를 `controlled expansion language`로 정규화한다.
- 기존 approval / sizing / rollout / capital allocator authority는 유지한 채, operator-facing summary만 추가한다.
- 이번 계약은 DB policy 자동 변경 없이 `compare-only`, `advisory-only` layer만 정의한다.

## 2. summary object 이름
공통 이름:
- `positive_evidence_expansion`

## 3. 출력 상태 집합
허용 상태는 아래 셋으로 고정한다.

1. `expandable`
- mature positive evidence와 healthy execution이 같이 있어 controlled expansion 검토가 가능한 family

2. `hold`
- positive evidence는 일부 있지만 아직 expansion-ready로 보기엔 guardrail이나 maturity가 남은 family

3. `not_ready`
- thin sample, negative/mixed outcome, execution drag, 또는 research-only posture 때문에 positive expansion language를 쓸 수 없는 family

주의:
- 이번 라운드에서는 `aggressive_expand`, `auto_expand`, `override_expand` 같은 상태를 두지 않는다.

## 4. recommendation 값
`expansion_bias`는 아래 셋만 허용한다.

1. `consider_expand`
2. `hold`
3. `do_not_expand`

주의:
- 이 값은 operator hint일 뿐 approval, sizing, rollout DB row를 직접 바꾸지 않는다.

## 5. 입력 소스
positive expansion은 아래 입력만 사용한다.

1. `rollout_recommendation`
- `family`
- `recommendation`
- `current_policy`
- `maturity`
- `confidence`

2. `strategy_lifecycle`
- `state`
- `transition_bias`
- `previous_state`

3. `score_to_outcome_funnel`
- family-level `closed`
- family-level `baseline_cost_profitable_rate_from_closed`

4. `family_execution_degradation_advisory`
- family-level execution health

5. `mode_advisory`
- family mode posture

6. `capital_allocator`
- family tilt summary는 support-only로 사용 가능

## 6. 출력 surface
이번 라운드에서 직접 반영하는 surface:

1. `validation_report`
- `positive_evidence_expansion_available`
- `positive_evidence_expansion_summary`

2. `operations/checklist`
- 새 `positive_evidence_expansion` item 또는 existing rollout/lifecycle item evidence 확장

3. `execution/operator-dashboard`
- `signal_funnel.positive_evidence_expansion`

4. `README`
- expansion layer 설명

비반영 surface:
- `ExecutionApproval`
- `approval_snapshot`
- `plan.validity`
- `/scanner/top`
- `/portfolio/budget` candidate rows
- rollout policy DB row

## 7. 공통 shape

```json
{
  "available": true,
  "advisory_only": true,
  "family": "sweep_reversal",
  "state": "expandable",
  "expansion_bias": "consider_expand",
  "confidence": "medium",
  "summary": "family has mature positive post-cost evidence and healthy execution; controlled expansion can be reviewed",
  "reason_codes": [
    "family_outcome:positive",
    "family_execution:healthy",
    "rollout_recommendation:expand",
    "lifecycle:production"
  ],
  "source_summary": {
    "family_closed": 9,
    "family_post_cost_rate": 0.66,
    "family_execution_status": "healthy",
    "family_mode_advisory_state": "keep_current_mode",
    "rollout_recommendation": "expand",
    "lifecycle_state": "production",
    "allocator_tier": "boost"
  }
}
```

## 8. 우선순위 규칙
positive expansion state 판단 우선순위는 아래로 고정한다.

1. `not_ready`
- thin sample / execution drag / research-only / negative outcome

2. `expandable`
- mature positive family + healthy execution + non-negative lifecycle posture

3. `hold`
- 위 둘 사이의 중간 구간

즉 expansion language는 `negative guardrail`을 먼저 본다.

## 9. hard guardrails
positive expansion은 아래를 직접 바꾸지 못한다.

1. approval state
2. `recommended_risk_r`
3. `allocated_risk_r`
4. rollout policy DB row
5. scanner ranking
6. portfolio ordering

즉 positive expansion은 공격적 control layer가 아니라 operator-facing confidence language다.

## 10. thin-sample 보호 규칙
thin sample이면 아래를 지킨다.

1. `expandable` 금지
2. `consider_expand` 금지
3. `hold` 또는 `not_ready`만 허용

## 11. wording 규칙
1. `expandable`
- “auto expansion”처럼 쓰지 않는다.
- 항상 `controlled`, `review`, `consider` 언어만 사용한다.

2. `hold`
- 긍정 evidence가 일부 있지만 아직 guardrail이 남아 있음을 명시한다.

3. `not_ready`
- failure 언어보다 guardrail / evidence 부족 언어를 우선한다.

## 12. 비목표
이번 계약에서 하지 않는 것:

1. approval auto boost
2. sizing auto boost
3. rollout DB 자동 승격
4. strategy family 생성/삭제
