# Outcome-Aware Capital Allocator Patch Plan

최종 갱신: 2026-03-23
상태: Item 3 baseline fixed

## 1. 목적
- `capital_allocator`를 portfolio allocation layer와 operator explanation layer에 일관되게 반영한다.
- `recommended_risk_r`와 `allocated_risk_r`를 분리해서, sizing source-of-truth와 allocation allowance를 구분한다.
- validation / checklist / dashboard / portfolio report가 같은 allocator 언어를 쓰도록 고정한다.

## 2. 반영 원칙
1. allocator는 portfolio layer 중심으로 배치한다.
2. scanner / approval / rollout DB에는 반영하지 않는다.
3. `outcome_bias`와 `capital_allocator`는 같이 존재할 수 있지만 역할을 merge하지 않는다.
4. `recommended_risk_r`는 sizing, `allocated_risk_r`는 portfolio allowance로 분리한다.

## 3. Portfolio Candidate Row 반영안
대상:
- `/Users/yumin/Documents/trading/app/services/portfolio_risk_overlay.py`
- `/Users/yumin/Documents/trading/app/schemas/api.py`

새 additive 필드:
- `capital_allocator`
- `allocation_weight`
- `allocated_risk_r`
- `capital_pressure`

기존 유지:
- `recommended_risk_r`
- `strategy_sizing`
- `outcome_bias`
- `pre_outcome_final_rank_score`
- `post_outcome_final_rank_score`

배치 원칙:
- `recommended_risk_r`는 그대로 남긴다.
- `allocated_risk_r`는 portfolio layer 계산 결과로만 추가한다.
- hard block logic은 `recommended_risk_r`와 기존 caps를 기준으로 유지한다.

## 4. Portfolio Budget Report 반영안
대상:
- `/Users/yumin/Documents/trading/app/services/portfolio_budget_report.py`

새 aggregate 필드:
- `capital_allocator_summary`

candidate row report 추가:
- `allocation_weight`
- `allocated_risk_r`
- `capital_allocator.tier`
- `capital_allocator.reason_codes`

문구 원칙:
- report는 allocator를 `scarce capital tilt`로 설명
- sizing penalty / outcome bias와 다른 계층이라는 문구 유지

## 5. Validation Report 반영안
대상:
- `/Users/yumin/Documents/trading/app/services/validation_report.py`

새 top-level summary:
- `capital_allocator_available`
- `capital_allocator_summary`

markdown 섹션:
- `## Capital Allocator`

포함 필드:
- `allocator_state`
- `family_focus`
- `capital_pressure`
- `family_weights`
- `summary`

비포함:
- candidate row 전량 복붙
- current positions raw dump

## 6. Operations Checklist 반영안
대상:
- `/Users/yumin/Documents/trading/app/services/operational_checklist.py`

선택:
- 새 item `capital_allocator`

상태 규칙:
1. unavailable
- `PASS`
- informational only

2. active allocator with `underallocated_positive`
- `PASS`
- informational; monitor allocation opportunity

3. active allocator with `overallocated_negative`
- `WARN`
- review capital concentration before adding more risk

guardrail:
- allocator item은 blocking item이 아니다

## 7. Operator Dashboard 반영안
대상:
- `/Users/yumin/Documents/trading/app/services/execution_operator_dashboard.py`

signal_funnel additive field:
- `capital_allocator`

portfolio summary candidate drill-down:
- candidate row에 `capital_allocator`, `allocated_risk_r` 포함

역할 분리:
- `outcome_control_trace` = control
- `rollout_recommendation` = policy
- `opportunity_capture` = throughput
- `capital_allocator` = scarce capital tilt

## 8. 테스트 반영안
대상:
- `/Users/yumin/Documents/trading/tests/test_portfolio_budget_report.py`
- `/Users/yumin/Documents/trading/tests/test_portfolio_overlay.py`
- `/Users/yumin/Documents/trading/tests/test_validation_report.py`
- `/Users/yumin/Documents/trading/tests/test_operational_checklist.py`
- `/Users/yumin/Documents/trading/tests/test_execution_operator_dashboard.py`
- `/Users/yumin/Documents/trading/tests/test_api_smoke.py`

고정할 것:
1. candidate row에 `allocated_risk_r`, `capital_allocator` 존재
2. `allocated_risk_r >= 0` 및 thin-sample neutral 케이스
3. validation summary 키 존재
4. checklist item semantics
5. dashboard signal_funnel summary 키 존재

## 9. README 반영안
대상:
- `/Users/yumin/Documents/trading/README.md`

추가 섹션:
- `Outcome-Aware Capital Allocator`

핵심 문구:
- `recommended_risk_r`와 `allocated_risk_r` 구분
- allocator는 portfolio layer 전용
- family 중심, regime/session modifier
- advisory/explanation과 runtime allowance의 경계 설명

## 10. 비목표
이번 patch 단계에서 하지 않는 것:
1. scanner row에 allocator 추가
2. approval response에 allocator 추가
3. rollout policy auto-change
4. static quota table 도입

## 11. 완료 기준
1. portfolio / validation / checklist / dashboard가 같은 allocator 언어를 쓴다.
2. `recommended_risk_r`와 `allocated_risk_r` 역할이 분리된다.
3. allocator가 hard authority와 섞이지 않는다.
