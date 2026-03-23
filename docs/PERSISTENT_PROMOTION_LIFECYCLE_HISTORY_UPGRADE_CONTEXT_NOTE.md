# Persistent Promotion Lifecycle History Upgrade Context Note

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 왜 이 작업을 하는가
- 현재 summary는 잘 나오지만, 그 summary가 일회성 snapshot처럼 읽히는 한계가 있다.
- 실제 운영에서는 `언제 degraded 되었고`, `언제 clearance_ready였고`, `얼마나 자주 reopen 후보가 됐는지`가 중요하다.
- 이번 라운드 목적은 governance layer를 history-aware로 올리는 것이다.

## 2. 절대 규칙
1. history는 audit-friendly여야 한다.
2. current snapshot semantics를 깨지 않는다.
3. immutable event 중심으로 설계한다.
4. migration은 점진적으로 간다.

## 3A. Item 1 계약 결론
1. persistent history는 새 authority가 아니라 immutable lineage layer다.
2. 허용 event는 lifecycle transition, review queue, remediation, clearance, reopen, auto-execution stage 기록까지만 둔다.
3. validation / checklist / dashboard는 aggregate summary만 읽고 full history row를 그대로 퍼뜨리지 않는다.

## 3B. Item 2 derivation 결론
1. append-only event fingerprint와 duplicate suppression 규칙을 먼저 고정했다.
2. `promotion_decision_brief -> promotion_reopen_queue -> promotion_clearance_tracker`를 family 선택 precedence로 둔다.
3. latest event와 recent 30일 row count로 `history_unavailable / history_accumulating / history_stable / history_attention_required`를 정한다.

## 3C. Item 3 patch 결론
1. validation에는 `promotion_lifecycle_history_available`, `promotion_lifecycle_history_summary`, `## Promotion Lifecycle History`를 추가하는 방향으로 고정했다.
2. checklist는 non-blocking informational item으로, dashboard는 `signal_funnel.promotion_lifecycle_history` aggregate summary만 허용한다.
3. persistence failure는 runtime approval authority를 바꾸지 않는 soft-fail로 제한한다.

## 3D. Item 4 구현 결론
1. `PromotionLifecycleHistory` append-only model, repository, service를 실제 runtime에 연결했다.
2. validation 경로는 persist 시도 후 recent aggregate summary를 읽고, dashboard 경로는 persist 없이 same summary shape만 읽는다.
3. persistence failure는 rollback 후 compare-only fallback summary로 내려가도록 soft-fail 처리했다.

## 3E. Item 5 테스트 및 문서 동기화 결론
1. append-only insert와 snapshot-hash duplicate suppression을 DB 테스트로 고정했다.
2. validation, checklist, dashboard, API smoke에 `promotion_lifecycle_history` key와 핵심 semantics를 추가했다.
3. README에도 lineage layer 설명과 operator surface 노출 위치를 반영했다.

## 3F. Item 6 self-check 결론
1. `promotion_lifecycle_history`는 validation / checklist / dashboard / durable store에만 있고 approval / sizing / scanner / candidate row / rollout DB authority는 건드리지 않는다.
2. `promotion_review_queue`, `promotion_remediation_queue`, `promotion_clearance_tracker`, `promotion_reopen_queue`와 역할 분리도 유지된다.
3. 누락, authority 경계 훼손, 과도한 영향 범위, 맥락 노트 위반은 현재 보이지 않는다.
