# Strategy v2 Session Box Alias Implementation Contract

최종 갱신: 2026-03-23
상태: Checklist item 1 completed

## 1. 목적
- `location_reference`, `session_liquidity_reference`의 실제 필드와 노출 surface를 확정한다.
- 이번 라운드 구현이 compare-only additive alias 범위를 넘지 않도록 계약을 먼저 고정한다.

## 2. alias object 계약
### 2.1 `location_reference`
필드:
- `primary_type`
- `primary_label`
- `secondary_type`
- `session_box_role`
- `edge_proximity_atr`

의미:
- 현재 후보의 HTF/MTF 위치 근거를 설명하는 compare-only alias다.
- `session_box_role`은 `reference_only` 또는 `refinement_only`만 허용한다.

### 2.2 `session_liquidity_reference`
필드:
- `reference_type`
- `range_start_ts`
- `range_end_ts`
- `range_high`
- `range_low`
- `breakout_side`
- `outside_close_state`
- `failed_acceptance`
- `as_of_ts`

의미:
- session box / opening range를 세션 유동성 reference로 기록하는 compare-only alias다.
- `outside_close_state`는 reaction source-of-truth가 아니라 보조 설명 필드다.

## 3. 노출 surface
### 3.1 `plan.validity`
저장:
- `validity.location_reference`
- `validity.session_liquidity_reference`

이유:
- scanner와 portfolio가 같은 stored plan validity를 재사용하도록 기준점을 하나로 맞춘다.

### 3.2 `GET /scanner/top`
대상 schema:
- `app/schemas/api.py::ScannerItemOut`

노출:
- `scanner.top[*].location_reference`
- `scanner.top[*].session_liquidity_reference`

이유:
- operator가 즉시 읽는 대표 candidate surface이기 때문이다.

### 3.3 `GET /portfolio/budget`
대상 schema:
- `app/schemas/api.py::PortfolioBudgetCandidateOut`

노출:
- `accepted_candidates[*].location_reference`
- `accepted_candidates[*].session_liquidity_reference`
- `blocked_candidates[*].location_reference`
- `blocked_candidates[*].session_liquidity_reference`

이유:
- portfolio 후보 row는 accepted/blocked가 같은 schema를 공유하므로 additive alias도 같은 방식으로 유지하는 편이 안전하다.

## 4. 이번 라운드 비노출 surface
1. top-level `PortfolioBudgetReportOut`
2. `ExecutionApproval`
3. `OrderIntentResponse`
4. `operations/checklist`
5. `outside_close_evidence`

이유:
- 이번 라운드는 candidate readability 개선이 목적이다.
- approval / intent / operator checklist까지 넓히면 compare-only 범위를 넘을 수 있다.

## 5. 구현 규칙
1. alias는 기존 `reaction_classification`, `reaction_input`, `strategy_family`, `strategy_grade`, `recommended_risk_r`를 대체하지 않는다.
2. alias가 파생 불가하면 field는 미노출 또는 `None` 처리하고 empty placeholder object는 만들지 않는다.
3. alias는 scoring, ranking, approval, sizing, lock semantics에 영향을 주지 않는다.
4. `outside close` 해석은 이번 라운드에서 `session_liquidity_reference.outside_close_state`까지만 기록하고, 별도 contract로 승격하지 않는다.

## 6. 다음 구현 순서
1. `plan.validity`에 alias 생성
2. `ScannerItemOut` schema와 `/scanner/top` row 노출
3. `PortfolioBudgetCandidateOut` schema와 `/portfolio/budget` 후보 row 노출
4. 테스트 및 문서 동기화
