# Strategy v2 PBO / DSR Design

최종 갱신: 2026-03-08
상태: Design ready / runtime proxy + separated true threshold runner seeded automatically when eligible / metrics computable when seeded

## 1. 목적
- `docs/STRATEGY_V2_VALIDATION_PROTOCOL.md`에 고정된 `PBO/DSR` 명세를 코드 런타임과 같은 계약으로 노출한다.
- 아직 계산할 수 없는 항목을 계산된 것처럼 포장하지 않고, 현재 blocker와 다음 구현 단계를 명시한다.

## 2. 현재 런타임 계약
- validation 경로는 다음 두 payload를 함께 반환한다.
  - `strategy_v2_pbo_dsr_trial_writer`
  - `strategy_v2_pbo_dsr_artifact_store`
  - `strategy_v2_pbo_dsr_design`
  - `strategy_v2_pbo_dsr_metrics`
- 전용 조회 endpoint:
  - `GET /validation/pbo-dsr/trial-writer`
  - `GET /validation/pbo-dsr/threshold-runner`
  - `GET /validation/pbo-dsr/artifact-store`
  - `GET /validation/pbo-dsr`
- 현재 기본 상태는 다음과 같다.
  - artifact store:
    - `artifact_store_ready=true`
    - `available=false|true` (seed 상태에 따라 달라짐)
    - `metrics_available=false|true` (latest snapshot 계산 상태에 따라 달라짐)
  - design payload:
    - `design_ready=true`
    - `available=false|true` (metrics runtime 연결 상태에 따라 달라짐)
  - metrics payload:
    - `available=false|true`
    - `metrics_complete=false|true`
    - `reason`으로 missing vs partial vs computed를 구분
- 생성 템플릿:
  - `reports/validation/strategy_v2_pbo_dsr_artifact_store_<SYMBOL>_<VERSION>_<UTC>.md`
  - `reports/validation/strategy_v2_pbo_dsr_design_<SYMBOL>_<VERSION>_<UTC>.md`

## 3. PBO 설계
- method: `CSCV`
- objective metric: `out_of_sample_mean_ev`
- thresholds:
  - pass: `0.20`
  - warn: `0.35`
  - fail: `0.35`
- parameter families:
  - `scoring_thresholds`
  - `transition_threshold`
  - `acceptance_rejection_thresholds`
  - `sizing_clamps`
- required inputs:
  - `parameter_sweep_trials`
  - `fold_level_out_of_sample_scores`
  - `selected_vs_non_selected_rankings`

## 4. DSR 설계
- method: `deflated_sharpe_ratio`
- minimum threshold: `0.0`
- required inputs:
  - `trade_sequence_returns`
  - `trial_count`
  - `selection_universe_size`
  - `sharpe_estimate`
  - `return_skew_kurtosis`
- selection bias inputs:
  - `number_of_trials`
  - `selection_rule`
  - `best_trial_oos_sharpe`

## 5. 저장 계약
- artifacts:
  - `validation_trial_runs`
  - `validation_trial_fold_scores`
  - `validation_pbo_dsr_snapshots`
- required fields:
  - `trial_id`
  - `parameter_family`
  - `parameter_values`
  - `fold_id`
  - `in_sample_metric`
  - `out_of_sample_metric`
  - `selection_rank`
  - `selected_flag`
  - `sharpe_like_score`

## 6. 현재 blocker
- separated true threshold runner는 연결됐지만, 여전히 `stored plan metadata` 기반 light rerun이지 full historical engine rerun은 아님
- eligible closed v2 trade 수가 부족하면 proxy writer와 true threshold runner 둘 다 seed를 만들지 못할 수 있음
- `full_parameter_sweep_universe` bias adjustment는 현재 연결됐지만, 여전히 stored-plan light rerun 기반 selected-trial universe이므로 full historical threshold rerun과 동일하다고 해석하면 안 됨

## 7. 다음 구현 순서
1. stored-plan light rerun을 historical engine rerun으로 교체할 readiness 기준을 추가
2. replay output artifact와 threshold lineage 차이를 같이 보는 deployment gate를 정리
3. true market replay runner 실행 lineage를 threshold lineage와 같은 배포 판정 gate로 더 직접 묶기
4. threshold lineage winner와 replay-derived worst scenario를 deployment approval template에서 더 직접 교차 표시

## 8. 운영 해석 규칙
- `strategy_v2_pbo_dsr_trial_writer.available=true`는 runtime proxy와 stored-plan threshold proxy trial/fold row가 자동 seed됐다는 뜻이다.
- `strategy_v2_pbo_dsr_trial_writer.available=false`는 보통 표본 부족 또는 fold 부족이며, writer 부재와 같은 뜻으로 해석하면 안 된다.
- `threshold_parameter_families_present`는 현재 writer가 seed한 threshold family 범위를 뜻한다.
- `candidate_trials_by_family`는 family별 proxy candidate 수를 뜻하며, true parameter rerun 건수를 의미하지 않는다.
- `strategy_v2_pbo_dsr_metrics.lineage_audit`는 combined lineage source audit의 단일 기준이다.
- `strategy_v2_pbo_dsr_metrics.selection_universe_summary`는 combined artifact universe와 full parameter-sweep universe split recording의 단일 기준이다.
- dual-lineage가 있는데 `selected_trial_from_runtime_proxy=true`면, `deployment_recommendation.lineage_audit_applied=true`가 함께 켜지고 배포 판단은 warning downgrade 상태로 본다.
- `dsr_selection_universe_basis=full_parameter_sweep_universe`는 true threshold lineage가 있을 때 bias adjustment가 새 기준으로 전환됐다는 뜻이다.
- `legacy_combined_benchmark_sharpe`와 `benchmark_sharpe_delta_vs_legacy_combined`는 old basis 대비 회귀 비교용이며, 승인 판단은 active `selection_universe_basis`를 따른다.
- `strategy_v2_pbo_dsr_design.available=false`는 runtime metric이 아직 없다는 뜻일 수 있고, 오류를 뜻하지 않는다.
- `strategy_v2_pbo_dsr_artifact_store.artifact_store_ready=true`는 schema/조회 계약이 준비됐다는 뜻이다.
- `strategy_v2_pbo_dsr_artifact_store.available=true`는 row가 존재한다는 뜻이다.
- `metrics_available=true`는 latest snapshot 기준 PBO/DSR 두 축이 모두 계산됐다는 뜻이다.
- `strategy_v2_pbo_dsr_metrics.metrics_complete=true` 전까지는 승인 수치처럼 해석하면 안 된다.
- 두 payload 모두 수익성 승인 지표가 아니라 구현 준비도와 저장 계약 점검용이다.
- 실제 배포 승인에는 여전히 `walk-forward`, `Monte Carlo`, `A-only vs A+B`, `transition/shock lock`, `thesis dedupe`, `stress` 비교가 우선이다.
