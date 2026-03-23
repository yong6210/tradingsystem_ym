# Outcome-First Engine Upgrade Context Note

최종 갱신: 2026-03-23
상태: All checklist items completed

## 1. 왜 이 작업을 하는가
- 현재 시스템은 `좋은 후보를 선별하고 운영 리스크를 통제하는 구조`는 강하다.
- 하지만 실제 수익 연결 측면에서는 `결과를 보고 경고하는 수준`에서 더 나아가, `결과가 승인과 배분을 바꾸는 수준`까지 가야 한다.
- 이번 작업의 목적은 새 전략을 넣는 것이 아니라, 이미 구현된 outcome / degradation / promotion 정보를 control loop로 승격하는 것이다.

## 2. 절대 규칙
1. `state -> location -> liquidity -> reaction -> execution` 해석 순서는 그대로 유지한다.
2. `validation`과 `operations checklist`는 계속 최종 승인 surface다.
3. `reaction_classification`, `reaction_input`, `strategy_family`, `strategy_grade`, `recommended_risk_r`의 source-of-truth 역할을 무너뜨리지 않는다.
4. 새 control은 additive penalty / allowance layer여야 한다.
5. sample이 얇은 bucket에는 과도한 자동 패널티를 걸지 않는다.
6. execution degradation과 outcome penalty는 operator가 읽을 수 있게 이유가 남아야 한다.
7. `manual_review`는 여전히 rollout expansion 금지 신호로 취급한다.

## 3. 현재 코드 기준 인식
이미 있는 것:
1. `score_to_outcome_funnel`
2. `execution_degradation_advisory`
3. `family_execution_degradation_advisory`
4. `mode_advisory`
5. `alpha_research_promotion_watchlist`

아직 약한 것:
1. approval confidence에 대한 직접 penalty
2. sizing ceiling에 대한 direct penalty
3. portfolio overlay의 outcome-weighted allocation
4. validation / operator surface에서 penalty chain 설명

## 3A. Item 1 계약 결론
1. approval penalty는 새 hard block이 아니라 `base auto-approval downgrade layer`다.
2. `deployment_go_no_go`는 그대로 두고 `approval_state / playbook / approval_reasons`만 조정한다.
3. `manual_review` tier만 auto-approval을 `APPROVED_MANUAL`로 낮춘다.
4. `watch` tier는 이번 라운드에서는 reason-only로 유지한다.
5. trace는 `ExecutionApproval`과 approval snapshot에만 먼저 붙인다.

## 3B. Item 2 계약 결론
1. sizing penalty는 `position_sizing` 원본 factor를 바꾸지 않고 뒤에 붙는 `risk allowance clamp`다.
2. `manual_review`는 `hard_clamp(0.5x)`, `watch`는 `soft_clamp(0.75x)`를 기본 tier로 둔다.
3. thin sample bucket에는 penalty를 적용하지 않는다.
4. trace는 `strategy_sizing.outcome_risk_adjustment`에 남기고, `recommended_risk_r`는 penalty 반영 후 값으로 내려간다.
5. `recommended_risk_r = 0` 강제는 기존 hard block / mode shadow-only만 허용한다.

## 3C. Item 3 계약 결론
1. portfolio overlay outcome logic은 새 hard gate가 아니라 `ordering bias`다.
2. family 축을 최우선으로 보고, regime / session은 보조 bias로만 사용한다.
3. outcome bias는 `[-3.0, +3.0]` score delta 범위 안에서만 작동한다.
4. hard block 통과 여부는 그대로 유지하고, accepted ordering만 outcome-aware로 조정한다.
5. scanner가 아니라 portfolio layer에만 먼저 붙인다.

## 3D. Item 4 계약 결론
1. penalty trace는 새 source-of-truth가 아니라 `설명 객체`다.
2. 같은 penalty chain을 validation report / checklist / dashboard에서 같은 언어로 보여준다.
3. checklist는 `operator action`, validation은 `approval summary`, dashboard는 `aggregate + drill-down` 역할로 분리한다.
4. decomposition 전체를 다시 노출하지 않고, 압축된 summary만 올린다.

## 3E. Item 5 구현 결론
1. approval bundle은 symbol 기준 outcome/degradation summary를 계산해 approval service로 넘긴다.
2. approval service는 `outcome_approval_penalty`를 계산하고 approval snapshot에 저장한다.
3. `downgrade_to_manual` tier만 `APPROVED_AUTO -> APPROVED_MANUAL`을 적용한다.
4. `reason_only` tier는 state를 유지하고 `approval_reasons`에만 추가된다.
5. hard block과 rollout block semantics는 그대로 유지된다.

## 3F. Item 6 구현 결론
1. sizing penalty 입력은 `StrategyEngine`에서 symbol별로 계산해 runtime overlay에 주입한다.
2. `strategy_sizing.base_final_risk_r`, `strategy_sizing.outcome_risk_adjustment`, `recommended_risk_r`가 runtime row에서 함께 갱신된다.
3. 적용 surface는 `scanner`, `portfolio budget`, `execution candidate` 경로다.
4. thin sample 보호 규칙은 유지되고, `recommended_risk_r = 0` 강제는 추가하지 않았다.
5. persisted `plan.validity`는 이번 단계에서 바꾸지 않고 runtime row만 clamp한다.

## 3G. Item 7 구현 결론
1. portfolio outcome bias는 `hard gate`가 아니라 `final ordering bias`로만 적용된다.
2. 적용 surface는 `portfolio budget` candidate rows이며, scanner ranking은 그대로 둔다.
3. `outcome_bias_score`, `outcome_bias`, `pre_outcome_final_rank_score`, `post_outcome_final_rank_score`를 portfolio row에 남긴다.
4. family는 `±2.5`, regime / session은 `±0.5` 보조 bias를 주고, 전체 delta는 `[-3.0, +3.0]`으로 clamp한다.
5. thin sample bucket과 unavailable decomposition은 neutral 처리한다.

## 3H. Item 8 구현 결론
1. validation report는 `outcome_control_trace_summary`를 새 top-level summary로 가진다.
2. operational checklist는 `outcome_control_trace` item으로 approval / sizing / portfolio penalty chain을 운영 언어로 보여준다.
3. operator dashboard는 `signal_funnel.outcome_control_trace` aggregate와 `portfolio_summary` candidate drill-down을 함께 노출한다.
4. dashboard recent intent row는 `outcome_approval_penalty`를 포함해 approval downgrade 이유를 직접 보여준다.
5. trace는 설명 객체로만 추가됐고, 기존 source-of-truth는 그대로 유지된다.

## 3I. Item 9 구현 결론
1. outcome-first control loop 관련 핵심 경로를 묶은 회귀 세트를 통과했다.
2. README는 approval penalty, risk allowance clamp, portfolio ordering bias, `outcome_control_trace`를 현재 runtime surface 기준으로 동기화했다.
3. 문서 설명은 source-of-truth를 바꾸지 않고 `설명 계층`과 `operator surface` 중심으로만 확장했다.
4. 이번 라운드 테스트 범위는 approval, sizing, portfolio overlay, validation report, checklist, operator dashboard, API smoke까지 포함한다.

## 3J. Item 10 self-check 결론
1. 새 control은 approval / sizing / portfolio / validation / operator surface에만 additive로 붙었고, hard block semantics는 유지됐다.
2. `reaction_classification`, `reaction_input`, `strategy_family`, `recommended_risk_r`의 source-of-truth 역할은 유지됐다.
3. `outcome_control_trace`, `outcome_approval_penalty`, `outcome_risk_adjustment`, `outcome_bias`는 모두 설명 또는 allowance layer로만 동작한다.
4. approval, sizing, ordering, validation, checklist, dashboard, API smoke를 묶은 회귀가 통과했고 추가 수정은 필요하지 않았다.

## 4. 우선 개선 대상
1. approval에 outcome/degradation penalty 연결
2. sizing에 family/regime/session outcome penalty 연결
3. portfolio overlay에 outcome bias 연결
4. validation / dashboard에 penalty trace 노출

## 5. 배제 대상
1. family 자체를 outcome 하나로 강제 on/off하는 하드 킬스위치 남발
2. 표본이 적은 상태에서 aggressive auto-promotion
3. execution degradation만으로 무조건 전면 차단하는 과도한 hard gate
4. 외부 방법론 용어를 새 source-of-truth로 승격

## 6. 참고 기준
- `/Users/yumin/Documents/trading/app/services/score_to_outcome_funnel.py`
- `/Users/yumin/Documents/trading/app/services/execution_degradation_advisory.py`
- `/Users/yumin/Documents/trading/app/services/family_execution_degradation_advisory.py`
- `/Users/yumin/Documents/trading/app/services/mode_advisory.py`
- `/Users/yumin/Documents/trading/app/services/portfolio_risk_overlay.py`
- `/Users/yumin/Documents/trading/README.md`
