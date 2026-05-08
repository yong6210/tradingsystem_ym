# Strategy V2 Regime Specialist Matrix

## 목적

이 문서는 `모든 상황을 하나의 만능 전략으로 처리하지 않는다`는 원칙을 고정한다.  
대신 시장 상태를 몇 개의 레짐으로 나누고, 각 레짐에 **전문 전략(family)** 을 하나씩 붙인다.

핵심 원칙은 네 가지다.

1. `A/B`는 저빈도 고정밀 anchor 구조로 유지한다.
2. 새로운 family는 한 번에 하나씩만 추가한다.
3. family마다 별도 scorecard를 운영한다.
4. 어떤 family도 같은 thesis에 대해 중복 포지션을 열지 않는다.

## 현재 확정 상태

### A. Sweep Reversal Anchor

- family: `sweep_reversal`
- 역할: baseline anchor
- 레짐: `transition`, `range`
- 상태: `live / research anchor`
- entry: `LIMIT only`

### B. Transition Rescue Overlay

- family: `transition_edge_overlay`
- 역할: `A`가 `low_confluence`로 버린 edge를 selective하게 복구
- 레짐: `transition`
- 상태: `shadow`
- entry: baseline과 동일, execution rewrite 없음

## 레짐별 전문 모델 체계

### 1. Trend

목표는 mean-reversion이 아니라 **구조 유지 + continuation** 이다.

후보:

- `trend_continuation_pullback`
- `liquidity_run_continuation`
- `volatility_expansion`

우선순위:

1. `liquidity_run_continuation`
2. `volatility_expansion`
3. `trend_continuation_pullback`

설명:

- 기존 repo-native `trend_continuation`은 BTC에서 `generated 0`으로 탈락했다.
- 따라서 trend family를 다시 열려면 `같은 이름`이 아니라 `다른 사건 정의`가 필요하다.
- 가장 유망한 건 `reversal`과 충돌하지 않는 continuation-side liquidity 해석이다.

### 2. Transition

전환장은 이미 가장 강한 family가 존재한다.

후보:

- `sweep_reversal`
- `transition_edge_overlay`
- `choch_displacement_reclaim`

우선순위:

1. `transition_edge_overlay` live 검증
2. `choch_displacement_reclaim` 연구

설명:

- 현재 가장 강한 edge는 transition에서 나온다.
- 다음 family는 `CHOCH라는 이름`이 아니라,
  `CHOCH + displacement + reclaim + protected structure` 처럼 사건을 정확히 잘라야 한다.

### 3. Range

목표는 구조적 회귀다.

후보:

- `sweep_reversal`
- `range_rotation`
- `failed_breakout_reclaim` (향후 세부 family로 분리 가능)

우선순위:

1. `range_rotation`

설명:

- 지금은 range가 sweep_reversal에 흡수돼 있다.
- 나중엔 `mature range`를 별도 family로 떼어내야 한다.

### 4. Session Open

목표는 시간 기반 burst를 포착하는 것이다.

후보:

- `orb_breakout`
- `session_auction_reclaim`

설명:

- 이 family는 빈도를 보완하는 역할을 할 수 있다.
- 단, session box / blackout / macro event 예외 처리가 먼저 필요하다.
- `session_auction_reclaim`는 단순 breakout이 아니라, opening drive 이후 `VWAP/OR` 재수용을 보고 continuation을 노리는 버전이다.

### 5. Volatility Expansion

목표는 squeeze 해소 직후의 초기 trend ignition을 포착하는 것이다.

후보:

- `volatility_expansion`

설명:

- A/B가 놓치는 `초기 추세 시동`을 담당한다.
- 가짜 breakout 방지 필터가 핵심이다.

### 6. Event Shock

목표는 이벤트 직후 생기는 짧은 directional imbalance를 trade하는 것이다.

후보:

- `event_shock_imbalance`

설명:

- 흥미롭지만 실행 friction과 슬리피지 모델이 없으면 바로 live로 가면 안 된다.

### 7. Dead Market

이건 전략이 아니라 **의도적인 no-trade 상태**다.

후보:

- `capital_preservation_no_trade`

설명:

- 아무 레짐도 edge를 갖고 있지 않으면 거래하지 않는 것이 정답이다.
- 이 상태는 항상 명시적으로 유지한다.

## 라우팅 원칙

핵심은 hard route가 아니라 **후보 우선순위**다.

### 잘못된 방식

`trend -> 무조건 trend_continuation`

### 맞는 방식

- `trend`에선 trend family를 먼저 평가
- `transition`에선 A/B family를 먼저 평가
- `range`에선 range family를 먼저 평가
- 단, 최종 선택은 quality / collision / risk policy로 결정

## 신규 family 추가 프로토콜

새 family는 항상 아래 순서로만 추가한다.

1. 사건 정의 고정
2. 레짐 정의 고정
3. thesis duplicate policy 정의
4. 365일 future-blind
5. `PASS / WATCH / REJECT`
6. shadow
7. partial
8. full selective rollout

## 하드 합격 기준

- `post-cost EV >= +0.20R`
- `closed >= 40 / 365d`
- 기존 family와 `corr <= 0.3`
- 수익이 특정 레짐에 명확히 집중
- downstream quality 붕괴 없음

## 다음 우선순위

현재 기준으로 연구 우선순위는 이렇다.

1. `B` live 검증 유지
2. `choch_displacement_reclaim`
3. `liquidity_run_continuation`
4. `orb_breakout`
5. `session_auction_reclaim`
6. `volatility_expansion`
7. `range_rotation`
8. `event_shock_imbalance`

## 한 줄 결론

모든 상황을 하나의 전략으로 먹지 않는다.  
대신 `레짐별 전문 모델`을 하나씩 검증해서, 합격한 family만 포트폴리오에 편입한다.
