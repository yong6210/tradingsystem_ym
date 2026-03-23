# Strategy v2 Session Box Absorption Mapping

최종 갱신: 2026-03-23
상태: Session box vocabulary mapped to strategy v2 language

## 1. 목적
- 세션 박스 전략에서 재사용 가능한 표현만 현재 `strategy v2` 해석 체계로 번역한다.
- `세션 유동성`, `돌파 후 확인`, `규율`은 흡수하고, `지표 묶음`, `고승률 저RR` 구조는 배제한다.

## 2. 상위 구조 매핑
- 외부 표현: `8:00-9:30 premarket box / opening range`
  - strategy v2 번역: `session liquidity reference`
- 외부 표현: `price closes outside the box`
  - strategy v2 번역: `acceptance evidence candidate`
- 외부 표현: `price fails outside and returns inside the box`
  - strategy v2 번역: `rejection evidence candidate`
- 외부 표현: `1m execution chart`
  - strategy v2 번역: `execution confirmation layer`
- 외부 표현: `mechanical execution`
  - strategy v2 번역: `operator discipline / repeatable execution process`

## 3. 개념별 번역
### 3.1 Session Box
- `session box high / low`
  - 우리 언어로는 `session high/low liquidity` 또는 `intraday location refinement`다.
  - 독립 전략이 아니라 상위 위치 아래에서 보는 보조 레벨이다.
- `break of the box`
  - 우리 언어로는 `session liquidity event`다.
  - `box를 넘었다` 자체가 아니라 그 이후 `acceptance`인지 `rejection`인지가 중요하다.
- `close outside the box`
  - 우리 언어로는 `acceptance evidence candidate`다.
  - 단독 엔트리가 아니라 `위치 + 유동성 narrative`가 선행될 때만 의미가 있다.
- `return inside after outside close`
  - 우리 언어로는 `rejection / failed acceptance evidence`다.
  - sweep 이후 반전 해석의 보조 근거로 사용할 수 있다.

### 3.2 Trend / Filter Stack
- `EMA 20 / 50 / 200 alignment`
  - 직접 채택하지 않는다.
  - 필요한 정보는 `HTF state`, `trend clarity`, `impulse quality`, `protected level hold`로 번역한다.
- `RSI`
  - 흡수 대상이 아니다.
  - momentum 참고용 보조 지표도 현재 v2 source-of-truth가 아니다.
- `Elliott wave / trendline`
  - 흡수 대상이 아니다.
  - 패턴/그림 기반 설명은 runtime contract로 승격하지 않는다.

### 3.3 Entry / Execution
- `breakout -> retest -> entry`
  - 우리 언어로는 `session liquidity event -> acceptance/rejection evidence -> execution model selection`이다.
  - 실행은 여전히 `LIMIT`, `CONFIRM`, `SWEEP_CONFIRM` 안에서 해석한다.
- `dip buy 1 / dip buy 2`
  - 고정 피보 분할매수는 채택하지 않는다.
  - scaling이 필요하면 기존 `risk budget`과 `protected invalidation` 아래에서만 허용한다.
- `stop loss below fib / box`
  - 우리 언어로는 `protected level failure` 또는 `sweep thesis invalidation`이다.
  - 손절은 항상 thesis failure 기준이지, 도구 자체의 고정 레벨이 아니다.
- `take profit at fib 1.272`
  - 직접 채택하지 않는다.
  - 목표는 `next liquidity`, `opposing HTF location`, `cost-aware EV`로 판단한다.

### 3.4 Performance / Operating Logic
- `high win-rate strategy`
  - 우리 언어로는 설계 근거가 아니다.
  - validation은 계속 `EV / p5 / max drawdown / execution degradation`으로 읽는다.
- `0.2R ~ 0.25R wins`
  - 현재 전략 성과 모델과 맞지 않는다.
  - 비용/슬리피지 취약성이 커서 baseline 구조로 채택하지 않는다.
- `discipline matters more than perfect strategy`
  - 우리 언어로는 `operator checklist compliance`와 `repeatable execution`이다.
  - 이 원칙은 유지한다.

## 4. 전략군별 해석
### Sweep Reversal
- 외부 표현: `box high sweep -> outside close failure -> short`
- strategy v2 번역:
  1. `HTF extreme / known liquidity level`
  2. `session box high/low sweep`
  3. `failed acceptance or reclaim`
  4. `rejection_confirmed` 또는 최소 `confirm_only`
  5. `execution zone`에서 `LIMIT` 또는 `SWEEP_CONFIRM`

### Trend Continuation Pullback
- 외부 표현: `box breakout with trend alignment -> retest -> continuation`
- strategy v2 번역:
  1. `HTF trend clarity`
  2. `session box breakout as acceptance evidence`
  3. `protected level 유지`
  4. `healthy pullback`
  5. `execution confirmation`
- 단, `session box breakout-only`로는 해석하지 않는다.

### No Trade
- 외부 표현: `box break happened`
- strategy v2 번역:
  - `위치/유동성 narrative가 없으면 no-trade`
  - `confirm evidence가 빈약하면 no-trade`
  - `session box는 있었지만 edge가 없으면 no-trade`

## 5. 운영상 번역 규칙
1. `session box`는 `source-of-truth`가 아니라 `session liquidity reference`다.
2. `close outside the box`는 `approval`이 아니라 `reaction evidence candidate`다.
3. `EMA/RSI/엘리어트/추세선/피보`는 이번 라운드 흡수 대상이 아니다.
4. `high win-rate`나 짧은 표본 성과는 전략 채택 근거가 아니다.
5. 최종 판단은 계속 `reaction_classification`, `strategy_family`, `strategy_grade`, `recommended_risk_r`로 내린다.

## 6. 한 줄 요약
- `session box`는 `세션 유동성 reference`
- `outside close`는 `acceptance/rejection evidence candidate`
- `mechanical execution`은 `운영 규율`
- `indicator stack / 고승률 저RR`은 `비채택`
