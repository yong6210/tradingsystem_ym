# Promotion Decision Brief Upgrade Derivation Rules

최종 갱신: 2026-03-23
상태: Item 2 baseline fixed

## 1. 목적
- `promotion_decision_brief`는 top family 하나를 기준으로 promotion case를 압축하는 single-family summary다.
- 이 계층은 `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`, `promotion_clearance_tracker`, `promotion_reopen_queue`를 다시 늘어놓지 않고, operator가 지금 읽어야 할 핵심 posture만 한 번에 보여준다.

## 2. family selection precedence
headline family는 아래 우선순위로 하나만 고른다.
1. `promotion_reopen_queue.headline_family`
2. `promotion_clearance_tracker.family`
3. `promotion_remediation_queue.headline_family`
4. `promotion_review_queue.headline_family`
5. `promotion_governance.family`
6. `strategy_lifecycle.family`
7. `positive_evidence_expansion.family`
8. `capital_allocator.family_focus`

비어 있거나 `unknown`이면 다음 source로 넘어간다.

## 3. source normalization
headline family가 정해지면 아래 값을 정규화한다.
1. governance posture
- `promotion_governance.state`
- `promotion_governance.target_posture`
- `promotion_governance.confidence`

2. review context
- `promotion_review_queue.top_review_action`
- matching family row의 `review_action / promotion_state / confidence`

3. remediation context
- matching family row의 `remediation_action / remediation_domain / confidence`

4. clearance context
- `promotion_clearance_tracker.clearance_state`
- `promotion_clearance_tracker.clearance_bias`
- `remaining_guardrail_domains`
- `cleared_guardrail_domains`

5. reopen context
- `promotion_reopen_queue.top_reopen_action`
- matching family row의 `reopen_action / clearance_state / confidence`

6. support context
- `strategy_lifecycle.state`
- `positive_evidence_expansion.state`
- `capital_allocator.family_weights[*].tier`
- `family_execution_degradation_advisory.status`

## 4. guardrail normalization
아래 조건은 positive wording보다 먼저 평가한다.
1. thin sample
- `sample:thin_sample`가 governance / review / remediation / clearance / reopen row reason codes 어디에든 있으면 thin sample로 본다.

2. execution hard guardrail
- family execution status가 `manual_review`면 hard guardrail로 본다.

3. blocked clearance
- `promotion_clearance_tracker.clearance_state == blocked`

4. active remediation
- `remediation_action in {execution_remediation, policy_remediation, condition_remediation}`

## 5. brief_state precedence
허용 state는 `reopen_candidate / clearance_required / observe_case` 셋만 쓴다.

우선순위는 아래처럼 고정한다.
1. `observe_case`
- thin sample
- `clearance_state == observe_only`
- lifecycle이 `research`이고 reopen / remediation 근거가 약함

2. `reopen_candidate`
- `promotion_reopen_queue.top_reopen_action == reopen_review` 또는 family row `reopen_action == reopen_review`
- `clearance_state == clearance_ready`
- family execution status가 `manual_review`가 아님
- active remediation이 없음
- governance state가 `hold` 또는 `promotable`

3. `clearance_required`
- 위 두 조건이 아니면 기본값

## 6. decision_bias mapping
1. `reopen_candidate` -> `consider_reopen_review`
2. `clearance_required` -> `continue_clearance`
3. `observe_case` -> `observe_only`

## 7. target_posture mapping
1. `promotion_governance.target_posture`가 `probation / production / keep_current` 중 하나면 그대로 사용한다.
2. governance target이 없고 `brief_state == reopen_candidate`이며 lifecycle이 `probation`이면 `production`
3. governance target이 없고 `brief_state == reopen_candidate`이며 lifecycle이 `research`면 `probation`
4. 그 외는 `keep_current`

## 8. confidence precedence
1. `observe_case`는 항상 `low`
2. `reopen_candidate`는 reopen row confidence를 우선, 없으면 clearance confidence, 그 다음 governance confidence
3. `clearance_required`는 clearance confidence를 우선, 없으면 remediation confidence, 그 다음 governance confidence
4. `positive_evidence_expansion.state == expandable`와 allocator `boost`는 `reopen_candidate` confidence를 한 단계까지만 보조할 수 있다.

## 9. reason_codes
reason code prefix는 아래만 허용한다.
1. `promotion_decision_brief:*`
2. `promotion_governance:*`
3. `review_queue:*`
4. `remediation_queue:*`
5. `promotion_clearance:*`
6. `promotion_reopen_queue:*`
7. `family_execution:*`
8. `lifecycle:*`
9. `positive_expansion:*`
10. `allocator:*`
11. `sample:*`

## 10. wording
1. `reopen_candidate`
- “family=X can be reviewed as a controlled promotion re-open candidate”

2. `clearance_required`
- “family=X still needs guardrail clearing before promotion review should be reopened”

3. `observe_case`
- “family=X remains in observe posture while promotion evidence is still incomplete”

금지:
1. auto-promote wording
2. rollout DB mutation wording
3. approval/sizing authority wording
