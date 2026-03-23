# Persistent Promotion Lifecycle History Upgrade Derivation Rules

최종 갱신: 2026-03-23

## 1. 목적
- 같은 governance 입력이면 항상 같은 history event fingerprint와 aggregate history state가 나오도록 저장 규칙을 먼저 고정한다.
- 이번 규칙은 operator summary를 durable하게 만드는 규칙이지, approval / sizing / rollout authority를 재정의하는 규칙이 아니다.

## 2. event precedence
1. `lifecycle_transition`
2. `promotion_review_queued`
3. `remediation_started`
4. `clearance_progressed`
5. `promotion_reopen_ready`
6. `auto_execution_stage_recorded`

## 3. family 선택
1. `promotion_decision_brief.family`
2. 없으면 `promotion_reopen_queue.headline_family`
3. 없으면 `promotion_clearance_tracker.family`
4. 없으면 `promotion_governance.family`
5. 없으면 `strategy_lifecycle.family`

## 4. fingerprint rule
1. fingerprint는 `family + event_type + state_from + state_to + bias + latest_reason_codes + event_day_bucket` 조합으로 만든다.
2. 같은 fingerprint가 이미 있으면 duplicate append를 금지한다.
3. source summary detail이 달라도 fingerprint 핵심 상태가 같으면 동일 event로 본다.

## 5. event 파생 규칙
1. `strategy_lifecycle.previous_state != strategy_lifecycle.state`면 `lifecycle_transition`
2. `promotion_review_queue.top_review_action in {promote_review, defer_review}`면 `promotion_review_queued`
3. `promotion_remediation_queue.top_remediation_action in {execution_remediation, policy_remediation, condition_remediation}`면 `remediation_started`
4. `promotion_clearance_tracker.clearance_state in {blocked, partial_clear, clearance_ready}`면 `clearance_progressed`
5. `promotion_reopen_queue.top_reopen_action == reopen_review`면 `promotion_reopen_ready`
6. `auto_promotion_rollout_execution.execution_stage != advisory_only`면 `auto_execution_stage_recorded`

## 6. aggregate history state
1. history row가 없으면 `history_unavailable`
2. row는 있으나 latest event가 `remediation_started` 또는 blocked clearance면 `history_attention_required`
3. 최근 30일 row가 있고 latest event가 `promotion_reopen_ready` 또는 `auto_execution_stage_recorded`면 `history_stable`
4. 그 외에는 `history_accumulating`

## 7. summary window
1. first implementation은 최근 30일 기준 aggregate를 만든다.
2. `recent_transitions`는 최신 3개만 노출한다.
3. durable store full history는 surface에 전부 노출하지 않는다.

## 8. explicit limitation
1. first implementation은 immutable insert + aggregate read까지만 다룬다.
2. event backfill job은 다음 단계로 미룬다.
3. rollout DB row overwrite와 lifecycle snapshot overwrite는 이번 규칙 비범위다.
