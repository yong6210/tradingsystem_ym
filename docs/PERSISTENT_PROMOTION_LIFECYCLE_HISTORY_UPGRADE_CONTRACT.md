# Persistent Promotion Lifecycle History Upgrade Contract

최종 갱신: 2026-03-23

## 1. 목적
- `strategy_lifecycle`, `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`, `promotion_clearance_tracker`, `promotion_reopen_queue`, `promotion_decision_brief`, `auto_promotion_rollout_execution`를 snapshot-only가 아니라 durable history language로 연결한다.
- 이번 라운드의 목적은 current posture를 바꾸는 것이 아니라, `어떻게 여기까지 왔는가`를 immutable event로 남기는 것이다.

## 2. 허용 history event
1. `lifecycle_transition`
2. `promotion_review_queued`
3. `remediation_started`
4. `clearance_progressed`
5. `promotion_reopen_ready`
6. `auto_execution_stage_recorded`

## 3. 허용 aggregate state
1. `history_unavailable`
2. `history_accumulating`
3. `history_stable`
4. `history_attention_required`

## 4. 직접 입력 source
1. `strategy_lifecycle`
2. `promotion_governance`
3. `promotion_review_queue`
4. `promotion_remediation_queue`
5. `promotion_clearance_tracker`
6. `promotion_reopen_queue`
7. `promotion_decision_brief`
8. `auto_promotion_rollout_execution`
9. `rollout_recommendation`

## 5. 직접 반영 surface
1. persistent store
2. validation
3. checklist
4. dashboard
5. README

## 6. 비범위 surface
1. `ExecutionApproval`
2. `approval_snapshot`
3. `recommended_risk_r`
4. `/scanner/top`
5. `/portfolio/budget` candidate row authority
6. rollout DB row direct overwrite

## 7. 1차 durable row shape

```json
{
  "id": "uuid",
  "family": "trend_continuation",
  "event_type": "clearance_progressed",
  "event_ts": "2026-03-23T00:00:00Z",
  "state_from": "blocked",
  "state_to": "clearance_ready",
  "bias": "consider_reopen_review",
  "source_key": "promotion_clearance_tracker",
  "source_summary": {
    "remaining_guardrail_domains": ["policy"],
    "cleared_guardrail_domains": ["execution", "condition"]
  },
  "reason_codes": [
    "promotion_clearance:clearance_ready",
    "promotion_reopen_queue:reopen_review"
  ],
  "snapshot_hash": "sha256"
}
```

## 8. aggregate summary shape

```json
{
  "available": true,
  "advisory_only": true,
  "family": "trend_continuation",
  "history_state": "history_stable",
  "latest_event_type": "promotion_reopen_ready",
  "latest_event_ts": "2026-03-23T00:00:00Z",
  "event_count_30d": 6,
  "recent_transitions": [
    "degraded -> blocked",
    "blocked -> clearance_ready",
    "clearance_ready -> reopen_review"
  ],
  "summary": "family=trend_continuation now has durable promotion history showing a recent clearance-to-reopen transition.",
  "reason_codes": [
    "history:stable",
    "latest_event:promotion_reopen_ready"
  ]
}
```

## 9. guardrail
1. history row는 append-only다.
2. 기존 snapshot summary semantics를 깨지 않는다.
3. rerun 중복 방지를 위해 event fingerprint가 필요하다.
4. thin sample은 history row 기록을 막지 않지만, positive interpretation을 자동으로 만들지 않는다.
5. persistence failure가 runtime approval authority를 바꾸면 안 된다.

## 10. 역할 분리
1. 기존 summary stack은 current posture를 설명한다.
2. `persistent_promotion_lifecycle_history`는 current posture를 바꾸지 않고 lineage를 남긴다.
3. validation / checklist / dashboard는 same aggregate history summary만 읽는다.
