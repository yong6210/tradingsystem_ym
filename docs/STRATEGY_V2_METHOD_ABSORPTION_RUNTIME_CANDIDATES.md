# Strategy v2 Method Absorption Runtime Candidates

최종 갱신: 2026-03-23
상태: Checklist item 4 completed

## 1. 목적
- 외부 방법론에서 흡수 가능한 개념을 현재 runtime contract 기준으로 분류한다.
- `기존 계약 재사용`, `낮은 리스크 additive 후보`, `지금은 보류/배제`를 분리해 다음 단계 검증 범위를 고정한다.

## 2. 기존 계약으로 이미 커버되는 항목
### 2.1 구조 / 반응
- 외부 `CHoCH/BOS`
  - 지금도 별도 신호 없이 `reaction_classification`, `reaction_rejection_score`, `reaction_acceptance_score`, `reaction_input`으로 해석 가능
  - 우선 새 필드 추가 없이 기존 계약 재사용

### 2.2 실행 존
- 외부 `FVG/OB revisit`
  - 지금도 `zone_type`, `strategy_scorecard_buckets.execution_zone_quality`, `strategy_family_reason`로 충분히 해석 가능
  - 우선 새 필드 추가 없이 기존 계약 재사용

### 2.3 세션 컨텍스트
- 외부 `opening range / session box / premarket context`
  - 지금도 `session_guidance`, `session_penalty`, `prior day/session high-low`, `thesis_fingerprint.liquidity_narrative` 일부로 해석 가능
  - 우선 운영 해석부터 고정하고, contract 추가는 실험 근거가 생길 때만 고려

### 2.4 위치 / 내러티브
- 외부 `HTF level`, `equal highs/lows`, `premium/discount`
  - 지금도 `strategy_scorecard.buckets.location`, `thesis_fingerprint.liquidity_narrative`, `strategy_family_reason`에 녹아 있음
  - 우선 새 top-level field는 추가하지 않음

## 3. 낮은 리스크 additive 후보
### 후보 A. `location_reference`
목적:
- 운영자와 validation이 현재 후보의 `상위 위치 근거`를 더 직접 읽게 한다.

권장 필드:
- `location_reference.primary_type`
- `location_reference.primary_label`
- `location_reference.secondary_type`
- `location_reference.premium_discount_state`
- `location_reference.edge_proximity_atr`

권장 저장 위치:
- `plan.validity.location_reference`
- `scanner.top[*].location_reference`
- `portfolio.accepted_candidates[*].location_reference`

우선순위:
- `medium`

이유:
- 기존 `strategy_scorecard`와 `liquidity_narrative`를 깨지 않으면서 operator readability만 높일 수 있다.

### 후보 B. `session_liquidity_reference`
목적:
- `opening range / premarket box / session high-low`를 독립 전략이 아니라 세션 유동성 보조 정보로 기록한다.

권장 필드:
- `session_liquidity_reference.reference_type`
- `session_liquidity_reference.range_high`
- `session_liquidity_reference.range_low`
- `session_liquidity_reference.close_outside_count`
- `session_liquidity_reference.breakout_side`
- `session_liquidity_reference.as_of_ts`

권장 저장 위치:
- `plan.validity.session_liquidity_reference`
- `scanner.top[*].session_liquidity_reference`

우선순위:
- `low`

이유:
- 현재 `session_guidance`는 시간대/penalty 중심이라, 세션 박스 자체를 기록하려면 별도 additive object가 더 맞다.
- 다만 execution quality가 안정되기 전에는 ranking/hard block에 연결하지 않는다.

### 후보 C. `reaction_evidence`
목적:
- 외부 `CHoCH/BOS` 표현을 runtime에서 직접 쓰지 않고, 현재 반응 증거를 더 읽기 쉽게 만든다.

권장 필드:
- `reaction_evidence.structure_shift_hint`
- `reaction_evidence.reclaim_speed_bucket`
- `reaction_evidence.close_outside_bucket`
- `reaction_evidence.retest_status`
- `reaction_evidence.efficiency_state`

권장 저장 위치:
- `plan.validity.reaction_evidence`
- `execution_approval.context_snapshot.reaction_evidence`

우선순위:
- `medium`

이유:
- 실제 source-of-truth는 계속 `reaction_classification`과 `reaction_input`이고, 이 필드는 읽기 쉬운 summary alias로만 둔다.

### 후보 D. `execution_refinement`
목적:
- 하위 시간대 확인이 live approval이 아니라 `execution refinement`였다는 점을 명시한다.

권장 필드:
- `execution_refinement.timeframe`
- `execution_refinement.confirmation_required`
- `execution_refinement.confirmation_reason`
- `execution_refinement.compare_only`

권장 저장 위치:
- `plan.validity.execution_refinement`
- `execution_approval.executable_plan`

우선순위:
- `low`

이유:
- 1m 성격의 확인 로직을 붙일 때도 전략 전체가 `1m breakout strategy`로 오해되지 않게 해준다.

## 4. 지금은 보류 또는 배제할 후보
### 보류
1. `session box`를 score/rank에 직접 반영하는 하드 규칙
2. `1m confirmation`을 approval hard gate로 올리는 규칙
3. `premarket range breakout` 전용 family

보류 이유:
- 표본이 얇고 execution advisory가 `manual_review` 상태라, 지금은 operator readability 이상의 승격 근거가 없다.

### 배제
1. `BOS`
2. `CHoCH`
3. `EMA stack`
4. `RSI`
5. `Elliott wave count`
6. `Fib 1.272 target`
7. `high win-rate / low-RR` contract

배제 이유:
- 패턴 또는 지표 자체가 source-of-truth가 되기 쉽고, 현재 전략의 `Location / Liquidity / Reaction / EV` 우선순위와 충돌한다.

## 5. 권장 진행 순서
1. 먼저 `reaction_evidence`와 `location_reference`처럼 읽기 쉬운 alias성 후보만 검토
2. `session_liquidity_reference`는 compare-only 실험 대상으로만 제한
3. `execution_refinement`는 1m branch 실험을 다시 열 때만 고려
4. 어떤 후보도 validation에서 `EV / p5 / max drawdown / execution degradation` 개선이 없으면 승격하지 않음

## 6. 현재 결론
- 가장 안전한 방향은 `기존 reaction/session/scorecard/thesis contract를 먼저 재활용`하는 것이다.
- 새 runtime 후보가 필요하더라도 `additive summary object` 수준에 머물러야 한다.
- `BOS/CHoCH/FVG`를 top-level primary contract로 승격하는 방향은 현재 전략과 맞지 않는다.
