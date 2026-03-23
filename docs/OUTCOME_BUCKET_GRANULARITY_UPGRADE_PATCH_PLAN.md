# Outcome Bucket Granularity Upgrade Patch Plan

최종 갱신: 2026-03-23
상태: Item 3 baseline fixed

## 1. 목적
- `volatility_condition / cost_condition / liquidity_condition` 축을 어떤 surface에 어떤 언어로 보여줄지 먼저 고정한다.
- 새 condition bucket은 family headline을 대체하지 않고 `supporting condition split`으로만 노출한다.
- explanation layer와 authority layer가 섞이지 않도록 반영 범위를 제한한다.

## 2. Validation Report 반영안
추가:
1. top-level `outcome_bucket_granularity_available`
2. top-level `outcome_bucket_granularity_summary`
3. markdown section `## Outcome Bucket Granularity`

`outcome_bucket_granularity_summary` 최소 필드:
1. `family_focus`
2. `top_condition_axis`
3. `top_condition_bucket`
4. `confidence`
5. `summary`
6. `reason_codes`
7. `condition_axes`

표현 원칙:
1. `condition drag`, `condition split`, `supporting modifier` 언어를 사용한다.
2. deterministic root-cause language는 금지한다.
3. thin sample은 `insufficient condition coverage`로만 설명한다.

## 3. Operations Checklist 반영안
추가:
1. informational item `Outcome Bucket Granularity`

체크리스트 동작:
1. blocking item이 아니다.
2. summary unavailable이면 `PASS` informational로 둔다.
3. `cost_condition` 또는 `liquidity_condition` divergence가 큰 경우만 `WARN` informational을 허용한다.
4. action language는 `review cost-sensitive bucket`, `review shallow-liquidity bucket` 같은 soft wording만 사용한다.

## 4. Operator Dashboard 반영안
추가:
1. `signal_funnel.outcome_bucket_granularity`

제한:
1. aggregate summary만 노출한다.
2. candidate row, recent intent row, approval snapshot drill-down에는 퍼뜨리지 않는다.
3. `opportunity_capture`, `capital_allocator`, `positive_evidence_expansion`과 merge하지 않는다.

## 5. README 반영안
추가 위치:
1. `Positive Evidence Expansion` 뒤
2. `Opportunity Capture` 앞

핵심 설명:
1. family-first outcome view 위에 condition split을 additive하게 붙인다는 점
2. `volatility / cost / liquidity`는 supporting condition bucket이라는 점
3. compare-only interpretation이며 approval, sizing, rollout authority를 바꾸지 않는다는 점

## 6. 비반영 Surface
추가 금지:
1. `ExecutionApproval`
2. `approval_snapshot`
3. `plan.validity`
4. `/scanner/top`
5. `/portfolio/budget` candidate row
6. rollout policy DB row

## 7. 구현 단계 가이드
1. decomposition expansion은 `score_to_outcome_funnel` schema 재사용을 우선한다.
2. summary는 mature/usable bucket divergence가 있을 때만 headline을 만든다.
3. `liquidity_condition`은 raw depth가 아니라 liquidity proxy임을 surface wording에 명시한다.
