# B Continuation Edge Validation Upgrade Patch Plan

최종 갱신: 2026-03-24
상태: Item 3 baseline fixed

## 1. 목적
- `B 전략(trend_continuation)`의 post-cost edge와 diversification verdict를 어떤 surface에 어떤 wording으로 보여줄지 먼저 고정한다.
- 새 summary는 `B diversification evidence layer`로만 두고 activation / approval / sizing / rollout authority로 번지지 않게 한다.
- `b_continuation_activation`, `strategy_cluster_balance`, `capital_allocator`와 역할이 섞이지 않도록 반영 위치와 문구를 제한한다.

## 2. Validation Report 반영안
추가:
1. top-level `b_continuation_edge_validation_available`
2. top-level `b_continuation_edge_validation_summary`
3. markdown section `## B Continuation Edge Validation`

`b_continuation_edge_validation_summary` 최소 필드:
1. `raw_family`
2. `strategy_cluster`
3. `edge_state`
4. `validation_bias`
5. `sample_state`
6. `family_post_cost_rate`
7. `family_post_cost_ev`
8. `diversification_state`
9. `drawdown_contribution_state`
10. `a_b_correlation_proxy`
11. `weakest_axis`
12. `weakest_bucket`
13. `confidence`
14. `summary`
15. `reason_codes`
16. `source_summary`

표현 원칙:
1. `B still offers usable diversification evidence`, `B diversification remains fragile`, `B confidence should be reduced`, `gather more B evidence` 같은 evidence wording만 사용한다.
2. deterministic diversification-proof language는 금지한다.
3. exact correlation coefficient나 realized portfolio attribution이 없으면 proxy language임을 명시한다.

## 3. Operations Checklist 반영안
추가:
1. informational item `B Continuation Edge Validation`

체크리스트 동작:
1. blocking item이 아니다.
2. summary unavailable이면 `PASS` informational로 둔다.
3. `edge_state=validated_edge`는 `PASS` informational로 유지한다.
4. `edge_state=fragile_edge`와 `edge_state=insufficient_edge`는 `WARN` informational을 허용한다.
5. `edge_state=insufficient_sample`은 failure가 아니라 evidence accumulation wording으로만 설명한다.

evidence 최소 필드:
1. `available`
2. `raw_family`
3. `edge_state`
4. `validation_bias`
5. `sample_state`
6. `family_post_cost_rate`
7. `diversification_state`
8. `drawdown_contribution_state`
9. `a_b_correlation_proxy`
10. `weakest_axis`
11. `weakest_bucket`
12. `reason_codes`
13. `source_summary`

## 4. Operator Dashboard 반영안
추가:
1. `signal_funnel.b_continuation_edge_validation`

제한:
1. aggregate summary만 노출한다.
2. `/scanner/top`, `/portfolio/budget`, approval snapshot, recent intents drill-down에는 퍼뜨리지 않는다.
3. `b_continuation_activation`, `strategy_cluster_balance`, `capital_allocator`, `promotion_governance`와 merge하지 않는다.

포함 필드:
1. `raw_family`
2. `strategy_cluster`
3. `edge_state`
4. `validation_bias`
5. `sample_state`
6. `family_post_cost_rate`
7. `diversification_state`
8. `drawdown_contribution_state`
9. `a_b_correlation_proxy`
10. `weakest_axis`
11. `weakest_bucket`
12. `confidence`
13. `summary`
14. `reason_codes`
15. `source_summary`

역할:
1. `b_continuation_activation`은 rollout / guardrail posture
2. `strategy_cluster_balance`는 current A/B mix posture
3. `capital_allocator`는 scarce capital tilt
4. `b_continuation_edge_validation`은 B diversification evidence verdict

## 5. README 반영안
추가 위치:
1. `B Continuation Activation` 뒤
2. `Strategy Cluster Balance` 앞

핵심 설명:
1. raw `trend_continuation` family를 직접 읽는다는 점
2. `validated_edge / fragile_edge / insufficient_edge / insufficient_sample`이 compare-only B evidence state라는 점
3. `family_post_cost_rate`가 first-wave primary metric이고 `family_post_cost_ev`는 optional scalar라는 점
4. `a_b_correlation_proxy`와 `drawdown_contribution_state`는 first-wave proxy language라는 점
5. validation / checklist / dashboard가 같은 `b_continuation_edge_validation_summary`를 읽는다는 점
6. activation posture, approval, sizing, rollout DB를 직접 바꾸지 않는다는 점

README Operator Surfaces 보강:
1. `POST /validation/report`
   - `b_continuation_edge_validation_summary` 설명 1줄 추가
2. `POST /operations/checklist`
   - `B Continuation Edge Validation` informational item 추가
3. `GET /execution/operator-dashboard`
   - `signal_funnel.b_continuation_edge_validation` 추가

## 6. 비반영 Surface
추가 금지:
1. `ExecutionApproval`
2. `approval_snapshot`
3. `plan.validity`
4. `/scanner/top`
5. `/portfolio/budget` candidate row
6. rollout policy DB row
7. `b_continuation_activation` row object merge
8. `strategy_cluster_balance` candidate ordering authority merge
9. `capital_allocator` authority merge

## 7. 구현 단계 가이드
1. summary helper는 raw `trend_continuation` family row를 직접 읽는 compare-only layer로 둔다.
2. diversification proxy는 `strategy_cluster_balance`와 `capital_allocator`를 읽되, exact correlation / drawdown attribution으로 과장하지 않는다.
3. `validated_edge`여도 `support_guarded_activation`은 evidence wording일 뿐 auto-live, auto-promote, auto-scale language로 쓰지 않는다.
4. `fragile_edge`와 `insufficient_edge`는 `B가 끝났다`보다 `diversification confidence`와 `post-cost deterioration` 언어를 우선한다.
