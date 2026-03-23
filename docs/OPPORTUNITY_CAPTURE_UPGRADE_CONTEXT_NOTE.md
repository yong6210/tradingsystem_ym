# Opportunity Capture Upgrade Context Note

최종 갱신: 2026-03-23
상태: Final review completed

## 1. 왜 이 작업을 하는가
- 현재 엔진은 outcome-first control까지는 강하다.
- 하지만 여전히 `quality가 좋아 보이는 신호` 중심으로 읽히기 쉽고, `기회를 얼마나 놓치고 있는가`는 operator가 빠르게 읽기 어렵다.
- 이번 라운드 목적은 `좋은 신호만 고르는 시스템`에서 `기회 부족까지 계량해서 보는 시스템`으로 한 단계 더 올리는 것이다.

## 2. 절대 규칙
1. approval / sizing / rollout policy source-of-truth는 그대로 유지한다.
2. opportunity capture는 처음에는 compare-only / advisory-only summary로만 추가한다.
3. thin sample / low activity 구간을 무리하게 negative throughput으로 해석하지 않는다.
4. family 우선, regime/session은 보조 근거로만 쓴다.
5. `신호 부족`과 `품질 부족`을 같은 뜻처럼 섞지 않는다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `score_to_outcome_funnel`
2. `outcome_control_trace`
3. `rollout_recommendation`
4. `portfolio blocked_reason_counts`
5. `family/regime/session decomposition`

아직 약한 것:
1. trades/day 같은 throughput summary
2. accepted 대비 submitted, submitted 대비 filled의 기회 손실 요약
3. blocked mix가 `quality 문제인지`, `rollout 문제인지`, `risk cap 문제인지`를 한 줄로 읽는 summary

## 4. 적용 원칙
1. throughput은 `quality를 대체`하지 않고 보완한다.
2. `opportunity_capture`는 recommendation보다 먼저 `관측 레이어`로 추가한다.
3. 신호 희소성 때문에 과도하게 threshold를 바꾸는 자동화는 이번 라운드에서 금지한다.
4. family가 가장 먼저 읽히고 regime/session은 modifier로만 붙는다.

## 5. 참고 기준
- `/Users/yumin/Documents/trading/app/services/score_to_outcome_funnel.py`
- `/Users/yumin/Documents/trading/app/services/portfolio_budget_report.py`
- `/Users/yumin/Documents/trading/app/services/execution_operator_dashboard.py`
- `/Users/yumin/Documents/trading/app/services/validation_report.py`
- `/Users/yumin/Documents/trading/docs/OUTCOME_FIRST_ENGINE_UPGRADE_CONTEXT_NOTE.md`
- `/Users/yumin/Documents/trading/docs/OUTCOME_FIRST_ROLLOUT_RECOMMENDATION_CONTEXT_NOTE.md`

## 6. Item 1 계약 결론
1. opportunity capture는 `score_to_outcome_funnel`을 중심으로 만들고, runtime blocked mix와 execution quality는 보조 근거로만 사용한다.
2. 출력 surface는 validation / checklist / dashboard로 제한하고 approval, scanner, portfolio candidate row는 비노출로 둔다.
3. headline은 family 기준 throughput/capture gap으로 잡고 regime/session은 modifier로만 사용한다.
4. 이번 라운드에서 opportunity capture는 recommendation이 아니라 explanatory summary로만 유지한다.

## 7. Item 2 규칙 결론
1. `trades_per_day`, `capture_rates`, `capture_gap`은 `score_to_outcome_funnel`의 snapshot/historical 필드만으로 계산한다.
2. `blocked_mix`는 기존 dashboard gate-group 분류와 같은 규칙으로 재사용한다.
3. `dominant_bottleneck`은 gap 최대 stage를 고르되, thin activity 구간은 과도한 negative 해석 대신 `thin_activity_window`를 우선한다.
4. `family_focus`는 candidate volume과 runtime-to-submit gap을 함께 보는 throughput focus score로 고르고, regime/session은 positive/negative modifier로만 붙인다.

## 8. Item 3 surface 결론
1. validation은 top-level summary와 markdown section으로 `throughput explanation`을 보여준다.
2. checklist는 `MANUAL/FAIL`이 아니라 `PASS/WARN` 중심 informational item으로 유지한다.
3. dashboard는 `signal_funnel.opportunity_capture` aggregate summary만 노출하고 candidate/intents row로 퍼뜨리지 않는다.
4. `outcome_control_trace`, `rollout_recommendation`, `opportunity_capture`는 각각 control / policy / throughput 역할로 분리한다.

## 9. Item 4 구현 결론
1. `app/services/opportunity_capture.py`에서 throughput summary를 생성하고, strategy engine이 validation/dashboard에 같은 object를 배선한다.
2. validation report는 `opportunity_capture_available`, `opportunity_capture_summary`, markdown section을 가진다.
3. operations checklist는 `Opportunity Capture` informational item을 추가해 selection bottleneck / fill shortage / thin activity를 읽게 한다.
4. operator dashboard는 `signal_funnel.opportunity_capture` aggregate summary만 노출한다.

## 10. Item 5 테스트 / 문서 결론
1. helper 단위 테스트와 validation/checklist/dashboard/API smoke 계약 테스트로 `opportunity_capture`를 고정했다.
2. README에 `Opportunity Capture` 섹션과 operator surface 설명을 추가해 현재 runtime 언어와 동기화했다.
3. 이번 라운드에서도 `opportunity_capture`는 compare-only throughput explanation이라는 경계를 유지한다.

## 11. Final Self-Check 결론
1. `opportunity_capture`는 validation/checklist/dashboard에만 노출되고 approval, sizing, rollout policy source-of-truth를 직접 바꾸지 않는다.
2. `outcome_control_trace`, `rollout_recommendation`, `opportunity_capture`의 역할은 각각 control / policy / throughput으로 분리된 상태를 유지한다.
3. helper 단위 테스트와 surface 계약 테스트가 모두 통과했으므로, 이번 라운드는 현재 상태로 닫는 것이 맞다.
