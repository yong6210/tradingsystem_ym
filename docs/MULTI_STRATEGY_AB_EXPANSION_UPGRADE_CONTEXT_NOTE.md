# Multi Strategy AB Expansion Upgrade Context Note

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 왜 이 작업을 하는가
- 현재 엔진은 control / governance / promotion language는 충분히 올라왔지만, alpha source는 여전히 단일 family 편향이 강하다.
- `A_ONLY`는 안정적일 수 있어도 시장 구조가 바뀌면 throughput 과 opportunity capture 한계가 분명하다.
- 이번 라운드 목적은 전략 수를 늘리는 것이 아니라, `A(reversal)`와 `B(continuation/breakout)`를 같은 operating language 안에 올리는 것이다.

## 2. 절대 규칙
1. B 전략은 바로 auto-live 강제하지 않는다.
2. 기존 A 전략 source-of-truth를 깨지 않는다.
3. family-first governance 구조를 유지한다.
4. 첫 단계는 shadow / probation / compare-only 중심으로 간다.

## 3A. Item 1 계약 결론
1. 허용 family는 `a_reversal / b_continuation` 두 개로만 고정한다.
2. `a_reversal`은 current production anchor, `b_continuation`은 first-class family지만 initial rollout은 shadow/probation 중심으로 둔다.
3. 직접 반영 surface는 scanner / portfolio / validation / checklist / dashboard / README까지로 제한한다.
4. thin sample, manual review, family-first accounting guardrail을 계약 단계에서 먼저 고정한다.

## 3B. Item 2 derivation 결론
1. raw `strategy_family`는 그대로 source-of-truth로 두고, 그 위에 A/B overlay를 얹는다.
2. first-wave mapping은 `sweep_reversal -> a_reversal`, `trend_continuation -> b_continuation`, `range_rotation -> research_only_sidecar`로 고정한다.
3. `A_ONLY`에서는 `a_reversal`만 live-eligible, `A_PLUS_B`에서는 `a_reversal + b_continuation`을 같이 읽되 B는 thin sample / manual review / reduce rollout guardrail을 통과해야 한다.
4. `b_continuation`은 first-wave에서 “available but guarded” 언어를 유지하고, raw family와 rollout authority를 뒤집지 않는다.
5. A/B overlay는 raw family replacement가 아니라 compare-only operating interpretation layer다.

## 3C. Item 3 patch 결론
1. scanner와 portfolio는 raw `strategy_family`를 유지한 채 `strategy_cluster`와 `multi_strategy_overlay`를 additive로만 붙인다.
2. validation / checklist / dashboard는 별도 `multi_strategy_ab_summary` cluster를 공유하고, approval / rollout DB / sizing authority로는 퍼뜨리지 않는다.
3. `/portfolio/budget` candidate row에는 `strategy_family`를 명시적으로 포함시키고 A/B overlay는 explanation layer로만 사용한다.
4. first-wave README wording은 `A remains anchor`, `B is available but guarded`, `range rotation stays research-only sidecar`로 고정한다.

## 3D. Item 4 구현 결론
1. [multi_strategy_ab.py](/Users/yumin/Documents/trading/app/services/multi_strategy_ab.py#L1) 에 raw family -> A/B overlay와 aggregate summary helper를 추가했다.
2. scanner와 `/portfolio/budget` candidate row는 `strategy_cluster`, `strategy_cluster_status`, `multi_strategy_overlay`를 additive로 노출한다.
3. validation / checklist / dashboard는 shared `multi_strategy_ab_summary`를 읽고, `A remains anchor / B available but guarded / range rotation research-only sidecar` 언어를 같은 shape로 유지한다.
4. raw `strategy_family`, `strategy_mode`, approval, rollout DB, sizing authority는 그대로 유지했다.

## 3E. Item 5 테스트 및 문서 동기화 결론
1. [test_multi_strategy_ab.py](/Users/yumin/Documents/trading/tests/test_multi_strategy_ab.py#L1) 로 helper의 `compare_only / available_but_guarded / probation_ready` 경로를 직접 고정했다.
2. portfolio / validation / checklist / dashboard / API smoke 테스트에 `multi_strategy_ab_summary`, `strategy_cluster`, `strategy_cluster_status`, `multi_strategy_overlay` 계약을 추가했다.
3. [README.md](/Users/yumin/Documents/trading/README.md#L164) 에 `Multi Strategy AB Expansion` 섹션과 operator surface 설명을 추가해 현재 runtime language를 entrypoint 문서와 맞췄다.

## 3F. Item 6 self-check 결론
1. `multi_strategy_ab`는 [multi_strategy_ab.py](/Users/yumin/Documents/trading/app/services/multi_strategy_ab.py#L1), scanner, `/portfolio/budget`, validation, checklist, dashboard, README에만 additive로 붙어 있고 approval / rollout DB / sizing authority는 그대로 유지된다.
2. raw `strategy_family`는 계속 source-of-truth이고 `strategy_cluster`, `strategy_cluster_status`, `multi_strategy_overlay`, `multi_strategy_ab_summary`는 compare-only operating interpretation layer로만 남아 있다.
3. B family는 여전히 `available but guarded` 기본값과 thin-sample/manual-review guardrail을 유지해서, A/B 확장이 곧바로 auto-live처럼 읽히는 회귀는 보이지 않는다.
