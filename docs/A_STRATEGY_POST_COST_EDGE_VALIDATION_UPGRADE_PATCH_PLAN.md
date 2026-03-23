# A Strategy Post-Cost Edge Validation Upgrade Patch Plan

최종 갱신: 2026-03-24
상태: Item 3 baseline fixed

## 1. 목적
- `A 전략(sweep_reversal)`의 post-cost edge verdict를 어떤 surface에 어떤 wording으로 보여줄지 먼저 고정한다.
- 새 summary는 `A anchor evidence layer`로만 두고 approval / sizing / rollout authority로 번지지 않게 한다.
- multi-strategy / promotion / positive expansion 계층과 역할이 섞이지 않도록 반영 위치와 문구를 제한한다.

## 2. Validation Report 반영안
추가:
1. top-level `a_strategy_post_cost_edge_validation_available`
2. top-level `a_strategy_post_cost_edge_validation_summary`
3. markdown section `## A Strategy Post-Cost Edge Validation`

`a_strategy_post_cost_edge_validation_summary` 최소 필드:
1. `family`
2. `edge_state`
3. `validation_bias`
4. `sample_state`
5. `family_post_cost_rate`
6. `family_post_cost_ev`
7. `weakest_axis`
8. `weakest_bucket`
9. `confidence`
10. `summary`
11. `reason_codes`
12. `source_summary`

표현 원칙:
1. `A anchor remains supported`, `anchor fragility needs monitoring`, `anchor confidence should be reduced`, `gather more post-cost evidence` 같은 evidence wording만 사용한다.
2. deterministic alpha-proof language는 금지한다.
3. family-level `post_cost_ev`가 없으면 `None` 허용으로 명시하고 `family_post_cost_rate`를 primary metric으로 유지한다.

## 3. Operations Checklist 반영안
추가:
1. informational item `A Strategy Post-Cost Edge Validation`

체크리스트 동작:
1. blocking item이 아니다.
2. summary unavailable이면 `PASS` informational로 둔다.
3. `edge_state=validated_edge`는 `PASS` informational로 유지한다.
4. `edge_state=fragile_edge`와 `edge_state=insufficient_edge`는 `WARN` informational을 허용한다.
5. `edge_state=insufficient_sample`은 failure가 아니라 evidence accumulation wording으로만 설명한다.

evidence 최소 필드:
1. `available`
2. `family`
3. `edge_state`
4. `validation_bias`
5. `sample_state`
6. `family_post_cost_rate`
7. `weakest_axis`
8. `weakest_bucket`
9. `reason_codes`
10. `source_summary`

## 4. Operator Dashboard 반영안
추가:
1. `signal_funnel.a_strategy_post_cost_edge_validation`

제한:
1. aggregate summary만 노출한다.
2. `/scanner/top`, `/portfolio/budget`, approval snapshot, recent intents drill-down에는 퍼뜨리지 않는다.
3. `multi_strategy_ab_expansion`, `strategy_cluster_balance`, `promotion_governance`, `positive_evidence_expansion`과 merge하지 않는다.

포함 필드:
1. `family`
2. `edge_state`
3. `validation_bias`
4. `sample_state`
5. `family_post_cost_rate`
6. `weakest_axis`
7. `weakest_bucket`
8. `confidence`
9. `summary`
10. `reason_codes`
11. `source_summary`

역할:
1. `multi_strategy_ab_expansion`은 A/B coexistence language
2. `strategy_cluster_balance`는 cluster mix posture
3. `a_strategy_post_cost_edge_validation`은 A anchor evidence verdict
4. `promotion_governance`는 승격 review decision language

## 5. README 반영안
추가 위치:
1. `Strategy Cluster Balance` 뒤
2. `Promotion Governance` 앞

핵심 설명:
1. raw `sweep_reversal` family를 직접 읽는다는 점
2. `validated_edge / fragile_edge / insufficient_edge / insufficient_sample`이 compare-only A-anchor evidence state라는 점
3. `family_post_cost_rate`가 first-wave primary metric이고 `family_post_cost_ev`는 optional scalar라는 점
4. validation / checklist / dashboard가 같은 `a_strategy_post_cost_edge_validation_summary`를 읽는다는 점
5. approval / sizing / rollout DB를 직접 바꾸지 않는다는 점

README Operator Surfaces 보강:
1. `POST /validation/report`
   - `a_strategy_post_cost_edge_validation_summary` 설명 1줄 추가
2. `POST /operations/checklist`
   - `A Strategy Post-Cost Edge Validation` informational item 추가
3. `GET /execution/operator-dashboard`
   - `signal_funnel.a_strategy_post_cost_edge_validation` 추가

## 6. 비반영 Surface
추가 금지:
1. `ExecutionApproval`
2. `approval_snapshot`
3. `plan.validity`
4. `/scanner/top`
5. `/portfolio/budget` candidate row
6. rollout policy DB row
7. `multi_strategy_ab` raw overlay object merge
8. `strategy_cluster_balance` candidate ordering authority merge

## 7. 구현 단계 가이드
1. summary helper는 raw `sweep_reversal` family row를 직접 읽는 compare-only layer로 둔다.
2. weakest-axis 설명은 `outcome_bucket_granularity` 우선, 없으면 regime/session negative bucket fallback으로 제한한다.
3. `validated_edge`여도 `keep_anchor`는 evidence wording일 뿐 auto-expand나 auto-promote language로 쓰지 않는다.
4. `fragile_edge`와 `insufficient_edge`는 `A 전략이 끝났다`보다 `anchor confidence`와 `post-cost deterioration` 언어를 우선한다.
