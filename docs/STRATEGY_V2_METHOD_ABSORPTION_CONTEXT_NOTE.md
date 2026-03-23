# Strategy v2 Method Absorption Context Note

최종 갱신: 2026-03-23
상태: Item 1 baseline fixed

## 1. 왜 이 작업을 하는가
- 외부 트레이딩 방법론은 설명 언어와 실행 습관 측면에서 배울 점이 있지만, 그대로 가져오면 현재 전략의 정량 구조가 무너질 수 있다.
- 따라서 `우리 전략과 합치되는 구조적 원칙`만 추출하고, 나머지는 배제해야 한다.

## 2. 절대 규칙
1. 해석 우선순위는 계속 `상태 -> 위치 -> 유동성 -> 반응 -> 실행`이다.
2. `Location first`, `Liquidity first`, `Reaction over pattern`, `Execution zone is secondary` 원칙을 깨지 않는다.
3. `A_ONLY` 운영 기조와 `no-trade` 우선 철학을 유지한다.
4. `Range Rotation`은 계속 `research_only`다.
5. `OB-only`, `FVG-only`, `trendline-led`, `indicator stack-led` 해석은 금지한다.
6. `승률`보다 `EV / p5 / max drawdown / 운영 적합성`을 우선한다.
7. execution advisory가 `manual_review`인 동안 새 개념은 라이브 확대 근거가 아니다.

## 3. 채택 원칙 확정
1. HTF -> LTF 탑다운 순서는 유지한다. 단, 상위 시간대 위치가 먼저고 하위 시간대는 실행 확인 레이어다.
2. HTF extreme, prior day/session/week high-low, equal highs-lows, premium/discount 같은 `위치` 정보는 계속 1순위로 본다.
3. session box, opening range, premarket range 같은 시간대 박스는 `세션 유동성 reference`로만 사용한다.
4. sweep 이후 reclaim, displacement, outside-close, retest hold 같은 `반응 근거`는 흡수 대상이다.
5. 하위 시간대 종가 확정은 `acceptance/rejection evidence`로만 사용한다.
6. FVG/OB는 독립 알파가 아니라 `실행 존`으로만 사용한다.
7. 기계적 실행, 사전 invalidation 정의, 감정 배제는 운영 규율로 유지한다.

## 4. 배제 원칙 확정
1. BOS/CHoCH/FVG 자체를 독립 진입 신호로 쓰지 않는다.
2. EMA/RSI/엘리어트/추세선/피보나치 stacked confluence는 흡수 대상이 아니다.
3. `1m breakout only`, `box breakout only`, `close outside range only`는 독립 전략으로 채택하지 않는다.
4. `최소 1:4 고정`, `0.2R 고승률` 같은 고정 손익 구조는 채택하지 않는다.
5. 짧은 기간 백테스트나 과장된 승률 수치는 채택 근거가 아니다.
6. trade count를 늘리는 방향의 룰은 execution quality가 안정되기 전까지 추가하지 않는다.

## 5. 현재 참고 기준
- `docs/STRATEGY_V2_BLUEPRINT.md`
- `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md`
- `docs/STRATEGY_V2_ACCEPTANCE_REJECTION_SPEC.md`
- `docs/STRATEGY_OPERATING_MANUAL.md`
- `reports/validation/BTCUSDC_v2_20260310T163616Z.md`
