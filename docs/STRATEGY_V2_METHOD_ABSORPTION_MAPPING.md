# Strategy v2 Method Absorption Mapping

최종 갱신: 2026-03-23
상태: External method vocabulary mapped to strategy v2 language

## 1. 목적
- 외부 트레이딩 방법론의 용어를 현재 `strategy v2` 해석 체계로 번역한다.
- 외부 표현을 그대로 쓰지 않고, runtime/validation/operations에서 이미 쓰는 언어로 정렬한다.

## 2. 상위 구조 매핑
- 외부 표현: `Top-Down Analysis`
  - strategy v2 번역: `상태 -> 위치 -> 유동성 -> 반응 -> 실행`
- 외부 표현: `Daily / 4H trend`
  - strategy v2 번역: `Market State + HTF alignment + HTF extreme context`
- 외부 표현: `15m intraday structure`
  - strategy v2 번역: `location refinement + liquidity narrative`
- 외부 표현: `1m execution trigger`
  - strategy v2 번역: `execution confirmation layer`

## 3. 개념별 번역
### 3.1 Market Structure
- `HH/HL, LH/LL`
  - 직접 신호가 아니라 `state` 해석 근거다.
  - 우리 언어로는 `trend/range/shock/transition` 판정 보조 근거다.
- `BOS`
  - 독립 진입 신호가 아니다.
  - 우리 언어로는 `continuation evidence` 또는 `acceptance evidence`다.
- `CHoCH`
  - 독립 진입 신호가 아니다.
  - 우리 언어로는 `reclaim / rejection / early structure shift evidence`다.
  - 하위 시간대에서는 `confirm only` 성격의 실행 근거로만 본다.

### 3.2 Liquidity
- `liquidity pool`
  - 우리 언어로는 `HTF extreme`, `prior day/session/week high-low`, `equal highs-lows`다.
- `sweep`
  - 우리 언어로는 `event`.
  - `Sweep Reversal` family의 시작 조건이다.
- `unmitigated liquidity`
  - 우리 언어로는 `untested location / pending target reference`다.
  - `가격이 반드시 간다`가 아니라 `도달 시 반응을 볼 위치`로 해석한다.

### 3.3 FVG / OB / Zone
- `FVG`
  - 우리 언어로는 `execution zone` 또는 `inefficiency evidence`다.
  - 독립 알파가 아니라 `reaction 이후 어디서 실행할지`를 정하는 도구다.
- `Order Block`
  - 우리 언어로는 `execution zone` 또는 `protected level context`다.
  - `OB-only` 해석은 금지다.
- `mitigation`
  - 우리 언어로는 `retest / hold / reclaim follow-through` 확인이다.

### 3.4 Session / Range
- `opening range`, `premarket box`, `session high/low`
  - 우리 언어로는 `session liquidity reference`다.
  - 단독 breakout 전략이 아니라, session 기반 `location` 보조 정보다.
- `close outside the box`
  - 우리 언어로는 `acceptance evidence candidate`다.
  - 단독 trigger가 아니라 `location + liquidity narrative`가 먼저 있어야 한다.

### 3.5 Entry / Confirmation
- `touch HTF level -> 1m CHoCH -> FVG entry`
  - 우리 언어로는 `HTF location reached -> reaction evidence confirmed -> execution model selection`이다.
  - execution model은 `LIMIT`, `CONFIRM`, `SWEEP_CONFIRM` 중 하나로 번역한다.
- `trend alignment via EMA stack`
  - 우리 언어로는 직접 채택하지 않는다.
  - 필요한 정보는 `HTF trend clarity`, `impulse quality`, `protected level hold`로 흡수한다.

## 4. 전략군별 해석
### Sweep Reversal
- 외부 표현: `liquidity grab + CHoCH + FVG entry`
- strategy v2 번역:
  1. `HTF extreme / key liquidity level`
  2. `sweep`
  3. `reclaim + displacement + outside-close control`
  4. `rejection_confirmed` 또는 최소 `confirm_only`
  5. `execution zone(FVG/OB)`에서 `LIMIT` 또는 `SWEEP_CONFIRM`

### Trend Continuation Pullback
- 외부 표현: `BOS + pullback + FVG revisit`
- strategy v2 번역:
  1. `HTF trend clarity`
  2. `impulse quality`
  3. `healthy pullback`
  4. `protected high/low 유지`
  5. `fresh execution zone revisit`

### Range Rotation
- 외부 표현: `range edge reversal`
- strategy v2 번역:
  1. `range definition`
  2. `edge proximity`
  3. `liquidity grab`
  4. `reversal quality`
  5. 현재는 `research_only`

## 5. 운영상 번역 규칙
1. 외부 용어가 보여도 runtime source-of-truth는 계속 `reaction_classification`, `strategy_family`, `strategy_grade`, `recommended_risk_r`다.
2. `1m` 근거는 baseline live rule이 아니라 `execution refinement / compare-only` 성격으로 해석한다.
3. validation은 계속 `win rate`보다 `EV / p5 / max drawdown / execution degradation` 기준으로 읽는다.
4. 외부 고승률 주장은 표본/비용/실행 품질 검증 전에는 설계 근거가 아니다.

## 6. 한 줄 요약
- `BOS/CHoCH`는 `반응 증거`
- `FVG/OB`는 `실행 존`
- `session box`는 `세션 유동성 reference`
- `top-down`은 `상태 -> 위치 -> 유동성 -> 반응 -> 실행`
