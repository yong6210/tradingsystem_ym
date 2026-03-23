# Strategy Lifecycle Upgrade Contract

최종 갱신: 2026-03-23
상태: Item 1 baseline fixed

## 1. 목적
- family 단위 strategy lifecycle state를 공통 언어로 정규화한다.
- alpha research, rollout recommendation, execution degradation, post-cost outcome을 lifecycle state와 lifecycle recommendation으로 묶는다.
- 이번 계약은 DB policy를 자동 수정하지 않고, operator-facing summary layer만 정의한다.

## 2. lifecycle state 집합
허용 상태는 아래 다섯 개로 고정한다.

1. `research`
- 아직 live promotion 근거가 부족하거나 rollout이 research-only에 머물러야 하는 family

2. `probation`
- live expansion 전 단계
- usable evidence는 있으나 아직 production으로 보기엔 제한이 남는 family

3. `production`
- mature post-cost evidence와 healthy execution이 같이 있는 family

4. `degraded`
- 기존 production/probation family가 execution drag 또는 post-cost deterioration로 보수화된 상태

5. `retired`
- rollout 관점에서 사실상 live use를 중단하고 research backlog로만 유지해야 하는 family

## 3. 입력 소스
lifecycle은 아래 입력만 사용한다.

1. `alpha_research_pipeline`
- `promotion_watchlist`
- `recommended_action_summary`
- `research_focus_alignment`

2. `rollout_recommendation`
- `family`
- `recommendation`
- `current_policy`
- `suggested_policy_delta`
- `maturity`

3. `execution_degradation_advisory`
- global execution health context

4. `family_execution_degradation_advisory`
- family-level execution 상태

5. `score_to_outcome_funnel`
- family decomposition
- baseline-cost profitable conversion
- sample counts

6. `mode_advisory`
- family mode state

## 4. 출력 surface
이번 라운드에서 직접 반영하는 surface:

1. `validation_report`
- `strategy_lifecycle_available`
- `strategy_lifecycle_summary`

2. `operations/checklist`
- 새 `strategy_lifecycle` item 또는 existing rollout/research item evidence 확장

3. `execution/operator-dashboard`
- `signal_funnel.strategy_lifecycle`

4. `README`
- lifecycle layer 설명

비반영 surface:
- `ExecutionApproval`
- `approval_snapshot`
- `plan.validity`
- `/scanner/top`
- `rollout policy` DB row
- `/portfolio/budget` candidate rows

즉 lifecycle은 control authority가 아니라 governance / promotion language다.

## 5. 공통 object shape
공통 이름:
- `strategy_lifecycle`

summary shape:

```json
{
  "available": true,
  "advisory_only": true,
  "family": "sweep_reversal",
  "state": "probation",
  "previous_state": "research",
  "transition_bias": "promote|hold|degrade|retire|observe",
  "summary": "family has usable evidence and can be monitored in probation before broader promotion",
  "reason_codes": [
    "promotion_watchlist:eligible",
    "rollout_recommendation:hold",
    "sample:usable"
  ],
  "source_summary": {
    "family_closed": 8,
    "family_post_cost_rate": 0.5,
    "family_execution_status": "healthy",
    "family_mode_advisory_state": "keep_current_mode",
    "rollout_recommendation": "hold",
    "promotion_watchlist_ready": true
  }
}
```

## 6. 우선순위 규칙
lifecycle state 판단 우선순위는 아래로 고정한다.

1. hard-negative family condition
- retire / degrade 후보

2. production evidence
- mature positive family

3. probation evidence
- usable but 아직 promotion guardrail이 남은 family

4. research evidence
- thin sample or explicit research-only context

즉 `negative 먼저`, 그 다음 `production`, 그 다음 `probation`, 마지막 `research` 순서다.

## 7. thin-sample 보호 규칙
thin sample이면 아래를 지킨다.

1. `production` 금지
2. aggressive `promote` bias 금지
3. `research` 또는 제한적 `probation`만 허용

## 8. recommendation 의미 규칙
`transition_bias`는 아래 다섯 값만 허용한다.

1. `promote`
- research/probation에서 상향 검토 가능

2. `hold`
- 현재 state 유지

3. `degrade`
- production/probation에서 보수화 필요

4. `retire`
- live use 중단, research backlog only

5. `observe`
- evidence 부족, 당장 state 변경보다 관찰 우선

## 9. 하드 가드레일
lifecycle은 아래를 직접 바꾸지 못한다.

1. approval state
2. sizing
3. portfolio allocation
4. rollout policy DB row
5. scanner ranking

즉 lifecycle은 governance language이지 execution authority가 아니다.

## 10. reason code 규칙
허용 prefix:
- `promotion_watchlist:`
- `rollout_recommendation:`
- `family_execution:`
- `family_outcome:`
- `family_mode:`
- `sample:`
- `lifecycle:`

예시:
- `promotion_watchlist:eligible`
- `rollout_recommendation:research_only`
- `family_execution:manual_review`
- `family_outcome:positive`

## 11. 비목표
이번 계약에서 하지 않는 것:

1. rollout policy DB 자동 승격/하향
2. approval hard block 변경
3. strategy family 자동 생성/삭제
4. candidate row lifecycle 부착
