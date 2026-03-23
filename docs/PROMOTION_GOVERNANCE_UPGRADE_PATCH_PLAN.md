# Promotion Governance Upgrade Patch Plan

최종 갱신: 2026-03-23
상태: Item 3 baseline fixed

## 1. 목적
- `promotion governance`를 어떤 surface에 어떤 wording으로 보여줄지 먼저 고정한다.
- rollout recommendation, strategy lifecycle, positive evidence expansion과 역할이 섞이지 않도록 반영 위치와 문구를 제한한다.

## 2. Validation Report 반영안
추가:
1. top-level `promotion_governance_available`
2. top-level `promotion_governance_summary`
3. markdown section `## Promotion Governance`

`promotion_governance_summary` 최소 필드:
1. `family`
2. `state`
3. `promotion_bias`
4. `target_posture`
5. `confidence`
6. `summary`
7. `reason_codes`
8. `source_summary`

표현 원칙:
1. `controlled promotion review candidate`
2. `keep current posture and continue evidence accumulation`
3. `promotion review should be deferred while guardrails remain active`
4. policy auto-change language는 금지한다.

## 3. Operations Checklist 반영안
추가:
1. informational item `Promotion Governance`

동작:
1. blocking item이 아니다.
2. `state=defer`는 `WARN` informational 허용
3. `state=promotable`도 `PASS` informational로만 유지
4. checklist wording은 `review promotion candidate`, `defer promotion review`, `keep current posture` 정도로 제한한다.

## 4. Operator Dashboard 반영안
추가:
1. `signal_funnel.promotion_governance`

제한:
1. aggregate summary만 노출한다.
2. candidate row, recent intent row, approval snapshot에는 퍼뜨리지 않는다.
3. `strategy_lifecycle`, `positive_evidence_expansion`, `outcome_bucket_granularity`와 merge하지 않는다.

## 5. README 반영안
추가 위치:
1. `Strategy Lifecycle` 뒤
2. `Positive Evidence Expansion` 앞

핵심 설명:
1. lifecycle은 posture, promotion governance는 승격 review decision language라는 점
2. `promotable / hold / defer`가 compare-only review state라는 점
3. approval, sizing, rollout DB를 직접 바꾸지 않는다는 점

## 6. 비반영 Surface
추가 금지:
1. `ExecutionApproval`
2. `approval_snapshot`
3. `plan.validity`
4. `/scanner/top`
5. `/portfolio/budget` candidate row
6. rollout policy DB row
7. operator action priority hard ordering

## 7. 구현 단계 가이드
1. summary helper는 rollout / lifecycle / positive expansion / condition split을 읽는 compare-only layer로 둔다.
2. `outcome_bucket_granularity`와 `capital_allocator`는 support-only modifier로만 사용한다.
3. thin sample과 execution drag가 있으면 `promotable` language를 만들지 않는다.
