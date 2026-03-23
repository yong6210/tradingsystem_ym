# Auto Promotion Rollout Execution Upgrade Derivation Rules

최종 갱신: 2026-03-23

## 1. 목적
- 같은 governance 입력이면 항상 같은 `auto_promotion_rollout_execution` stage가 나오도록 precedence와 safety rule을 먼저 고정한다.
- 이번 규칙은 auto-write를 여는 규칙이 아니라, `dry-run proposal`과 `semi-auto candidate`를 언제 허용할 수 있는지 정하는 규칙이다.

## 2. 입력 precedence
1. `promotion_decision_brief`
2. `promotion_reopen_queue`
3. `promotion_clearance_tracker`
4. `promotion_remediation_queue`
5. `promotion_governance`
6. `rollout_recommendation`
7. `strategy_lifecycle`
8. `family_execution_degradation_advisory`
9. `mode_advisory`
10. `outcome_control_trace`
11. `positive_evidence_expansion`

## 3. target family 선택
1. `promotion_decision_brief.family`
2. 없으면 `promotion_reopen_queue.headline_family`
3. 없으면 `promotion_clearance_tracker.family`
4. 없으면 `promotion_remediation_queue.headline_family`
5. 없으면 `promotion_governance.family`
6. 없으면 `rollout_recommendation.family`

## 4. hard block rule
아래 중 하나라도 참이면 `execution_stage=auto_execution_blocked`, `execution_bias=block_auto_execution`, `write_scope=none`:

1. `promotion_decision_brief.brief_state == observe_case`
2. `promotion_reopen_queue.top_reopen_action != reopen_review`
3. `promotion_clearance_tracker.clearance_state in {blocked, observe_only}`
4. `promotion_remediation_queue.top_remediation_action in {execution_remediation, policy_remediation, condition_remediation}`
5. `family_execution_degradation_advisory.top_family.status in {watch, manual_review}`
6. `mode_advisory.family_top.advisory_state in {research_only, restrict, stop}`
7. `outcome_control_trace.approval_penalty_status in {manual_review, blocked}`
8. any reason code contains `sample:thin_sample`

## 5. dry-run execution 허용 규칙
다음을 모두 만족하면 `execution_stage=dry_run_execution`, `execution_bias=prepare_dry_run`, `dry_run_only=true`:

1. `promotion_decision_brief.brief_state == reopen_candidate`
2. `promotion_reopen_queue.top_reopen_action == reopen_review`
3. `promotion_clearance_tracker.clearance_state == clearance_ready`
4. `promotion_governance.state == promotable`
5. `rollout_recommendation.recommendation in {expand, hold}`
6. `strategy_lifecycle.state in {probation, production}`
7. `family_execution_degradation_advisory`가 target family 기준 `healthy` 또는 `unavailable`
8. `outcome_control_trace.approval_penalty_status not in {manual_review, blocked}`

## 6. semi-auto candidate 허용 규칙
`dry_run_execution` 조건을 만족하고, 아래 support-only positive modifier가 충분할 때만 `execution_stage=semi_auto_candidate`, `execution_bias=consider_semi_auto`:

1. `positive_evidence_expansion.state == expandable`
2. `positive_evidence_expansion.expansion_bias == consider_expand`
3. `rollout_recommendation.recommendation == expand`
4. `promotion_governance.target_posture in {probation, production}`
5. `promotion_decision_brief.target_posture in {probation, production}`

주의:
1. `semi_auto_candidate`도 direct write는 하지 않는다.
2. operator confirmable proposal execution만 허용한다.

## 7. action domain 파생
1. `rollout_recommendation.recommendation == expand`면 `action_domain=rollout_policy_delta`
2. `promotion_governance.target_posture in {probation, production}`면 `action_domain=promotion_posture_update`
3. 둘 다 약하거나 불명확하면 `action_domain=no_write_observe`
4. `action_domain`은 1개만 허용한다.

## 8. write scope
1. `advisory_only` -> `none`
2. `dry_run_execution` -> `none`
3. `semi_auto_candidate` -> `proposal_only`
4. `auto_execution_blocked` -> `none`

## 9. confidence rule
1. `high`
   - `promotion_clearance_tracker.clearance_state == clearance_ready`
   - `promotion_governance.state == promotable`
   - `rollout_recommendation.recommendation == expand`
   - execution drag 없음
2. `medium`
   - dry-run 조건은 만족하지만 positive support가 일부만 있음
3. `low`
   - blocked 또는 observe 계열

## 10. reason code 구성
우선순위:
1. `auto_execution:*`
2. `promotion_decision_brief:*`
3. `promotion_reopen_queue:*`
4. `promotion_clearance:*`
5. `promotion_governance:*`
6. `rollout_recommendation:*`
7. `lifecycle:*`
8. `execution_guardrail:*`
9. `mode_guardrail:*`
10. `sample:*`

## 11. wording rule
1. `auto_execution_blocked`
   - `auto execution remains blocked; keep governance changes advisory-only until guardrails clear`
2. `dry_run_execution`
   - `family=<family> is eligible for audit-only dry-run execution review; generate proposal artifacts but do not write policy rows`
3. `semi_auto_candidate`
   - `family=<family> is eligible for operator-confirmable semi-auto proposal execution; keep write scope proposal-only`
4. `advisory_only`
   - `family=<family> remains manual-only; keep promotion and rollout review compare-only`

## 12. explicit limitation
1. DB write function 호출은 이번 규칙에 포함하지 않는다.
2. audit artifact schema와 execution summary object만 먼저 고정한다.
3. persistent lifecycle/history update는 다음 라운드에서 다룬다.
