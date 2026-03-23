# Strategy v2 Session Box Absorption Runtime Candidates

최종 갱신: 2026-03-23
상태: Checklist item 4 completed

## 1. 목적
- 세션 박스 전략에서 흡수 가능한 개념을 현재 runtime contract 기준으로 분류한다.
- `기존 계약 재사용`, `낮은 리스크 additive 후보`, `지금은 보류/배제`를 분리해 다음 단계 비교 실험 범위를 고정한다.

## 2. 기존 계약으로 이미 커버되는 항목
### 2.1 세션 컨텍스트
- 외부 `opening range / premarket box / session box`
  - 지금도 `session_guidance`, `prior day/session high-low`, `thesis_fingerprint.liquidity_narrative`, `strategy_scorecard.buckets.session` 일부로 해석 가능하다.
  - 우선 새 authority field를 만들지 않고 기존 `session` 해석 계약을 재사용한다.

### 2.2 acceptance / rejection
- 외부 `close outside the box`, `return inside the box`
  - 지금도 `reaction_classification`, `reaction_acceptance_score`, `reaction_rejection_score`, `reaction_input`으로 해석 가능하다.
  - `outside close` 자체는 독립 승인 근거가 아니라 반응 증거 후보이므로, 먼저 기존 reaction contract를 유지한다.

### 2.3 위치 / 내러티브
- 외부 `session box high/low sweep`
  - 지금도 `strategy_scorecard.buckets.location`, `strategy_family_reason`, `thesis_fingerprint.liquidity_narrative`에서 상당 부분 설명 가능하다.
  - 세션 박스는 HTF 위치를 대체하지 않고 `intraday location refinement`로만 읽는다.

### 2.4 실행 규율
- 외부 `mechanical execution`
  - runtime top-level field보다는 `playbook`, `operations checklist`, `approval discipline` 성격이 더 강하다.
  - 이번 라운드에서는 새 payload field보다 운영 문서/체크리스트 해석으로 유지하는 편이 맞다.

## 3. 낮은 리스크 additive 후보
### 후보 A. `session_liquidity_reference`
목적:
- 세션 박스 high/low와 현재 박스 밖/안 상태를 operator가 직관적으로 읽게 한다.

권장 필드:
- `session_liquidity_reference.reference_type`
- `session_liquidity_reference.range_start_ts`
- `session_liquidity_reference.range_end_ts`
- `session_liquidity_reference.range_high`
- `session_liquidity_reference.range_low`
- `session_liquidity_reference.breakout_side`
- `session_liquidity_reference.outside_close_state`
- `session_liquidity_reference.failed_acceptance`
- `session_liquidity_reference.as_of_ts`

권장 저장 위치:
- `plan.validity.session_liquidity_reference`
- `scanner.top[*].session_liquidity_reference`
- `portfolio.accepted_candidates[*].session_liquidity_reference`

우선순위:
- `medium`

이유:
- 현재 `session_guidance`는 거래 가능 시간/penalty 해석 중심이다.
- 세션 박스 자체를 설명하려면 additive summary object가 더 읽기 쉽다.
- 다만 ranking, approval hard gate, sizing에는 연결하지 않는다.

### 후보 B. `outside_close_evidence`
목적:
- `box 밖에서 마감`과 `다시 박스 안으로 복귀`를 reaction contract와 정렬된 alias로 기록한다.

권장 필드:
- `outside_close_evidence.state`
- `outside_close_evidence.close_count`
- `outside_close_evidence.reentry_detected`
- `outside_close_evidence.interpretation`
- `outside_close_evidence.compare_only`

권장 저장 위치:
- `plan.validity.outside_close_evidence`
- `execution_approval.context_snapshot.outside_close_evidence`

우선순위:
- `low`

이유:
- 실제 source-of-truth는 계속 `reaction_classification`과 `reaction_input`이다.
- 이 필드는 세션 박스 표현을 operator가 읽기 쉽게 하는 summary alias에 가깝다.

### 후보 C. `location_reference`
목적:
- 세션 박스가 HTF 위치를 대체하지 않는다는 점을 payload에서도 더 직접 보이게 한다.

권장 필드:
- `location_reference.primary_type`
- `location_reference.primary_label`
- `location_reference.secondary_type`
- `location_reference.session_box_role`
- `location_reference.edge_proximity_atr`

권장 저장 위치:
- `plan.validity.location_reference`
- `scanner.top[*].location_reference`

우선순위:
- `medium`

이유:
- 이미 첫 번째 공통 흡수 작업에서 `location_reference`는 낮은 리스크 후보로 정리됐다.
- 세션 박스 라운드에서는 여기에 `session_box_role = reference_only | refinement_only` 정도만 얹는 편이 가장 안전하다.

## 4. 지금은 보류 또는 배제할 후보
### 보류
1. `session box breakout`을 rank/approval hard gate로 올리는 규칙
2. `premarket box breakout` 전용 family
3. `outside close`를 단독 live trigger로 승격하는 규칙
4. `1m confirmation`을 세션 박스 전략의 필수 hard gate로 두는 규칙

보류 이유:
- 현재 표본이 얇고 execution advisory가 `manual_review` 상태라, readability 이상의 승격 근거가 없다.
- 세션 박스는 보조 reference이지 primary strategy contract가 아니다.

### 배제
1. `EMA 20/50/200 stack`
2. `RSI`
3. `Elliott wave`
4. `trendline retest`
5. `Fib dip buy`
6. `Fib 1.272 target`
7. `high win-rate / low-RR` contract

배제 이유:
- 패턴/지표 자체가 source-of-truth가 되기 쉽고, 현재 전략의 `Location / Liquidity / Reaction / EV` 우선순위와 충돌한다.
- 비용/슬리피지 취약성이 큰 `small-win` 모델을 runtime semantics로 올리면 현재 execution 상태와 특히 맞지 않는다.

## 5. 권장 진행 순서
1. 먼저 `session_liquidity_reference`와 `location_reference`처럼 설명용 additive 후보만 compare-only로 검토한다.
2. `outside_close_evidence`는 `reaction_classification`과 중복되지 않는 범위에서만 제한적으로 검토한다.
3. 어떤 후보도 rank, approval, sizing semantics를 바꾸지 않는다.
4. validation에서 `EV / p5 / max drawdown / execution degradation` 개선이 없으면 승격하지 않는다.

## 6. 현재 결론
- 세션 박스 개념은 대부분 `session_guidance + reaction + location + liquidity_narrative` 조합으로 이미 해석 가능하다.
- 새 runtime 후보가 필요하더라도 `compare-only additive summary object` 수준에 머물러야 한다.
- `session box breakout`이나 `outside close`를 primary contract로 승격하는 방향은 현재 전략과 맞지 않는다.
