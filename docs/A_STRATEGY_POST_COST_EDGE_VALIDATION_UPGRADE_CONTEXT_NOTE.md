# A Strategy Post-Cost Edge Validation Upgrade Context Note

최종 갱신: 2026-03-24
상태: final applied

## 1. 왜 이 작업을 하는가
- 지금 시스템의 대부분은 이미 `전략 운영 시스템` 수준으로 올라와 있다.
- 하지만 `A 전략`이 실제로 돈을 안정적으로 버는지는 아직 구조가 아니라 증거로 증명해야 한다.
- 이번 라운드 목적은 `A 전략 anchor를 방어할 수 있는 post-cost evidence layer`를 만드는 것이다.

## 2. 절대 규칙
1. `A 전략`의 raw family source-of-truth는 계속 `sweep_reversal`이다.
2. `a_reversal` overlay는 operating language이고, raw family accounting을 대체하지 않는다.
3. gross win-rate가 아니라 `post-cost EV / post-cost profitable rate / execution drag`를 우선한다.
4. thin sample bucket은 공격적으로 해석하지 않는다.
5. 이번 라운드는 validate / compare / report 중심이고 auto-stop authority는 나중에 분리한다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `score_to_outcome_funnel`
2. `outcome_control_trace`
3. `outcome_bucket_granularity`
4. `capital_allocator`
5. `alpha_research_pipeline`
6. `multi_strategy_ab / b_continuation_activation / strategy_cluster_balance`

아직 약한 것:
1. `A 전략 anchor`의 standalone post-cost summary
2. family / regime / session / cost-condition 기준 A edge 설명
3. A 전략 약화 구간을 한 summary로 읽는 operator language

## 4. 적용 원칙
1. `A 전략` 검증은 새 authority가 아니라 evidence layer다.
2. validation / checklist / dashboard / README가 같은 A-edge language를 써야 한다.
3. A 전략이 약하더라도 바로 rollout policy DB를 자동 변경하지 않는다.
4. B 전략 검증과 섞지 않고, 먼저 A anchor를 독립 평가한다.

## 5. 첫 라운드에서 보고 싶은 것
1. `A 전략이 post-cost 기준으로 아직 positive인가`
2. `어느 regime / session / cost bucket에서 edge가 무너지는가`
3. `execution drag가 alpha deterioration인지, implementation deterioration인지`
4. `현재 A anchor를 유지해도 되는가, observation 강화가 필요한가`

## 6. 다음 작업
1. A-strategy post-cost summary / report wiring 구현

## 7A. Item 1 계약 결론
1. 첫 라운드 평가 대상 family는 raw `sweep_reversal` 하나로만 고정한다.
2. `a_reversal`은 optional overlay label이지만, accounting과 evidence 판단은 계속 raw family 기준으로 유지한다.
3. edge state는 `validated_edge / fragile_edge / insufficient_edge / insufficient_sample` 네 개로만 고정한다.
4. direct surface는 validation / checklist / dashboard / README만 허용하고 approval / sizing / scanner / candidate row / rollout DB는 비범위로 둔다.
5. `score_to_outcome_funnel`의 family bucket을 primary evidence source로, `outcome_bucket_granularity`와 `family_execution_degradation_advisory`는 support-only modifier로 제한한다.
6. thin sample, post-cost non-positive, execution `watch/manual_review` 상태에서는 공격적 `keep_anchor` wording을 금지한다.

## 7B. Item 2 derivation 결론
1. family selection은 무조건 raw `sweep_reversal` row를 직접 찾고, `top_family_bucket`이나 `headline_cluster`로 대체하지 않는다.
2. `sample_state`는 `closed < 4 -> thin`, `4~7 -> usable`, `8+ -> mature`로 고정한다.
3. first-wave primary metric은 `family_post_cost_rate = baseline_cost_profitable_rate_from_closed`이고, family-level post-cost EV scalar는 아직 없으므로 `family_post_cost_ev`는 `None`을 허용한다.
4. edge precedence는 `insufficient_sample -> insufficient_edge -> fragile_edge -> validated_edge`로 고정한다.
5. `family_post_cost_rate <= 0.3`, family execution `manual_review`, approval manual-review/hard-clamp는 `insufficient_edge`를 먼저 만든다.
6. `0.3~0.5` 구간, execution `watch`, soft-clamp, cost-condition divergence, post-cost deterioration focus는 `fragile_edge`를 만든다.
7. `validated_edge`는 `family_post_cost_rate >= 0.5`, usable/mature sample, healthy execution, no clamp, no strong weakest-axis drag를 모두 만족할 때만 허용한다.

## 7C. Item 3 patch 결론
1. validation에는 top-level `a_strategy_post_cost_edge_validation_available`, `a_strategy_post_cost_edge_validation_summary`, markdown section `## A Strategy Post-Cost Edge Validation`를 추가하는 방향으로 고정한다.
2. checklist는 blocking이 아닌 informational item `A Strategy Post-Cost Edge Validation`으로만 반영하고, `fragile_edge`와 `insufficient_edge`에만 `WARN` informational을 허용한다.
3. dashboard는 `signal_funnel.a_strategy_post_cost_edge_validation` aggregate summary만 노출하고 candidate row나 approval snapshot으로 퍼뜨리지 않는다.
4. README는 `Strategy Cluster Balance` 뒤, `Promotion Governance` 앞에 배치해 `A anchor evidence verdict`가 A/B cluster layer와 promotion layer 사이에 위치하도록 정리한다.
5. 이번 단계에서도 approval / sizing / rollout DB / scanner / portfolio candidate row는 비범위로 유지한다.

## 7D. Item 4 구현 결론
1. 새 helper는 raw `sweep_reversal` family row를 직접 읽고, `family_post_cost_rate`, `sample_state`, approval/sizing penalty, weakest-axis drag, `post_cost_ev_deterioration` research focus를 합쳐 `validated_edge / fragile_edge / insufficient_edge / insufficient_sample` verdict를 계산한다.
2. validation에는 top-level summary와 markdown section `## A Strategy Post-Cost Edge Validation`가 추가되고, checklist에는 informational item, dashboard에는 `signal_funnel.a_strategy_post_cost_edge_validation`가 추가된다.
3. `family_post_cost_ev`는 아직 stable family scalar가 없어서 first-wave에서는 `None` 허용으로 유지하고 `family_post_cost_rate`를 primary scalar로 사용한다.
4. candidate row, scanner, approval snapshot, rollout DB는 이번 단계에서도 건드리지 않는다.

## 7E. Item 5 테스트/문서 결론
1. helper unit test는 `validated_edge` healthy case와 `manual_review -> insufficient_edge` precedence case를 직접 고정한다.
2. validation / checklist / dashboard / API smoke 테스트는 `a_strategy_post_cost_edge_validation` 키 존재와 핵심 semantics(`family=sweep_reversal`, `edge_state`, `validation_bias`)를 회귀로 묶는다.
3. README에는 `A Strategy Post-Cost Edge Validation` 섹션과 operator surface 설명을 추가해 A/B cluster layer와 promotion layer 사이에 A-anchor evidence verdict를 명시한다.
4. 이번 단계도 scanner / candidate row / approval / rollout DB는 비범위로 유지한다.

## 7F. Item 6 self-check 결론
1. `a_strategy_post_cost_edge_validation`는 helper, validation, checklist, dashboard, README에만 존재하고 scanner / candidate row / approval / sizing / rollout DB로는 번지지 않았다.
2. raw family source-of-truth는 계속 `sweep_reversal`로 유지되고, `a_reversal` overlay는 operator language에만 머문다.
3. first-wave primary metric은 여전히 `family_post_cost_rate`이고, `family_post_cost_ev`는 stable scalar가 생기기 전까지 optional `None`으로 남겨 false precision을 피한다.
4. 이번 라운드는 compare-only A-anchor evidence layer로 닫혔고, kill condition auto-stop authority는 다음 단계로 분리한다.
