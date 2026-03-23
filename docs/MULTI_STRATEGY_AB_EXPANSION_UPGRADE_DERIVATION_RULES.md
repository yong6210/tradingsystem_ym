# Multi Strategy AB Expansion Upgrade Derivation Rules

최종 갱신: 2026-03-23
상태: Item 2 baseline fixed

## 1. 목적
- 이 라운드는 기존 `strategy_family` 라우팅을 깨지 않고, 그 위에 `A/B` operating overlay를 얹는 규칙을 고정한다.
- 즉 raw family는 그대로 유지하고, `A_ONLY -> A_PLUS_B` 확장을 multi-strategy operating language로 해석하는 것이 목적이다.

## 2. raw family to A/B mapping
현재 `StrategyFamilyRouter`의 raw family는 그대로 source-of-truth로 유지한다.

first-wave mapping은 아래처럼 고정한다.
1. `sweep_reversal` -> `a_reversal`
2. `trend_continuation` -> `b_continuation`
3. `range_rotation` -> first-wave live A/B 범위에서는 제외하고 `research_only_sidecar`로 둔다
4. `legacy_zone_plan / unknown / none` -> A/B overlay 미적용

원칙:
1. `strategy_family` raw 값은 plan / scanner / portfolio / approval snapshot에서 계속 유지한다.
2. 새 A/B overlay는 family cluster 해석층이지 raw family 대체가 아니다.
3. first-wave live B family는 `trend_continuation` 하나만 허용한다.

## 3. mode interpretation
현재 mode language는 그대로 유지한다.
1. `A_ONLY`
- live-eligible family는 `a_reversal`만 허용한다.
- `b_continuation`은 scanner / validation / dashboard에서는 보일 수 있지만 approval/live execution은 막는다.

2. `A_PLUS_B`
- `a_reversal`과 `b_continuation`을 runtime scanner / portfolio / validation에서 같이 읽을 수 있다.
- 단, `b_continuation`은 family rollout / thin sample / execution guardrail을 통과한 경우에만 probation/live candidate로 해석한다.

3. `RESEARCH`
- `a_reversal`, `b_continuation`, `range_rotation` 모두 compare-only research candidate로만 읽는다.

## 4. first-wave B activation guardrail
`b_continuation`이 first-wave multi-strategy에서 live/probation 후보로 읽히려면 아래 조건을 모두 만족해야 한다.
1. raw family가 `trend_continuation`
2. thin sample 아님
3. family execution status가 `manual_review` 아님
4. rollout recommendation이 `reduce / research_only` 아님
5. strategy lifecycle이 `research`만으로 고정되지 않음

하나라도 어기면 `b_continuation`은 `shadow / research / probation review` 언어까지만 허용한다.

## 5. scanner / portfolio / validation interpretation
1. scanner
- raw `strategy_family`는 그대로 노출한다.
- compare-only `strategy_cluster` 또는 equivalent summary로 `a_reversal / b_continuation / research_only_sidecar` 해석을 덧붙일 수 있다.

2. portfolio
- accepted / blocked ordering은 raw family와 rollout authority를 우선한다.
- A/B overlay는 family mix, capital allocator, opportunity capture 같은 explanation layer에서만 먼저 쓴다.

3. validation / checklist / dashboard
- `A_ONLY vs A_PLUS_B` comparison과 family breakdown을 한 language로 읽게 만든다.
- `b_continuation`은 first-wave에서 “available but guarded”라는 wording을 유지한다.

## 6. first-wave non-goal
1. `range_rotation` live 투입
2. raw family schema 재작성
3. A/B overlay를 approval hard authority로 직접 승격
4. existing `strategy_mode` enum 재정의

## 7. precedence
multi-strategy 해석 우선순위는 아래처럼 고정한다.
1. raw `strategy_family`
2. raw `strategy_mode`
3. family rollout / approval / execution guardrail
4. A/B overlay cluster
5. compare-only operator wording

즉 A/B overlay는 raw family와 rollout authority를 뒤집지 않는다.

## 8. wording
1. `a_reversal`
- current production anchor

2. `b_continuation`
- first-wave secondary live family
- thin sample / manual review / reduce rollout이면 guarded/probation wording

3. `range_rotation`
- research-only sidecar in first wave

금지:
1. “A family removed” wording
2. “B family auto-live by default” wording
3. raw `strategy_family` replacement wording
