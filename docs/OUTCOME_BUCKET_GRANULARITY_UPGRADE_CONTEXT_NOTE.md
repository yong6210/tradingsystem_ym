# Outcome Bucket Granularity Upgrade Context Note

최종 갱신: 2026-03-23
상태: Final review completed

## 1. 왜 이 작업을 하는가
- 현재 시스템은 family / regime / session까지는 잘 정리됐지만, 같은 family 안에서도 volatility, spread/fee, liquidity depth 차이로 결과가 크게 달라질 수 있다.
- 지금 필요한 건 새 strategy family를 늘리는 것이 아니라, 기존 family 성과를 더 정확히 분해하는 것이다.
- 이번 라운드 목적은 outcome-first 계층의 입력 품질을 높이는 것이지, authority를 또 늘리는 것이 아니다.

## 2. 절대 규칙
1. family는 계속 1차 축이고, 새 bucket은 supporting condition layer로만 쓴다.
2. 새 bucket은 approval / sizing / rollout authority를 직접 바꾸지 않는다.
3. thin sample bucket은 neutral / informational 해석을 우선한다.
4. volatility / cost / liquidity bucket은 서로 독립 signal이 아니라 decomposition axis다.
5. 이번 라운드는 `decomposition + summary` 중심이고, DB policy 자동 변경은 하지 않는다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `score_to_outcome_funnel` family / regime / session decomposition
2. `rollout_recommendation`
3. `strategy_lifecycle`
4. `capital_allocator`
5. `positive_evidence_expansion`

아직 약한 것:
1. volatility regime granularity
2. cost regime granularity
3. liquidity depth granularity
4. family 성과 차이를 더 미세하게 설명하는 modifier layer

## 4. 적용 원칙
1. 새 bucket은 기존 family headline을 대체하지 않는다.
2. validation / checklist / dashboard / README가 같은 condition language를 써야 한다.
3. condition bucket은 `explain`, `compare`, `segment` 역할만 하고 authority와 merge하지 않는다.

## 4A. Item 1 계약 결론
1. 새 axis는 `volatility_condition / cost_condition / liquidity_condition` 셋으로만 고정한다.
2. family는 계속 1차 축이고 새 axis는 supporting condition layer로만 사용한다.
3. 직접 반영 surface는 score-to-outcome decomposition, validation, checklist, dashboard, README만 허용한다.
4. approval / sizing / scanner / candidate row / rollout DB는 비범위로 둔다.
5. thin sample은 bucket 이름이 아니라 interpretation guardrail로만 처리한다.

## 4B. Item 2 derivation 결론
1. volatility는 `atr5/atr15` ratio를 primary로, `portfolio_volatility`를 fallback proxy로 사용한다.
2. cost는 runtime에서는 `expected_fee_bps + max_slippage_bps`, historical에서는 `baseline_cost_r`를 사용한다.
3. liquidity는 raw depth가 아니라 existing `liquidity proxy`를 사용하고, 없으면 `max_slippage_bps`를 secondary proxy로 쓴다.
4. 새 axis row는 기존 decomposition row schema를 그대로 재사용한다.
5. condition summary는 mature/usable bucket만으로 divergence를 계산하고 family headline을 뒤집지 않는다.

## 4C. Item 3 patch 결론
1. validation에는 `outcome_bucket_granularity_available`, `outcome_bucket_granularity_summary`, `## Outcome Bucket Granularity`를 추가한다.
2. checklist에는 blocking이 아닌 informational item `Outcome Bucket Granularity`만 추가한다.
3. dashboard에는 `signal_funnel.outcome_bucket_granularity` aggregate summary만 반영한다.
4. README에는 family-first 구조 위에 condition split을 설명하는 짧은 섹션만 추가한다.
5. approval / candidate row / rollout DB에는 반영하지 않는다.

## 4D. Item 4 구현 결론
1. `score_to_outcome_funnel` decomposition에 `volatility_condition / cost_condition / liquidity_condition` axis를 실제로 추가한다.
2. `OutcomeBucketGranularityService`는 decomposition payload를 읽는 compare-only summary layer로만 구현한다.
3. validation / checklist / dashboard는 같은 summary object를 재사용하고, candidate row나 approval surface로는 퍼뜨리지 않는다.
4. historical volatility와 runtime cost/liquidity proxy는 값이 없으면 `unknown`을 허용하고, summary headline은 mature/usable divergence가 있을 때만 만든다.

## 4E. Item 5 테스트/문서 결론
1. helper 단위 테스트로 top condition axis와 thin coverage fallback을 직접 고정한다.
2. validation / checklist / dashboard / API smoke에 `outcome_bucket_granularity` 키와 핵심 semantics를 추가한다.
3. README에는 family-first 위에 condition split을 얹는 compare-only layer라고 명시한다.
4. operator surface 설명에서도 `outcome_bucket_granularity_summary`를 기존 summary cluster와 같은 레벨로 정렬한다.

## 4F. Item 6 self-check 결론
1. `outcome_bucket_granularity`는 validation / checklist / dashboard / README에만 있고 approval / sizing / scanner / candidate row / rollout DB로는 번지지 않았다.
2. `family` headline은 그대로 유지되고, `volatility / cost / liquidity`는 supporting condition split으로만 남아 있다.
3. `liquidity_condition`도 raw depth가 아니라 liquidity proxy로 명시돼 false precision을 줄였다.
4. helper 단위 테스트와 surface 회귀가 모두 통과해서 현재 범위에서 추가 수정이 필요한 충돌은 보이지 않는다.

## 5. 참고 기준
- `/Users/yumin/Documents/trading/app/services/score_to_outcome_funnel.py`
- `/Users/yumin/Documents/trading/app/services/validation_report.py`
- `/Users/yumin/Documents/trading/app/services/execution_operator_dashboard.py`
- `/Users/yumin/Documents/trading/app/services/portfolio_risk_overlay.py`
- `/Users/yumin/Documents/trading/README.md`
- `/Users/yumin/Documents/trading/docs/OUTCOME_BUCKET_GRANULARITY_UPGRADE_CONTRACT.md`
- `/Users/yumin/Documents/trading/docs/OUTCOME_BUCKET_GRANULARITY_UPGRADE_DERIVATION_RULES.md`
- `/Users/yumin/Documents/trading/docs/OUTCOME_BUCKET_GRANULARITY_UPGRADE_PATCH_PLAN.md`
- `/Users/yumin/Documents/trading/app/services/outcome_bucket_granularity.py`
- `/Users/yumin/Documents/trading/app/services/score_to_outcome_funnel.py`
- `/Users/yumin/Documents/trading/app/services/validation_report.py`
- `/Users/yumin/Documents/trading/app/services/operational_checklist.py`
- `/Users/yumin/Documents/trading/app/services/execution_operator_dashboard.py`
- `/Users/yumin/Documents/trading/tests/test_outcome_bucket_granularity.py`
- `/Users/yumin/Documents/trading/tests/test_validation_report.py`
- `/Users/yumin/Documents/trading/tests/test_operational_checklist.py`
- `/Users/yumin/Documents/trading/tests/test_execution_operator_dashboard.py`
- `/Users/yumin/Documents/trading/tests/test_api_smoke.py`
