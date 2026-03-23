# Auto Promotion Rollout Execution Upgrade Contract

최종 갱신: 2026-03-23

## 1. 목적
- `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`, `promotion_clearance_tracker`, `promotion_reopen_queue`, `promotion_decision_brief`, `rollout_recommendation`을 실제 execution candidate language로 연결한다.
- 이번 라운드의 목적은 곧바로 live DB auto-write를 여는 것이 아니라, `advisory-only -> dry-run execution proposal -> semi-auto candidate` 경계를 명확히 고정하는 것이다.

## 2. 허용 단계
1. `advisory_only`
2. `dry_run_execution`
3. `semi_auto_candidate`
4. `auto_execution_blocked`

## 3. 허용 bias
1. `keep_manual`
2. `prepare_dry_run`
3. `consider_semi_auto`
4. `block_auto_execution`

## 4. 허용 action domain
1. `promotion_posture_update`
2. `rollout_policy_delta`
3. `no_write_observe`

## 5. 직접 입력 source
1. `promotion_governance`
2. `promotion_review_queue`
3. `promotion_remediation_queue`
4. `promotion_clearance_tracker`
5. `promotion_reopen_queue`
6. `promotion_decision_brief`
7. `rollout_recommendation`
8. `strategy_lifecycle`
9. `family_execution_degradation_advisory`
10. `mode_advisory`
11. `outcome_control_trace`
12. `positive_evidence_expansion`

## 6. 직접 반영 surface
1. validation
2. checklist
3. dashboard
4. README
5. audit artifact contract

## 7. 비범위 surface
1. `ExecutionApproval`
2. `approval_snapshot`
3. `recommended_risk_r`
4. `/scanner/top`
5. `/portfolio/budget` candidate row authority 변경
6. rollout DB row 즉시 auto-write
7. promotion/lifecycle persistence 즉시 auto-write

## 8. 1차 object shape

```json
{
  "available": true,
  "advisory_only": true,
  "execution_stage": "dry_run_execution",
  "execution_bias": "prepare_dry_run",
  "action_domain": "rollout_policy_delta",
  "target_family": "trend_continuation",
  "target_posture": "probation",
  "write_scope": "none",
  "dry_run_only": true,
  "summary": "family=trend_continuation is eligible for audit-only dry-run execution review, but not for direct auto-write.",
  "reason_codes": [
    "promotion_reopen_queue:reopen_review",
    "promotion_clearance:clearance_ready",
    "guardrail:audit_first"
  ],
  "source_summary": {
    "promotion_state": "promotable",
    "reopen_action": "reopen_review",
    "clearance_state": "clearance_ready",
    "rollout_recommendation": "expand",
    "lifecycle_state": "probation"
  }
}
```

## 9. stage 의미
- `advisory_only`
  - 기존 compare-only 상태 유지
- `dry_run_execution`
  - audit artifact만 생성
  - 실제 DB write 없음
- `semi_auto_candidate`
  - operator-confirmable proposal execution까지만 허용
  - direct write는 여전히 금지
- `auto_execution_blocked`
  - 현재 evidence로는 자동 execution 논의 자체를 막음

## 10. guardrail
1. `thin_sample`이면 `semi_auto_candidate`와 공격적 rollout delta를 금지한다.
2. `family_execution_degradation_advisory.status in {watch, manual_review}`면 `action_domain=promotion_posture_update` 또는 `rollout_policy_delta` auto path를 금지한다.
3. `mode_advisory`가 `research_only` 또는 `restrict` 계열이면 `execution_stage`는 `advisory_only` 또는 `auto_execution_blocked`만 허용한다.
4. `outcome_control_trace.approval_penalty_status in {manual_review, blocked}`면 자동 execution 논의를 금지한다.
5. operator kill-switch, close-only, manual override가 항상 최우선이다.
6. audit trail 없는 write path는 금지한다.

## 11. 역할 분리
1. `promotion_governance`는 family review decision language다.
2. `promotion_review_queue`는 cross-family review ordering language다.
3. `promotion_remediation_queue`는 guardrail clearing ordering language다.
4. `promotion_clearance_tracker`는 family progress tracking language다.
5. `promotion_reopen_queue`는 cross-family reopen ordering language다.
6. `promotion_decision_brief`는 single-family case compression language다.
7. `auto_promotion_rollout_execution`은 execution candidate contract language다.

## 12. 이번 라운드의 명시적 제한
1. live rollout DB row auto-write는 금지한다.
2. lifecycle persistent store auto-write는 금지한다.
3. first implementation은 `dry_run_execution`과 `semi_auto_candidate` proposal wording까지만 허용한다.
4. validation/checklist/dashboard에서만 same summary object를 읽는다.
