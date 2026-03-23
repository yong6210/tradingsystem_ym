# Multi Strategy AB Expansion Upgrade Patch Plan

최종 갱신: 2026-03-23
상태: Item 3 baseline fixed

## 1. 목적
- `A_ONLY -> A_PLUS_B` 확장을 어떤 surface에 어떤 wording으로 붙일지 먼저 고정한다.
- raw `strategy_family` authority를 유지한 채, A/B overlay를 scanner / portfolio / validation / checklist / dashboard / README에 additive로만 반영한다.

## 2. 공통 문구 원칙
1. raw `strategy_family`는 source-of-truth로 유지한다.
2. `a_reversal / b_continuation / research_only_sidecar`는 overlay interpretation layer로만 쓴다.
3. `b_continuation`은 first-wave에서 항상 `available but guarded`, `shadow/probation first` 문구를 유지한다.
4. `A replaces B`, `B auto-live`, `raw family rewritten` 같은 문구는 금지한다.

## 3. Scanner 반영안
### 3.1 additive fields
`/scanner/top` row에는 아래 additive field까지만 허용한다.
1. `strategy_cluster`
2. `strategy_cluster_status`
3. `multi_strategy_overlay`

### 3.2 `multi_strategy_overlay` 최소 필드
1. `cluster`
2. `raw_family`
3. `mode`
4. `live_eligible`
5. `guarded`
6. `guardrail_reasons`
7. `summary`

### 3.3 scanner 경계
1. 기존 `strategy_family`, `strategy_grade`, `strategy_family_reason`는 그대로 유지한다.
2. scanner ranking은 raw family / mode / rollout / execution guardrail을 먼저 적용하고 overlay는 설명층으로만 붙인다.
3. `range_rotation`은 first-wave에서 `research_only_sidecar` 또는 overlay 미적용으로만 읽고 live candidate language는 금지한다.

## 4. Portfolio 반영안
### 4.1 candidate row additive fields
`/portfolio/budget` candidate row에는 아래 additive field까지만 허용한다.
1. `strategy_family`
2. `strategy_cluster`
3. `strategy_cluster_status`
4. `multi_strategy_overlay`

### 4.2 portfolio 역할
1. accepted / blocked ordering은 raw family, rollout authority, mode cap, portfolio cap을 우선한다.
2. A/B overlay는 family mix와 explanation layer를 읽게 하는 보조 정보로만 붙인다.
3. `allocated_risk_r`, `recommended_risk_r`, approval state는 overlay가 직접 바꾸지 않는다.

### 4.3 budget aggregate
추가:
1. top-level `multi_strategy_ab_summary`

최소 필드:
1. `available`
2. `mode`
3. `family_mix`
4. `a_cluster`
5. `b_cluster`
6. `research_sidecar_count`
7. `summary`

## 5. Validation Report 반영안
추가:
1. top-level `multi_strategy_ab_available`
2. top-level `multi_strategy_ab_summary`
3. markdown section `## Multi Strategy AB Expansion`

`multi_strategy_ab_summary` 최소 필드:
1. `mode`
2. `available`
3. `raw_family_anchor`
4. `a_cluster`
5. `b_cluster`
6. `research_sidecar`
7. `family_mix`
8. `summary`
9. `reason_codes`

표현 원칙:
1. `A remains current production anchor`
2. `B is available under guarded first-wave activation`
3. `range rotation remains research-only sidecar`
4. approval auto-change / rollout auto-change language는 금지한다.

## 6. Operations Checklist 반영안
추가:
1. informational item `Multi Strategy AB Expansion`

동작:
1. blocking item이 아니다.
2. `A_ONLY`에서도 `PASS` informational로 유지한다.
3. `A_PLUS_B`인데 B가 thin sample / manual review / reduce rollout이면 `WARN` informational 허용
4. checklist wording은 `B family remains guarded`, `A remains anchor`, `review B rollout guardrails first` 정도로 제한한다.

## 7. Operator Dashboard 반영안
추가:
1. `signal_funnel.multi_strategy_ab_expansion`
2. portfolio candidate drill-down의 additive `strategy_cluster` / `multi_strategy_overlay`

제한:
1. aggregate summary + candidate drill-down additive field까지만 허용한다.
2. recent intent row, approval snapshot, execution row에는 퍼뜨리지 않는다.
3. `promotion_governance`, `operator_action_priority`, `capital_allocator`와 merge하지 않는다.

## 8. README 반영안
추가 위치:
1. 전략 mode policy 설명 근처
2. governance stack 설명 앞

핵심 설명:
1. raw `strategy_family`와 A/B overlay의 관계
2. `A_ONLY / A_PLUS_B / RESEARCH`에서 A/B family를 어떻게 읽는지
3. first-wave에서 `b_continuation`이 guarded/probation 중심이라는 점
4. approval / rollout DB / sizing authority를 직접 바꾸지 않는다는 점

## 9. 비반영 Surface
추가 금지:
1. `ExecutionApproval`
2. `approval_snapshot`
3. `plan.validity` raw family rewrite
4. rollout policy DB row
5. `operator_action_priority` hard ordering
6. raw `strategy_mode` enum 재정의

## 10. 구현 단계 가이드
1. raw family를 A/B overlay로 변환하는 helper를 별도 서비스로 둔다.
2. scanner / portfolio는 row-level additive field를 붙이고, validation / checklist / dashboard는 shared aggregate summary를 읽는다.
3. `strategy_mode_policy.allowed_families`와 raw family gate는 그대로 유지하고 overlay는 explanation layer로만 사용한다.
4. `b_continuation`은 shadow/probation guardrail을 summary와 row overlay 모두에서 같은 reason code로 설명한다.

## 11. 완료 기준
1. scanner / portfolio / validation / checklist / dashboard / README가 같은 A/B language를 쓴다.
2. raw `strategy_family`와 A/B overlay가 충돌하지 않는다.
3. `A_ONLY -> A_PLUS_B` 확장이 B auto-live처럼 읽히지 않는다.
