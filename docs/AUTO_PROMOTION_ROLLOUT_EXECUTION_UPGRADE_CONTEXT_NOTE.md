# Auto Promotion Rollout Execution Upgrade Context Note

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 왜 이 작업을 하는가
- 현재 엔진은 추천과 queue는 잘 만들지만, 실제 정책 반영은 대부분 사람 손을 탄다.
- 이 상태는 안전하지만 느리다.
- 이번 라운드 목적은 `advisory-only -> semi-auto -> auto` 전환 조건을 명확히 만드는 것이다.

## 2. 절대 규칙
1. 첫 단계는 dry-run / audit-first다.
2. operator kill-switch와 manual override가 항상 우선이다.
3. approval / sizing hard authority는 유지한다.
4. audit trail 없는 auto-write는 금지한다.

## 3A. Item 1 계약 결론
1. `auto_promotion_rollout_execution`은 새 live authority가 아니라 execution candidate contract다.
2. 허용 stage는 `advisory_only / dry_run_execution / semi_auto_candidate / auto_execution_blocked`까지만 둔다.
3. 첫 구현은 `dry_run_execution`과 `semi_auto_candidate` proposal wording까지만 허용하고, live DB auto-write는 금지한다.
4. 직접 반영 surface는 validation / checklist / dashboard / README / audit artifact contract로 제한한다.
5. thin sample, family execution degradation, mode restriction, outcome approval penalty는 auto path를 즉시 막는 hard guardrail로 본다.

## 3B. Item 2 derivation 결론
1. `promotion_decision_brief -> promotion_reopen_queue -> promotion_clearance_tracker`를 readiness precedence로 두고, reopen/clearance가 먼저 열리지 않으면 auto path는 막는다.
2. `family_execution_degradation_advisory`, `mode_advisory`, `outcome_control_trace`는 hard block source로 사용한다.
3. `positive_evidence_expansion`은 block 해제 신호가 아니라 `semi_auto_candidate` 승격을 위한 support-only positive modifier로만 사용한다.
4. `dry_run_execution`은 audit artifact만 생성하고, `semi_auto_candidate`도 operator-confirmable proposal execution까지만 허용한다.
5. DB write scope는 이번 단계에서 `none / proposal_only`까지만 허용한다.

## 3C. Item 3 patch 결론
1. validation에는 `auto_promotion_rollout_execution_available`, `auto_promotion_rollout_execution_summary`, `## Auto Promotion Rollout Execution`을 추가한다.
2. checklist는 blocking이 아닌 informational item `auto_promotion_rollout_execution`으로만 연결한다.
3. dashboard는 `signal_funnel.auto_promotion_rollout_execution` aggregate summary만 허용하고, recent intents / approval snapshot / candidate row로는 퍼뜨리지 않는다.
4. README는 `Promotion Decision Brief` 뒤에 compare-only execution candidate contract 설명을 추가한다.
5. audit artifact와 DB mutation은 이번 패치 비범위로 유지한다.

## 3D. Item 4 구현 결론
1. 새 helper `auto_promotion_rollout_execution`을 추가하고 promotion stack + rollout + outcome control trace를 execution candidate contract language로 연결했다.
2. `execution_stage`, `execution_bias`, `action_domain`, `write_scope`, `dry_run_only`를 validation / checklist / dashboard 공통 summary로 배선했다.
3. first implementation은 `proposal_only`와 `none` write scope까지만 허용했고, direct DB mutation path는 추가하지 않았다.

## 3E. Item 5 테스트 및 문서 동기화 결론
1. helper unit test와 validation/checklist/dashboard/API smoke를 통해 새 summary key와 stage semantics를 고정했다.
2. README에 `Auto Promotion Rollout Execution` 섹션과 operator surface 설명을 추가했다.
3. 이 계층이 compare-only execution candidate contract라는 점을 테스트와 문서 양쪽에서 같이 못 박았다.

## 3F. Item 6 self-check 결론
1. 이번 구현은 validation / checklist / dashboard / README에만 머물고 approval / sizing / rollout DB authority로는 번지지 않았다.
2. `write_scope=none|proposal_only` 경계와 `auto_execution_blocked` hard guardrail이 유지돼서, 성급한 auto-write 회귀는 현재 보이지 않는다.
3. 따라서 이번 라운드는 여기서 닫아도 된다.
