# Strategy v2 Session Box Absorption Context Note

최종 갱신: 2026-03-23
상태: Baseline rules verified after final review

## 1. 왜 이 작업을 하는가
- 세션 박스 전략은 `세션 유동성`, `돌파 후 확인`, `기계적 실행` 측면에서는 배울 점이 있다.
- 하지만 현재 실행 품질 상태에서 `1m 저RR 고승률` 구조를 그대로 가져오면 전략 전체가 더 취약해질 수 있다.

## 2. 현재 전제
1. 최신 validation에서는 `execution degradation advisory = manual_review` 상태다.
2. `fill_rate_subscale`, `slippage_p95_drift`, `post_cost_ev_deterioration`가 이미 관측됐다.
3. 따라서 작은 R을 자주 먹는 1m breakout 전략은 현재 엔진/실행 품질과 잘 맞지 않는다.

## 3. 절대 규칙
1. 해석 우선순위는 계속 `상태 -> 위치 -> 유동성 -> 반응 -> 실행`이다.
2. `session box`는 독립 전략이 아니라 `세션 유동성 reference`로만 사용한다.
3. `breakout close`는 독립 엔트리가 아니라 `acceptance/rejection evidence`로만 사용한다.
4. execution source-of-truth는 계속 `reaction_classification`, `strategy_family`, `strategy_grade`, `recommended_risk_r`다.
5. `EMA/RSI/엘리어트/추세선/피보`는 흡수 대상이 아니다.
6. `승률`보다 `EV / p5 / max drawdown / execution degradation`을 우선한다.
7. `0.2R~0.25R` 저RR 구조는 채택하지 않는다.

## 4. 채택 원칙 확정
1. 세션 박스 high/low를 `세션 유동성 레벨`로 본다.
2. 돌파 종가 확인을 `acceptance/rejection evidence`로 번역한다.
3. 기계적 실행과 규율은 운영 원칙으로 유지한다.
4. 세션 박스는 `location refinement` 또는 `session liquidity reference` 수준으로만 사용한다.
5. 세션 박스 돌파는 반드시 상위 위치/유동성 narrative 아래에서만 해석한다.

## 5. 배제 원칙 확정
1. EMA/RSI/엘리어트/추세선 묶음
2. 고승률이면 된다는 사고
3. 1분 저RR 고승률 모델
4. 피보 타깃 기반 고정 청산 구조
5. `1m breakout-only`
6. `session box breakout-only`
7. 작은 이익을 자주 먹는 구조를 메인 성과 모델로 삼는 것

## 6. 참고 기준
- `docs/STRATEGY_V2_BLUEPRINT.md`
- `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md`
- `docs/STRATEGY_OPERATING_MANUAL.md`
- `reports/validation/BTCUSDC_v2_20260310T163616Z.md`
