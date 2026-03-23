# B Continuation Edge Validation Upgrade Context Note

최종 갱신: 2026-03-24
상태: complete

## 1. 왜 이 작업을 하는가
- 지금 시스템은 `A anchor + B guarded activation` 구조까지는 올라와 있다.
- 하지만 `B`가 실제로 돈을 버는 diversification source인지, 아니면 구조만 좋은 compare-only family인지 아직 증거로 분리되지 않았다.
- 이번 라운드 목적은 `trend_continuation`의 post-cost edge와 `A` 대비 diversification value를 같은 evidence layer로 만드는 것이다.

## 2. 절대 규칙
1. `B 전략`의 raw family source-of-truth는 계속 `trend_continuation`이다.
2. `b_continuation`은 operating label이고 raw family accounting을 대체하지 않는다.
3. gross outcome이 아니라 `post-cost rate / execution drag / correlation proxy / drawdown contribution`을 우선한다.
4. thin sample B bucket은 공격적으로 해석하지 않는다.
5. 이번 라운드는 validate / compare / report 중심이고 auto-kill authority는 나중에 분리한다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `b_continuation_activation`
2. `multi_strategy_ab`
3. `strategy_cluster_balance`
4. `capital_allocator`
5. `outcome_bucket_granularity`
6. `alpha_research_pipeline`

아직 약한 것:
1. `B 전략`의 standalone post-cost edge summary
2. `A vs B` correlation / diversification 가치 설명
3. `B`가 drawdown에 기여하는 방식 또는 완충하는 방식을 한 summary로 읽는 operator language

## 4. 적용 원칙
1. `B 전략` 검증은 새 authority가 아니라 evidence layer다.
2. validation / checklist / dashboard / README가 같은 `B-edge` language를 써야 한다.
3. `B`가 약하더라도 바로 rollout policy DB를 자동 변경하지 않는다.
4. `b_continuation_activation`과 섞지 않고, 먼저 `activation posture`와 `edge validation`을 역할 분리한다.

## 5. 첫 라운드에서 보고 싶은 것
1. `B 전략이 post-cost 기준으로 아직 positive인가`
2. `A 대비 상관이 너무 높아 diversification value가 약한가`
3. `B가 drawdown을 키우는지, 완충하는지, 중립인지`
4. `현재 B guarded activation posture를 유지해도 되는가, confidence를 낮춰야 하는가`

## 6. 다음 작업
1. B continuation edge summary / report wiring 구현

## 6A. Item 1 계약 결론
1. 첫 라운드 평가 대상 family는 raw `trend_continuation` 하나로만 고정한다.
2. `b_continuation`은 optional operating label이지만, accounting과 evidence 판단은 계속 raw family 기준으로 유지한다.
3. edge state는 `validated_edge / fragile_edge / insufficient_edge / insufficient_sample` 네 개로만 고정한다.
4. diversification language는 `diversification_state`, `drawdown_contribution_state`, `a_b_correlation_proxy` 세 축으로만 제한한다.
5. direct surface는 validation / checklist / dashboard / README만 허용하고 scanner / candidate row / approval / sizing / rollout DB는 비범위로 둔다.
6. thin sample, post-cost non-positive, high correlation proxy, drawdown-additive 상태에서는 공격적 `support_guarded_activation` wording을 금지한다.

## 6B. Item 2 derivation 결론
1. B edge verdict는 raw `trend_continuation` family row를 직접 읽고, A 비교용 reference는 raw `sweep_reversal` row를 support-only로 사용한다.
2. first-wave primary metric은 `family_post_cost_rate = baseline_cost_profitable_rate_from_closed`이고, family-level post-cost EV scalar는 아직 없으므로 `family_post_cost_ev`는 `None`을 허용한다.
3. `a_b_correlation_proxy`와 `drawdown_contribution_state`는 exact covariance/attribution이 아니라 `strategy_cluster_balance`와 `capital_allocator`를 읽는 proxy language로만 제한한다.
4. activation posture는 support-only context로 두고, `research_only / blocked / guarded_probation`이 edge verdict를 자동으로 낮추지 않게 분리한다.
5. edge precedence는 `insufficient_sample -> insufficient_edge -> fragile_edge -> validated_edge`로 고정하고, high-overlap plus drawdown-additive 조합은 hard-negative 쪽으로 우선한다.

## 6C. Item 3 patch 결론
1. validation에는 top-level `b_continuation_edge_validation_available`, `b_continuation_edge_validation_summary`, markdown section `## B Continuation Edge Validation`를 추가하는 방향으로 고정한다.
2. checklist는 blocking이 아닌 informational item `B Continuation Edge Validation`으로만 반영하고, `fragile_edge`와 `insufficient_edge`에만 `WARN` informational을 허용한다.
3. dashboard는 `signal_funnel.b_continuation_edge_validation` aggregate summary만 노출하고 candidate row나 approval snapshot으로 퍼뜨리지 않는다.
4. README는 `B Continuation Activation` 뒤, `Strategy Cluster Balance` 앞에 배치해 `activation posture -> B evidence verdict -> current mix posture` 순서가 되게 정리한다.
5. 이번 단계에서도 approval / sizing / rollout DB / scanner / portfolio candidate row는 비범위로 유지한다.

## 6D. Item 4 구현 결론
1. 새 helper는 raw `trend_continuation` family row를 직접 읽고, `family_post_cost_rate`, `sample_state`, family execution status, weakest-axis drag, activation posture context, cluster-balance proxy, allocator pressure를 합쳐 `validated_edge / fragile_edge / insufficient_edge / insufficient_sample` verdict를 계산한다.
2. `a_b_correlation_proxy`와 `drawdown_contribution_state`는 exact covariance/attribution이 아니라 current mix와 allocator pressure를 읽는 first-wave proxy language로만 유지한다.
3. validation에는 top-level summary와 markdown section `## B Continuation Edge Validation`가 추가되고, checklist에는 informational item, dashboard에는 `signal_funnel.b_continuation_edge_validation`가 추가된다.
4. scanner, candidate row, approval snapshot, rollout DB는 이번 단계에서도 건드리지 않는다.

## 6E. Item 5 테스트/문서 결론
1. helper unit test는 `validated_edge` healthy/diversifying case와 `high_overlap + drawdown_additive -> insufficient_edge` precedence case를 직접 고정한다.
2. validation / checklist / dashboard / API smoke 테스트는 `b_continuation_edge_validation` 키 존재와 핵심 semantics(`raw_family=trend_continuation`, `edge_state`, `validation_bias`)를 회귀로 묶는다.
3. README에는 `B Continuation Edge Validation` 섹션과 operator surface 설명을 추가해 `B Continuation Activation`과 `Strategy Cluster Balance` 사이에 B diversification evidence verdict를 명시한다.
4. 이번 단계도 scanner / candidate row / approval / rollout DB는 비범위로 유지한다.

## 6F. Item 6 self-check 결론
1. `b_continuation_edge_validation`는 helper, strategy engine wiring, validation report, checklist, dashboard, README, tests에만 존재하고 scanner / candidate row / approval / sizing / rollout DB로는 번지지 않았다.
2. raw family source-of-truth는 계속 `trend_continuation`으로 유지되고, `b_continuation`은 operating label과 summary context로만 사용된다.
3. `b_continuation_activation`은 rollout posture, `b_continuation_edge_validation`은 diversification evidence, `strategy_cluster_balance`는 current mix posture라는 역할 분리가 유지된다.
4. helper unit test, surface 회귀, README 동기화까지 끝나 있어 이번 라운드는 compare-only B evidence layer로 안전하게 닫아도 된다.
