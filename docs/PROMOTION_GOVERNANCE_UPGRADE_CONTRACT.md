# Promotion Governance Upgrade Contract

최종 갱신: 2026-03-23
상태: Item 1 baseline fixed

## 1. 목적
- `promotion governance`를 rollout policy 자동 변경 계층이 아니라 compare-only 승격 review language로 고정한다.
- `research -> probation -> production` 승격 검토를 operator가 같은 언어로 읽게 하되, approval / sizing / rollout DB authority와는 분리한다.

## 2. 허용 상태
허용 `state`:
1. `promotable`
2. `hold`
3. `defer`

허용 `promotion_bias`:
1. `consider_promote`
2. `hold`
3. `defer`

허용 `target_posture`:
1. `probation`
2. `production`
3. `keep_current`

## 3. 필수 필드
최소 summary shape:
1. `available`
2. `advisory_only`
3. `family`
4. `state`
5. `promotion_bias`
6. `target_posture`
7. `confidence`
8. `summary`
9. `reason_codes`
10. `source_summary`

`source_summary`는 아래 입력 축만 요약한다:
1. `rollout_recommendation`
2. `strategy_lifecycle`
3. `positive_evidence_expansion`
4. `outcome_bucket_granularity`
5. `family_execution_degradation_advisory`
6. `mode_advisory`
7. `capital_allocator`

## 4. 직접 반영 Surface
허용:
1. `validation_report`
2. `operations/checklist`
3. `execution/operator-dashboard`
4. `README`

## 5. 비반영 Surface
금지:
1. `ExecutionApproval`
2. `approval_snapshot`
3. `plan.validity`
4. `/scanner/top`
5. `/portfolio/budget` candidate row
6. rollout policy DB row
7. `operator_action_priority` hard ordering override

## 6. guardrail
1. thin sample에서는 `promotable`과 `consider_promote`를 금지한다.
2. family execution 상태가 `manual_review`면 `promotable`을 금지한다.
3. `outcome_bucket_granularity`는 family headline을 뒤집는 authority가 아니라 modifier summary로만 사용한다.
4. `capital_allocator`는 support-only input이며 승격 authority가 아니다.
5. promotion governance는 rollout recommendation과 별개다.

## 7. 역할 분리
1. `rollout_recommendation`은 policy suggestion이다.
2. `strategy_lifecycle`은 governance posture다.
3. `positive_evidence_expansion`은 controlled positive review language다.
4. `promotion_governance`는 승격 review decision language다.

## 8. 이번 라운드 계약 결론
1. promotion governance는 `promotable / hold / defer` 셋으로만 정리한다.
2. 출력은 compare-only summary로만 허용한다.
3. rollout DB, approval, sizing, candidate row semantics는 직접 바꾸지 않는다.
