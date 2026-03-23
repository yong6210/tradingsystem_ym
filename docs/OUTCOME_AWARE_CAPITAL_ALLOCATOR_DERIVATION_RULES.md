# Outcome-Aware Capital Allocator Derivation Rules

최종 갱신: 2026-03-23
상태: Item 2 baseline fixed

## 1. 목적
- `family / regime / session` outcome evidence를 portfolio-only capital allowance로 번역해서, 같은 입력이면 항상 같은 `capital_allocator` 결과가 나오게 한다.
- 이번 규칙은 `recommended_risk_r`를 대체하지 않고, 그 위에 붙는 `allocated_risk_r` layer만 정의한다.
- approval / rollout policy / scanner ranking은 직접 바꾸지 않는다.

## 2. 입력 우선순위
1. 1순위: family outcome / execution / mode
- `score_to_outcome_funnel.decomposition.family`
- `family_execution_degradation_advisory_summary.families`
- `mode_advisory_summary.family`

2. 2순위: regime / session modifier
- `score_to_outcome_funnel.decomposition.regime`
- `score_to_outcome_funnel.decomposition.session`
- `mode_advisory_summary.regime`
- `mode_advisory_summary.session`

3. 3순위: current capital pressure
- accepted candidate rows
- current positions
- family별 currently allocated risk

즉 allocator는 `family 먼저`, `regime/session 나중`, `current pressure 마지막` 순서로 해석한다.

## 3. 기본 수치 규칙
### 3.1 maturity 기준
family maturity는 다음처럼 고정한다.

1. `thin_sample`
- `family closed < 4`

2. `usable`
- `family closed >= 4`
  그리고 `< 10`

3. `mature`
- `family closed >= 10`

thin sample이면 allocator tier는 `neutral`만 허용한다.

### 3.2 family outcome state
1. `positive`
- family funnel mature
- `baseline_cost_profitable_rate_from_closed >= 0.5`
- family execution status가 `watch/manual_review`가 아님
- family mode advisory가 `research_only/watch`가 아님

2. `negative`
- family execution status가 `manual_review`
- 또는 mature family rate `<= 0.3`
- 또는 family mode advisory가 `research_only/watch`이고 thin sample이 아님

3. `mixed`
- thin sample이 아니고 positive/negative 어느 쪽도 아님

4. `unavailable`
- family row가 없거나 sample insufficient

### 3.3 regime/session modifier state
regime/session은 아래처럼만 본다.

1. `positive`
- closed >= 4
- rate >= 0.5
- mode advisory negative 아님

2. `negative`
- closed >= 4
- rate <= 0.3
- 또는 mode advisory가 `watch/research_only`이고 thin sample이 아님

3. `neutral`
- 위 조건에 걸리지 않음

4. `unavailable`
- decomposition unavailable

## 4. allocator tier 규칙
### 4.1 thin-sample 보호
family maturity가 `thin_sample`이면:
- `tier = neutral`
- `allocation_weight = 1.0`
- `risk_multiplier = 1.0`
- reason code에 `sample:thin_family_closed`

### 4.2 family 우선 tier
1. family `positive`
- 기본 tier = `boost`
- base allocation weight = `1.15`

2. family `negative`
- 기본 tier = `reduce`
- base allocation weight = `0.7`

3. family `mixed|unavailable`
- 기본 tier = `neutral`
- base allocation weight = `1.0`

## 5. regime/session modifier 규칙
modifier는 family tier를 뒤집지 않고 미세 조정만 한다.

### 5.1 positive family일 때
- regime positive: `+0.05`
- session positive: `+0.05`
- regime negative: `-0.05`
- session negative: `-0.05`

### 5.2 neutral family일 때
- regime positive: `+0.05`
- session positive: `+0.05`
- regime negative: `-0.05`
- session negative: `-0.05`

### 5.3 negative family일 때
- regime/session positive로 family negative를 뒤집지 않는다
- negative tier는 유지
- 단, positive modifier가 있어도 감산 폭만 완화 가능
  - 각각 `+0.025`

### 5.4 clamp
- 최종 `allocation_weight`는 `[0.6, 1.2]`로 제한한다.

## 6. capital pressure 규칙
allocator는 current capital pressure를 읽어 headline을 만든다.

### 6.1 family allocated risk 집계
- accepted candidates + current positions 기준으로 family별 `allocated risk`를 합산한다.

### 6.2 pressure state
1. `underallocated_positive`
- family tier = `boost`
- 현재 family allocated risk가 전체 active risk의 `20%` 미만

2. `overallocated_negative`
- family tier = `reduce`
- 현재 family allocated risk가 전체 active risk의 `40%` 초과

3. `neutral`
- 나머지

capital pressure는 headline/summary용이며 hard cap은 아니다.

## 7. risk_multiplier 규칙
allocator는 `recommended_risk_r` 위에만 곱한다.

### 7.1 기본 매핑
- `allocation_weight >= 1.1` -> `risk_multiplier = 1.1`
- `1.0 <= allocation_weight < 1.1` -> `risk_multiplier = 1.0`
- `0.8 <= allocation_weight < 1.0` -> `risk_multiplier = 0.9`
- `allocation_weight < 0.8` -> `risk_multiplier = 0.75`

### 7.2 thin-sample 보호
- `thin_sample`이면 무조건 `risk_multiplier = 1.0`

### 7.3 hard guardrail
- `risk_multiplier`는 기존 hard block 또는 sizing zero를 우회하지 못한다.

## 8. allocated_risk_r 규칙
- `allocated_risk_r = recommended_risk_r * risk_multiplier`
- 소수점 넷째 자리 반올림
- `recommended_risk_r <= 0`이면 `allocated_risk_r = recommended_risk_r`
- allocator가 unavailable이면 `allocated_risk_r = recommended_risk_r`

즉 allocator는 portfolio final allowance를 바꾸되, sizing 엔진의 base recommendation을 다시 쓰지 않는다.

## 9. summary wording 규칙
### 9.1 boost
- `family post-cost outcome is stable and execution quality is healthy; modestly increase capital allowance`

### 9.2 reduce
- `family execution quality or post-cost outcome is weak; reduce capital allowance before allocating scarce slots`

### 9.3 neutral
- `allocator evidence does not justify a capital tilt for this candidate`

### 9.4 capital pressure suffix
- `underallocated_positive`
  - `; positive family is still underallocated relative to current active risk`
- `overallocated_negative`
  - `; negative family already consumes too much active risk`

## 10. reason code 규칙
허용 prefix:
- `family_outcome:`
- `family_execution:`
- `family_mode:`
- `regime_modifier:`
- `session_modifier:`
- `capital_pressure:`
- `sample:`

예시:
- `family_outcome:positive`
- `family_execution:manual_review`
- `family_mode:research_only`
- `regime_modifier:negative`
- `capital_pressure:underallocated_positive`

## 11. aggregate summary 규칙
aggregate allocator summary는 아래를 포함한다.

1. `allocator_state`
- `active`
  - family 중 하나라도 `boost/reduce`
- `neutral`
  - 전부 neutral

2. `family_focus`
- 절대 변화량이 가장 큰 family
- tie면 allocated risk가 더 큰 family

3. `family_weights`
- family별 `allocation_weight`, `tier`
- top 3만 노출

4. `capital_pressure`
- top family 기준 pressure state

## 12. guardrails
이번 derivation rule에서 하지 않는 것:
1. allocator만으로 block reason 생성
2. scanner ranking 재정의
3. rollout recommendation을 allocator로 자동 변환
4. positive family라고 해도 thin sample에서 boost 부여
5. regime/session이 family verdict를 뒤집도록 허용
