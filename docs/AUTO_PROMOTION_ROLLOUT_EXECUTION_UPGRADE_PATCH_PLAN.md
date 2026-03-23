# Auto Promotion Rollout Execution Upgrade Patch Plan

최종 갱신: 2026-03-23

## 1. 목적
- `auto_promotion_rollout_execution`을 validation / checklist / dashboard / README에 어떤 wording과 shape로 넣을지 먼저 고정한다.
- audit-first dry-run contract와 runtime explanation surface를 분리한다.

## 2. validation 반영
추가 필드:
1. `auto_promotion_rollout_execution_available`
2. `auto_promotion_rollout_execution_summary`

추가 섹션:
1. `## Auto Promotion Rollout Execution`

최소 표기 필드:
1. `execution_stage`
2. `execution_bias`
3. `action_domain`
4. `target_family`
5. `target_posture`
6. `write_scope`
7. `dry_run_only`
8. `summary`
9. `reason_codes`

## 3. checklist 반영
새 item:
1. `auto_promotion_rollout_execution`

규칙:
1. blocking item이 아니라 informational item으로 유지한다.
2. `execution_stage in {dry_run_execution, semi_auto_candidate}`여도 status는 `PASS` 또는 `WARN`까지만 허용한다.
3. `auto_execution_blocked`는 operator에게 block reason을 설명하지만, approval authority를 대체하지 않는다.

## 4. dashboard 반영
허용 위치:
1. `signal_funnel.auto_promotion_rollout_execution`

비허용 위치:
1. recent intents
2. approval snapshot
3. open orders / positions
4. `/portfolio/budget` candidate row
5. scanner row

## 5. audit artifact 반영
허용 위치:
1. validation report markdown
2. 별도 summary object 안의 `write_scope`, `dry_run_only`

이번 단계 비범위:
1. 실제 artifact writer 구현
2. 실제 DB mutation job

## 6. README 반영
위치:
1. `Promotion Decision Brief` 뒤
2. `Positive Evidence Expansion` 앞

핵심 문구:
1. `auto_promotion_rollout_execution`은 compare-only execution candidate contract다.
2. first implementation은 audit-only dry-run / operator-confirmable proposal execution까지만 허용한다.
3. approval / sizing / rollout DB auto-write는 여전히 비범위다.

## 7. patch 방향
1. 새 top-level object를 만들되 authority object와 merge하지 않는다.
2. strategy engine은 governance stack을 읽어 summary object를 한 번만 계산하고 validation / dashboard에 공통 배선한다.
3. checklist는 validation summary만 읽어 wording drift를 막는다.
4. dashboard는 aggregate summary만 노출하고 row-level execution authority처럼 퍼뜨리지 않는다.

## 8. explicit boundary
1. `ExecutionApproval`
2. `approval_snapshot`
3. `recommended_risk_r`
4. rollout DB row
5. lifecycle/history persistence

위 5개는 이번 패치에서 건드리지 않는다.
