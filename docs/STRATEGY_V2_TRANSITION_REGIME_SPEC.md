# Strategy v2 Transition Regime Spec

최종 갱신: 2026-03-07
상태: Specification frozen

## 1. 목적
- `trend`, `range`, `shock` 어디에도 깨끗하게 속하지 않는 혼탁 구간을 `transition`으로 분리한다.
- 가장 손실이 많이 나는 억지 거래 구간을 명시적으로 차단한다.

## 2. 입력 필드
필수 입력:
1. 최근 `n=12`개 5m bar
2. 최근 `n=6`개 15m bar
3. `ATR(5m)`, `ATR(15m)`
4. jump rate
5. friction
6. 방향성 지표(`v`, `f`, `sdir`)
7. sweep count
8. wick/body ratio
9. FVG/OB hold failure count

## 3. Transition Features
각 feature는 `0/1` 또는 점수형으로 계산한다.

### F1. Opposing impulse conflict
- 최근 12개 5m 바 안에서 `|net_move| < 0.6 x sum(abs(bar_returns))`
- 그리고 반대 방향 impulse가 각각 `>= 1.0 ATR(5m)` 2회 이상

### F2. Bidirectional sweep churn
- 최근 12개 5m 바 안에서 상하 sweep이 모두 발생
- sweep interval이 `<= 6 bars`

### F3. Reaction failure cluster
- 최근 6개 이벤트에서 `reclaim failure` 또는 `acceptance/rejection mixed`가 3회 이상

### F4. Wick dominance
- 최근 6개 5m 바 평균 `wick_to_body_ratio >= 2.2`

### F5. State disagreement
- 15m directional bias와 5m event bias가 최근 3회 이상 충돌

### F6. Zone invalidation churn
- 최근 12개 5m 바에서 fresh FVG/OB 2개 이상이 바로 무력화

## 4. Transition Score
`transition_score = 20*F1 + 18*F2 + 18*F3 + 14*F4 + 15*F5 + 15*F6`

판정:
- `>= 55`: `transition_confirmed`
- `40~54`: `transition_watch`
- `< 40`: transition 아님

## 5. Hard Override
다음이면 점수와 관계없이 `transition_confirmed`:
1. 양방향 sweep + mixed 판정 2회 연속
2. recent 3 setup 중 2개가 `information_failure`
3. 15m bias와 5m execution bias가 3회 연속 반대로 종료

## 6. Lock Rules
`transition_confirmed`면:
1. `LIMIT` 금지
2. `Trend Continuation Pullback` 금지
3. `Range Rotation` 금지
4. 예외는 `A급 Sweep Reversal + confirm only`
5. size factor `0.00`
6. unlock 전까지 scanner에 `no_trade_reason=transition_lock`

`transition_watch`면:
1. `A-only` 외 전략 금지
2. `confirm only`
3. size factor `0.00`
4. 현재 구현은 watchlist visibility는 허용하지만 `recommended_risk_r`는 `0.00`으로 고정

## 7. Unlock Rules
아래 3개를 모두 만족하면 lock 해제:
1. `transition_score < 40`가 3개 bar 연속
2. `mixed` 분류가 최근 4개 이벤트에서 1회 이하
3. wick/body ratio가 `1.5` 미만으로 정상화

## 8. 로그 필드
저장 권장:
1. `transition_score`
2. `transition_state`
3. `transition_features`
4. `transition_unlock_candidate`
5. `transition_lock_reason`

## 9. 구현 메모
1. bar close 기준으로만 transition 재평가
2. same-bar lock/unlock 반복 금지
3. unlock 후 첫 2개 setup은 `confirm only`
