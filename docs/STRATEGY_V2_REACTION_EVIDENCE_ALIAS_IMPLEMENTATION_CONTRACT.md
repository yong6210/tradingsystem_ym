# Strategy v2 Reaction Evidence Alias Implementation Contract

최종 갱신: 2026-03-23
상태: Checklist item 1 completed

## 1. 목적
- `reaction_evidence`의 실제 필드와 노출 surface를 확정한다.
- 이번 라운드 구현이 compare-only additive alias 범위를 넘지 않도록 계약을 먼저 고정한다.

## 2. alias object 계약
### 2.1 `reaction_evidence`
필드:
- `structure_shift_hint`
- `reclaim_speed_bucket`
- `close_outside_bucket`
- `retest_status`
- `efficiency_state`

의미:
- 현재 후보의 구조적 반응 근거를 설명하는 compare-only alias다.
- 외부 `BOS/CHoCH` 표현을 직접 쓰지 않고, 기존 `reaction_classification`과 `reaction_input`를 사람이 빠르게 읽기 쉬운 요약층으로 정리한다.

권장 파생 원천:
- `validity.reaction_classification`
- `validity.reaction_input.reclaim_bars`
- `validity.reaction_input.outside_close_count`
- `validity.reaction_input.retest_hold`
- `validity.reaction_input.inefficiency_created`
- `validity.reaction_input.dwell_time_bars`

필드별 해석 경계:
- `structure_shift_hint`
  - `rejection_bias`, `acceptance_bias`, `mixed_response`, `not_available` 계열 요약만 허용한다.
  - 외부 구조 용어를 primary signal처럼 직접 기록하지 않는다.
- `reclaim_speed_bucket`
  - reclaim 속도를 `fast`, `moderate`, `slow_or_absent`, `not_available`처럼 bucket으로만 표현한다.
  - raw `reclaim_bars`는 계속 `reaction_input` source-of-truth에 남긴다.
- `close_outside_bucket`
  - swept level 바깥 close 정도를 `none`, `single`, `multiple`, `not_available` 같은 수준으로 요약한다.
  - raw `outside_close_count`는 계속 `reaction_input` source-of-truth에 남긴다.
- `retest_status`
  - `held`, `failed`, `not_observed`, `not_available` 수준으로만 정리한다.
  - retest 자체를 독립 트리거로 승격하지 않는다.
- `efficiency_state`
  - `inefficiency_created`, `no_inefficiency`, `not_available` 수준으로만 정리한다.
  - FVG/inefficiency는 여전히 execution zone / follow-through 설명에 그친다.

## 3. 노출 surface
### 3.1 `plan.validity`
저장:
- `validity.reaction_evidence`

이유:
- scanner와 portfolio가 같은 stored plan validity를 재사용하도록 기준점을 하나로 맞춘다.

### 3.2 `GET /scanner/top`
대상 schema:
- `app/schemas/api.py::ScannerItemOut`

노출:
- `scanner.top[*].reaction_evidence`

이유:
- operator가 즉시 읽는 대표 candidate surface이기 때문이다.

### 3.3 `GET /portfolio/budget`
대상 schema:
- `app/schemas/api.py::PortfolioBudgetCandidateOut`

노출:
- `accepted_candidates[*].reaction_evidence`
- `blocked_candidates[*].reaction_evidence`

이유:
- portfolio 후보 row는 accepted/blocked가 같은 schema를 공유하므로 additive alias도 같은 방식으로 유지하는 편이 안전하다.

## 4. 이번 라운드 비노출 surface
1. `ExecutionApproval`
2. `OrderIntentResponse`
3. `operations/checklist`
4. `validation/report`
5. 별도 top-level portfolio summary

이유:
- 이번 라운드는 candidate readability 개선이 목적이다.
- approval / intent / ops / validation top-level까지 넓히면 compare-only 범위를 넘거나 hard gate처럼 오해될 수 있다.

## 5. 구현 규칙
1. alias는 기존 `reaction_classification`, `reaction_input`, `strategy_family`, `strategy_grade`, `recommended_risk_r`를 대체하지 않는다.
2. alias가 파생 불가하면 field는 미노출 또는 `None` 처리하고 empty placeholder object는 만들지 않는다.
3. alias는 scoring, ranking, approval, sizing, lock semantics에 영향을 주지 않는다.
4. `BOS/CHoCH/FVG`를 raw label로 새 top-level field에 직접 노출하지 않는다.

## 6. 다음 구현 순서
1. 기존 `reaction_input` / `reaction_classification` 기반 파생 규칙 정리
2. `plan.validity`에 alias 생성
3. `ScannerItemOut` schema와 `/scanner/top` row 노출
4. `PortfolioBudgetCandidateOut` schema와 `/portfolio/budget` 후보 row 노출
5. 테스트 및 문서 동기화
