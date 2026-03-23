# Trading Engine v1 맥락 노트 (Living)

최종 갱신: 2026-03-09

## 1. 왜 이 작업을 하는가
- 추격 매매 대신 사전 플랜 기반으로 의사결정 일관성을 확보하기 위해
- 비용(수수료/슬리피지) 포함 EV 양수 기회만 집행해 장기 생존성을 높이기 위해
- zone_outcomes 학습 루프로 셋업 품질을 자동 정화하기 위해

## 2. 절대 규칙
1. 미래정보/리페인트 금지: 모든 계산은 인과적(causal)이어야 한다.
2. 리스크 우선: 수익 추구보다 계좌 보존이 우선이다.
3. 비용 우회 금지: 비용 포함 EV 필터를 우회하지 않는다.
4. 강추세 역방향/점프 과열 구간은 보수 라우팅 또는 스킵한다.
5. 이벤트는 outbox 기준으로 재처리 가능해야 한다.
6. 시간 저장은 UTC 고정, 표시 계층에서만 로컬 변환한다.
7. 검증 리포트가 `WARN/FAIL`이면 자동 알림을 남기고 원인 분석 없이 파라미터를 변경하지 않는다.
8. `/health/ready`가 `degraded`면 신규 라이브 진입을 보류한다.
9. 메타 필터(2차 게이트)를 우회하지 않는다.
10. 피처 중요도(Ablation) 분석에서 지속적으로 음수 기여를 보이는 항목은 가중치 재조정 대상이다.
11. 파라미터 변경은 자동 CHANGELOG 기록 없이 배포하지 않는다.
12. 운영 모드에서는 `/alerts/test`로 채널 전달 경로를 선검증하고, `validation_alert_channel=system`을 쓰는 경우 fanout 대상 채널 설정이 모두 유효한지 확인한다.
13. Timescale 정책/튜닝 변경 전에는 부하·보관 벤치마크를 재실행하고 `reports/timescale` PASS 리포트를 남긴다.
14. 스캐너 최종 진입 후보는 포트폴리오 오버레이(상관도/동시노출 제한)를 반드시 통과해야 한다.
15. 파라미터 조정 전에는 최근 `execution quality` 리포트로 슬리피지/미체결 편향을 먼저 확인한다.
16. vNext 구현은 `docs/UPGRADE_ROADMAP_VNEXT.md`의 Epic 순서와 승인 조건을 따른다.
17. 채널 알림 실패가 연속 임계치를 넘으면 서킷브레이커가 열릴 수 있으므로, 운영 중에는 복구 후 `/alerts/test`로 채널 상태를 재검증한다.
18. 실행 체결 이벤트는 `fill_id` 멱등 키로 처리하며, 동일 이벤트 재주입 시 상태/손익 집계를 변경하지 않는다.
19. 실행 품질 리포트는 `execution_fills`를 1차 근거로 사용하며, `zone_outcomes` 기반 추정치는 체결 원장이 없는 경우에만 fallback으로 허용한다.
20. 운영 시작 전과 알림 장애 복구 후에는 `/alerts/metrics`에서 채널별 성공률, p95 지연, 서킷 오픈 상태를 같이 확인한다.
21. 스캐너 최종 후보는 상관도뿐 아니라 `risk_budget_score`와 레짐별 동적 cap(`total/directional/cluster`)도 동시에 통과해야 한다.
22. 중요도 온라인 캘리브레이션은 최근 `plan.validity.confluence_components`와 `zone_outcomes`를 매칭한 `reports/calibration` snapshot만 runtime 적용 대상으로 인정하며, 한 번의 업데이트에서 가중치 급변(max delta 초과)을 허용하지 않는다.
23. `matched_samples` 또는 `baseline.generated_plans`가 최소 기준 미달이면 캘리브레이션 결과를 해석용 리포트로만 보고 runtime 가중치에 반영하지 않는다.
24. 전략 해석의 우선순위는 `상태 -> 위치 -> 유동성 -> 반응 -> 실행`이며, OB/FVG/트렌드라인을 독립 신호로 취급하지 않는다.
25. `transition`은 기본적으로 no-trade 상태이며, 예외는 `A급 Sweep Reversal + confirm only`로 제한한다.
26. 같은 thesis cluster에는 full-size 포지션 1개만 허용하고, `A-only` 운영 모드가 기본값이다.
27. `acceptance/rejection` 판정은 `docs/STRATEGY_V2_ACCEPTANCE_REJECTION_SPEC.md`의 바 마감 기준 규칙을 따르며, intrabar wick만으로 confirmed를 주지 않는다.
28. 실전 운영은 `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md`를 기준으로 하고, 구현 착수 전 항목 점검은 `docs/STRATEGY_V2_IMPLEMENTATION_CHECKLIST.md`를 따른다.
29. 전략 버전 롤아웃 전에는 `GET /execution/quality`의 `by_strategy_version`, `version_comparison`, `unfilled_reason_details`를 함께 확인해 집행 악화가 특정 버전에 집중되는지 먼저 본다.
30. `transition` 판정은 `docs/STRATEGY_V2_TRANSITION_REGIME_SPEC.md`의 score와 hard override 규칙을 따르며, scanner/engine 모두 같은 계산을 공유해야 한다.
31. thesis cluster 판정은 `docs/STRATEGY_V2_THESIS_FINGERPRINT_SPEC.md`를 기준으로 하고, scanner와 execution이 동일 fingerprint 함수를 사용해야 한다.
32. exit reason은 `docs/STRATEGY_V2_EXIT_EVENT_SCHEMA.md`의 enum과 우선순위를 따르며, execution quality와 validation report에 동일하게 반영한다.
33. 전략 v2 검증은 `docs/STRATEGY_V2_VALIDATION_PROTOCOL.md`를 기준으로 하며, `A-only`는 기본 배포 모드다.
34. `alerts/metrics.retry_queue.counts.dead_letter > 0`이면 라이브 운영 전 수동 재전송 또는 원인 제거가 먼저다.
35. 포트폴리오 관련 파라미터 조정 전에는 `GET /portfolio/budget`의 `current_exposure`, `headroom_by_regime`, `blocked_reason_counts`를 먼저 확인해 실제 병목이 total/directional/cluster 중 어디인지 분리한다.
36. `transition_confirmed`는 현재 엔진에서 즉시 `no-trade`로 처리되며, `transition_watch`는 최소 `confirm only`로 강등된다.
37. `reaction_classification`이 `mixed`면 현재 엔진은 신규 플랜을 생성하지 않으며, `acceptance_*`는 reversal 성격 후보를 차단한다.
38. `reaction_classification`이 `rejection_*`일 때만 `sweep_reversal` family routing을 허용하며, `trend` 비극단 위치와 `transition_watch`의 비A급 후보는 즉시 차단한다.
39. `trend_continuation`은 `acceptance`의 변형이 아니라 별도 family이며, `trend` + `OB/FVG` + `healthy pullback` + `protected level hold`를 동시에 만족할 때만 허용한다.
40. `range_rotation`은 현재 엔진에서 `research_only` family로만 인식하며, `range center` 후보는 별도 차단 reason으로 분리한다.
41. family가 없는 generic 후보는 runtime에서 `OB-only`, `FVG-only`, `trendline-led`면 즉시 차단하며, 현재 `trendline-led`는 `trend_proxy` 우세 generic setup을 proxy로 해석한다.
42. thesis cluster 판정은 현재 `app/services/thesis_fingerprint.py`가 단일 기준이며, `GET /scanner/top`과 `GET /portfolio/budget`의 thesis 필드는 반드시 같은 cluster id/reason을 보여야 한다.
43. 전략군 score는 현재 `strategy_scorecard`를 단일 계약으로 사용하며, raw component와 공통 bucket(`location/liquidity/reaction/invalidation/session`)은 동시에 저장해야 한다.
44. `trendline`은 현재 family score의 primary component가 아니며 `strategy_scorecard.buckets.trendline_bonus`로만 기록한다.
45. sizing은 현재 `strategy_sizing` 단일 계약으로 기록하며, 운영 판단은 `recommended_risk_r`를 기준으로 한다.
46. `transition_watch`, `transition_confirmed`, `mixed`, `active thesis cluster >= 2`는 현재 구현에서 모두 `recommended_risk_r = 0.00`으로 본다.
47. 운영 모드는 현재 `strategy_mode` 단일 계약으로 기록하며, 기본값은 `A_ONLY`다.
48. 현재 구현에서 `A_ONLY`는 `A급`, `A_PLUS_B`는 `A/B급`, `RESEARCH`는 `shadow-only`로 동작한다.
49. legacy generic plan은 기존 엔진 회귀를 유지하기 위해 현재 mode grade/family 하드 차단에서 임시 passthrough로 남아 있다.
50. 종료 이벤트는 현재 `execution_fills.payload`와 `plan.validity`에 같은 `exit_reason` 계약으로 남기며, 둘 중 하나라도 다르면 버그로 본다.
51. `strategy_family_time_stop_max_bars`를 넘긴 최종 청산은 `time_failure` 우선 검토 대상이며, `rejection -> acceptance` 또는 `mixed` 반전은 `information_failure`로 기록한다.
52. validation report와 execution quality report는 동일한 exit summary(`target/forced/information/time`)를 보여야 한다.
53. live mode(`A_ONLY`, `A_PLUS_B`)에서는 `OperatingLockService`가 `daily/session lock`을 강제하고, `RESEARCH`는 shadow-only라 lock을 보고만 한다.
54. daily lock 해제 시점은 `다음 UTC day`, session lock 해제 시점은 `현재 세션 종료`다.
55. `GET /metrics/strategy`, `GET /scanner/top`, `GET /portfolio/budget`의 `risk_reason`과 `operating_lock.reason`이 다르면 gate 합성 버그로 본다.
56. `A_ONLY` vs `A_PLUS_B` 검증은 현재 `StrategyV2ValidationService`가 `closed v2 plans`의 `strategy_family/strategy_grade/final_exit_*` 메타데이터만을 근거로 집계한다.
57. `strategy_v2_validation` 리포트의 기본 배포 권고는 현재도 `A_ONLY`이며, `A_PLUS_B`는 incremental B 샘플과 하방 지표를 먼저 확인하는 연구 축으로 본다.
58. `docs/STRATEGY_V2_BLUEPRINT.md`는 현재 `설계 목표`와 `현재 구현 메모`를 함께 기록하므로, 메모가 없는 항목은 자동화 완료로 가정하지 않는다.
59. `transition/shock lock` 비교는 현재 `StrategyV2LockValidationService`가 saved plan metadata 기준으로 재구성하며, transition trade는 제거하고 shock trade는 current regime factor만큼 계정 영향으로 clamp한다.
60. `thesis dedupe` 비교는 현재 `StrategyV2ThesisValidationService`가 글로벌 closed v2 plans 기준으로 재구성하며, ENTRY fill 시각이 있으면 open time으로 쓰고 없으면 `valid_from`으로 폴백한다.
61. `cost/slippage stress` 비교는 현재 `StrategyV2StressValidationService`가 saved closed v2 realized R에서 baseline/stressed cost를 차감하는 근사이며, `execution_fills`가 있으면 actual fee + entry slippage를 우선 사용한다.
62. `PBO/DSR`은 현재 `strategy_v2_pbo_dsr_artifact_store`, `strategy_v2_pbo_dsr_design`, `strategy_v2_pbo_dsr_metrics` 세 payload로 노출된다. artifact store는 저장 상태, design은 상위 계약, metrics는 실제 계산 결과다.
63. `strategy_v2_pbo_dsr_metrics.available=true`는 seeded artifact 기준으로 최소 한 축(PBO 또는 DSR)이 계산됐다는 뜻이고, `metrics_complete=true`여야 두 축이 모두 계산된 상태다.
64. `strategy_v2_pbo_dsr_design.available=true`는 artifact store에서 computed snapshot이 확인됐다는 뜻이며, 설계 문서가 계산 서비스와 동기화됐음을 의미한다.
65. `strategy_v2_pbo_dsr_artifact_store.artifact_store_ready=true`는 테이블/조회 계약이 준비됐다는 뜻이고, `metrics_available=true`는 latest snapshot 기준 PBO/DSR 두 축이 모두 계산됐다는 뜻이다.
66. `GET /validation/pbo-dsr`와 `POST /validation/report`의 `strategy_v2_pbo_dsr_metrics`가 현재 PBO/DSR 해석의 단일 기준이다.
67. 현재 DSR은 signed score와 probability를 같이 노출하지만, 배포 gate는 여전히 `dsr_value > 0` 규칙을 따른다.
68. `operations/checklist`는 현재 실전 운영용 단일 점검 진입점이며, `FAIL`과 blocking `MANUAL`은 라이브 시작 차단으로 해석한다.
69. `operations/checklist`는 `POST /alerts/test`를 자동 실행하지 않고 최근 테스트 이력만 본다. 채널 검증이 없으면 `MANUAL`이 정상 상태다.
70. `strategy_v2_stress_validation`은 현재 cost/slippage 외에도 `latency_plus_1_bar`, `partial_fills_only`, `shock_concentration` 시나리오를 포함한다.
71. 추가 stress 축은 full replay가 아니라 `plan/fill/candle` 메타데이터 기반 근사이므로, 방향성 해석용이지 체결 재현으로 취급하면 안 된다.
72. `operations/checklist`의 `session_guidance`는 운영 가이드 항목이고, `GET /scanner/top` 및 `GET /portfolio/budget` 후보 row의 `session_guidance`, `session_penalty`는 candidate-level soft penalty 항목이다.
73. `dead session`과 `session lock active`는 현재도 live hard block으로 승격하지 않고, ranking-only soft penalty만 반영한다.
74. `session_guidance`가 `WARN`이더라도 실제 진입 차단은 기존 `risk_gate_open`과 `operating_lock` 계약만이 담당한다.
75. 스캘핑 기본 운영에서는 `24h` 초과 zone을 hard skip하고, 최근 zone이 `created_ts` 기반 freshness boost를 받도록 본다.
76. 기본 plan validity는 `90m` baseline이며, dead session / session lock에서는 더 짧아진다.
77. preferred live session bias는 hard block이 아니라 setup score / expected probability의 소폭 boost로만 반영한다.
78. `strategy_v2_validation.family_metrics/family_summary`와 `session_metrics/session_summary`가 family/session 성과 해석의 기본 축이며, aggregate EV만으로 전략 우열을 단정하지 않는다.
79. `GET /validation/scalp-experiment`와 `POST /validation/report.strategy_v2_scalp_experiment`는 `15m zone / 5m execution` baseline과 `5m zone / 1m execution` experiment를 compare-only로 비교하는 계약이다.
80. `5m zone / 1m execution` branch는 실험용 비교 경로이며, live source-of-truth는 baseline server branch로 유지한다.
75. `strategy_v2_stress_replay_assessment.full_replay_ready=true`는 execution fill/latency candle lineage와 최소 표본이 full replay 논의를 할 만큼 갖춰졌다는 뜻이지, replay 엔진이 이미 구현됐다는 뜻은 아니다.
76. `strategy_v2_stress_replay_assessment.replacement_recommended=true`는 stress 근사가 충분하지 않다는 운영 우선순위 신호이며, 즉시 라이브 하드블록으로 해석하지 않는다.
77. stress 근사 유지 여부 판단은 현재 `GET /validation/stress-replay-assessment`와 `POST /validation/report`의 `strategy_v2_stress_replay_assessment` payload를 단일 기준으로 본다.
78. `strategy_v2_stress_replay_lineage`는 full replay 전환을 위한 입력 lineage 계약이며, writer나 runner가 이미 구현됐다는 뜻이 아니다.
79. `strategy_v2_stress_replay_lineage.runtime_inputs_ready=true`는 execution fill/latency candle/path coverage가 최소 임계값을 넘었다는 뜻이고, `available=true`보다 더 강한 상태다.
80. `strategy_v2_stress_replay_lineage.fill_path.exit_anchor_source=plan_final_exit_ts` 같은 fallback source는 정상 계약이며, lineage gap을 숨기지 않고 드러내기 위한 것이다.
81. `strategy_v2_pbo_dsr_trial_writer`는 현재 `mode/lock/stress` runtime proxy와 stored-plan threshold proxy family를 seed하는 hybrid proxy writer다.
82. `strategy_v2_pbo_dsr_threshold_runner`는 true threshold family를 `selection_rule=true_threshold_sweep_top_in_sample_ev`로 별도 seed하며, runtime proxy lineage와 같은 artifact store 안에서 공존한다.
83. `threshold_parameter_families_present`, `candidate_trials_by_family`는 hybrid proxy writer coverage를 해석하는 기준이고, true threshold lineage coverage는 `GET /validation/pbo-dsr/threshold-runner`로 본다.
84. combined lineage 해석은 `strategy_v2_pbo_dsr_artifact_store.selection_rule_counts`와 `strategy_v2_pbo_dsr_metrics.selected_trial.writer_source`를 단일 기준으로 쓴다.
85. `strategy_v2_stress_replay_runner_contract`는 full replay 엔진 자체가 아니라, prototype job batching과 worker IO contract를 고정한 design/runtime hybrid payload다.
86. `strategy_v2_stress_replay_runner_contract.runtime_job_ready=true`는 lineage/assessment 기준으로 prototype job을 만들 준비가 됐다는 뜻이지, queue worker가 이미 구현됐다는 뜻은 아니다.
87. `GET /validation/stress-replay-runner-contract`와 `POST /validation/report`의 `strategy_v2_stress_replay_runner_contract`가 replay prototype batch/readiness 해석의 단일 기준이다.
88. `strategy_v2_stress_replay_lineage_writer`는 replay를 실행하지 않고, scenario별 prototype input batch를 JSON artifact로 materialize하는 writer다.
89. `strategy_v2_stress_replay_lineage_writer.artifacts_written=true`는 batch input artifact가 생성됐다는 뜻이지, replay 결과 artifact가 있다는 뜻은 아니다.
90. `GET /validation/stress-replay-lineage-writer`와 `POST /validation/report`의 `strategy_v2_stress_replay_lineage_writer`가 scenario batch artifact 상태의 단일 기준이다.
91. `strategy_v2_stress_replay_output_artifacts`는 replay worker output artifact reader이며, artifact가 없어도 정상 상태일 수 있다.
92. `strategy_v2_stress_validation.replay_output_artifacts`와 `replay_output_comparison`은 replay output이 있는 scenario에 한해 deployment gate evidence로 승격된다.
93. `GET /validation/stress-replay-output-artifacts`는 latest scenario별 replay output artifact와 approximation delta를 읽는 단일 기준이다.
94. `strategy_v2_stress_replay_prototype_worker`는 lineage batch artifact를 읽어 replay output artifact를 실제 생성하는 prototype execution path이며, true market replay로 과대해석하면 안 된다.
95. `POST /validation/stress-replay-worker/prototype`와 `POST /validation/report`의 `strategy_v2_stress_replay_prototype_worker` payload가 현재 prototype worker 상태의 단일 기준이다.
96. prototype worker output이 생기면 `strategy_v2_stress_validation.deployment_recommendation`이 해당 scenario를 `replay_output` source로 재평가하고, `strategy_v2_stress_replay_assessment`는 그 결과 `scenario_statuses`를 그대로 소비한다.
97. replay output artifact가 없는 scenario는 계속 approximation 기준을 유지하므로, 현재 deployment gate는 hybrid(`approximation + replay-backed override`) 상태다.
98. `strategy_v2_stress_replay_assessment.true_runner_readiness`는 prototype replay worker readiness가 아니라, true market replay runner replacement readiness를 뜻한다.
99. `strategy_v2_stress_replay_assessment.deployment_recommendation.true_runner_promotion_*`는 base stress replacement decision과 별개로 실제 true market replay runner 승격 action을 나타내는 최종 운영 계약이다.
100. true runner 승격은 `true_runner_readiness.true_runner_ready=true`만으로 충분하지 않고, `strategy_v2_pbo_dsr_metrics.lineage_audit.audit_status=PASS`, `meets_protocol_gate=true`, `selected_trial_from_true_threshold=true`를 동시에 만족해야 한다.
101. dual-lineage가 공존하는데 selected trial이 runtime proxy에서 오면 stress replay assessment는 `decision`을 유지하더라도 `true_runner_promotion_action=stay_on_prototype`으로 승격을 막는다.
102. stress replay assessment endpoint와 validation report summary는 동일한 `true_runner_promotion_*` 언어를 써야 하며, 둘 중 하나만 바뀌는 상태를 허용하지 않는다.
103. `strategy_v2_pbo_dsr_metrics.selection_universe_summary`는 `combined artifact universe`와 `full parameter-sweep universe`를 분리 기록하는 단일 계약이다.
104. 현재 DSR 계산은 `full_parameter_sweep_selection_universe_size`가 있으면 `selection_universe_basis=full_parameter_sweep_universe`를 우선 사용하고, 없을 때만 `combined_artifact_universe`로 fallback한다.
105. `strategy_v2_pbo_dsr_artifact_store.selection_universe_summary`와 `strategy_v2_pbo_dsr_metrics.selection_universe_summary`는 같은 숫자를 써야 하며, 둘이 다르면 split recording이 깨진 상태로 본다.
106. `strategy_v2_pbo_dsr_metrics.dsr.legacy_combined_benchmark_sharpe`와 `benchmark_sharpe_delta_vs_legacy_combined`는 bias adjustment 기준 변경의 회귀 점검용이며, active deployment gate는 항상 `selection_universe_basis`가 가리키는 benchmark를 본다.
107. `strategy_v2_stress_replay_output_artifacts.lineage_summary`는 replay worker output provenance의 단일 기준이며, `input_batch_count`, `input_trade_rows`, `worker_modes`, `compared_scenarios`를 함께 본다.
108. `strategy_v2_stress_replay_assessment.deployment_recommendation.replay_output_lineage_alignment_*`는 `selected_trial source audit`와 `replay output lineage`를 직접 결합한 운영 해석 필드다.
109. `validation_report.deployment_approval_summary`는 `threshold lineage winner`와 `replay-derived worst scenario`를 같은 approval template에서 바로 읽기 위한 요약 계약이다.
110. `strategy_v2_stress_replay_assessment.deployment_recommendation.approval_cross_display`는 `selected trial lineage`와 `worst replay-backed stress scenario`를 직접 교차 표기하는 단일 payload다.
111. `approval_cross_display.approval_warning_locked/code/message`는 `runtime proxy winner + replay-backed downside` 조합일 때 승인 템플릿에 강한 경고 문구를 직접 고정하는 계약이다.
112. `deployment_approval_summary.topline_status/code/message`는 approval template 상단의 단일 승인 문구이며, `replay_output_lineage_alignment_*` 경고를 직접 반영한다.
113. `deployment_approval_summary.topline_summary_line`은 `winner / worst / promotion` 세 축을 항상 포함하는 one-line approval summary다.
114. `deployment_approval_summary.playbook_go_no_go/code/action/message`는 approval template warning code를 운영 playbook의 `GO / NO_GO / MANUAL_REVIEW` 문구로 직접 매핑하는 계약이다.
115. `validation_report.deployment_approval_summary.topline_message`, `operations/checklist.deployment_*`, `scanner.top[*].deployment_*`는 같은 `GO / NO_GO / MANUAL_REVIEW` 언어를 써야 하며, 서로 다른 prefix를 쓰면 계약 불일치로 본다.
116. `validation_alert.approval_topline_summary_line`는 `deployment_approval_summary.topline_summary_line`와 동일해야 하며, alert 저장 payload/재시도 payload/채널 메시지가 같은 one-line summary를 공유해야 한다.
117. `validation_alert.approval_playbook_go_no_go/code/action/message`는 `deployment_approval_summary.playbook_go_no_go/code/action/message`와 동일해야 하며, alert 저장 payload/재시도 payload/outbox payload가 같은 playbook mapping을 공유해야 한다.
118. `GET /portfolio/budget`의 top-level `deployment_go_no_go/code/message`와 portfolio markdown summary는 scanner/operations checklist와 같은 `GO / NO_GO / MANUAL_REVIEW` 언어를 공유해야 한다.
119. `validation_alert.deployment_go_no_go/code/message`는 scanner/portfolio/operations checklist와 같은 `GO / NO_GO / MANUAL_REVIEW` 언어를 써야 하며, `alerts/metrics.latest_validation_alert`와 `operations/checklist` evidence도 같은 필드를 직접 노출해야 한다.
120. `alerts/metrics.latest_validation_alert.approval_playbook_go_no_go/code/action/message`는 `validation_alert.approval_playbook_*`와 동일해야 하며, ops checklist의 `alert_channel_slo.evidence.latest_validation_alert`도 같은 playbook mapping을 직접 노출해야 한다.
121. `operations/checklist.portfolio_headroom.evidence.deployment_go_no_go/code/message`는 `/portfolio/budget` top-level `deployment_*`와 동일해야 하며, portfolio evidence는 headroom 숫자와 배포 언어를 동시에 보여줘야 한다.
122. validation alert 채널 메시지는 `approval=` one-line summary와 별도로 `deployment=<go_no_go>/<code>`를 직접 포함해야 하며, 운영자가 메시지 단독으로도 배포 언어를 해석할 수 있어야 한다.
123. `operations/checklist.validation_alert_delivery.evidence.approval_playbook_go_no_go/code/action/message`는 `validation_alert.approval_playbook_*`와 동일해야 하며, validation alert delivery evidence도 alert metrics 경로와 같은 수준으로 playbook mapping을 top-level에서 직접 노출해야 한다.
124. `GET /portfolio/budget`의 `playbook_go_no_go/code/action/message`는 `deployment_code`를 source-of-truth로 하는 portfolio용 운영 액션 문구여야 하며, validation approval playbook과 혼용하면 안 된다.
125. `app/services/deployment_contracts.py`는 alert/report deployment-playbook contract의 공통 helper이며, alert/test/subscribe/metrics/checklist/message formatter와 validation top-level consumer는 이 helper를 우선 사용해야 한다.
126. 현재 rollout-blocking backlog와 active post-rollout refactor backlog는 모두 비어 있으며, 남은 항목은 첫 라이브 운영 사이클 이후 contract pruning 재평가(optional hold)뿐이다.
125. validation alert 채널 메시지의 `playbook_action=`는 `approval_playbook_action`과 동일해야 하며, formatter가 운영 액션 문구를 누락하면 계약 불일치로 본다.
126. `POST /alerts/test`는 manual alert drill 경로이므로, 전달된 `approval_playbook_go_no_go/code/action/message`와 `deployment_go_no_go/code/message`를 top-level 응답에도 그대로 반환해야 한다.
127. `operations/checklist.portfolio_headroom.evidence.playbook_go_no_go/code/action/message`는 `/portfolio/budget` top-level playbook 필드와 동일해야 하며, checklist portfolio evidence도 deployment 언어와 운영 액션 문구를 함께 보여줘야 한다.
128. `POST /operations/checklist` top-level `playbook_go_no_go/code/action/message`는 `deployment_*`와 동일한 판단 축을 운영 행동 문구로 번역한 것이어야 하며, validation/report/portfolio top-level 요약과 다른 레벨의 의미를 쓰면 안 된다.
129. `POST /alerts/subscribe` 응답도 manual alert/subscribe 경로의 일관성을 위해 `deployment_go_no_go/code/message`, `approval_playbook_go_no_go/code/action/message`를 top-level로 직접 반환해야 한다.
130. `POST /validation/report` top-level `deployment_go_no_go/code/message`, `approval_topline_status/code/message/summary_line`, `playbook_go_no_go/code/action/message`는 `validation_report.deployment_approval_summary`의 passthrough contract여야 하며, `operations/checklist`는 같은 top-level contract를 우선 소비해야 한다.
131. 현재 남은 비검토 backlog는 rollout-blocking이 아니라 post-rollout refactor 성격으로 관리하며, 우선순위는 `alert contract dedup -> validation top-level/nested dedup` 순서로 고정한다.
132. `GET /indicators/pine`는 기존 엔진의 `ContextSnapshot + zones + plans`를 Pine/TradingView bridge용 payload로 직렬화한 view 계약이며, 라이브 실행 source-of-truth를 대체하면 안 된다.
133. `GET /indicators/pine-script`와 `scripts/tradingview/trading_engine_v1_mirror.pine`는 TradingView native mirror 스크립트이며, 최근 zone 중심의 chart-side approximation일 뿐 `plans/scanner/validation`를 대체하는 실행 계약이 아니다.
134. Binance 완전자동매매 2차의 futures user-stream source-of-truth는 `ORDER_TRADE_UPDATE`와 `ACCOUNT_UPDATE`이며, `executionReport`는 fallback 호환 경로로만 취급한다.
135. Binance user-stream live processing은 `websockets` optional dependency를 전제로 하며, 미설치 상태에서는 listen-key/REST position sync는 가능하지만 live stream process는 준비 미완료로 해석한다.
136. active backlog는 `docs/AUTO_TRADING_TRANSITION_CHECKLIST.md`를 source-of-truth로 관리하고, 앞으로 체크리스트 항목은 한 줄 체크박스가 아니라 `목적 / 구현 방식 / 완료 기준 / 검증`을 포함한 상세 형식으로만 추가한다.
137. 상세 체크리스트는 `좋다고 평가된 설계안`이라도 기존 machine contract를 깨지 않는 additive 순서로 재배치해야 하며, 구조 목표와 실제 PR 범위를 분리해 기록한다.
99. true runner readiness는 stronger lineage threshold와 critical scenario replay-output coverage를 동시에 만족해야 `true`가 된다.
100. `strategy_v2_pbo_dsr_metrics.lineage_audit`는 combined lineage 해석의 단일 기준이며, `selection_rule_counts + selected_trial.writer_source + selected_trial.selection_rule`를 함께 본다.
101. dual-lineage가 존재하는데 selected trial이 runtime proxy에서 선택되면, PBO/DSR minimum gate를 통과해도 deployment recommendation은 lineage 경고로 내려간다.
102. replay-backed stress scenario는 `replay_output - approximation` divergence를 별도 정책축으로 평가하며, scenario 자체가 PASS여도 divergence가 크면 deployment recommendation은 `replay_divergence_warn/fail`로 내려간다.
103. stress divergence 정책의 단일 기준은 `stress_replay_divergence_*` 설정값과 `strategy_v2_stress_validation.deployment_recommendation.divergence_*` 필드다.

## 3. 의사결정 우선순위
1. RiskGate 상태 확인 (`OPEN/THROTTLED/CLOSED`)
2. 레짐 확인 (`trend/range/shock`)
3. 컨플루언스 점수 확인
4. 비용 포함 EV, RR 하한 확인
5. 실행 모델 결정(LIMIT/CONFIRM/SWEEP_CONFIRM)

## 4. 신호 남발 방지 원칙
1. 기본값은 진입이 아니라 스킵이다.
2. 컨플루언스 하한 미달 신호는 전량 폐기한다.
3. 중복 엔트리(근접 가격대/동일 방향)는 1개만 허용한다.
4. 샘플 수가 충분한 음수 EV 셋업은 자동 비활성화한다.

## 5. 모델/버전 관리 원칙
- `strategy_version`을 zones/plans/outcomes/metrics에 함께 저장한다.
- 파라미터 변경 후에는 WF/MC 리포트를 재생성한다.
- 리포트 없이 라이브 정책 변경을 금지한다.

## 6. 운영 기준
- 기본 유니버스: `usdc_perp_top30`
- 기본 전략 버전: `v1`
- 기본 이벤트 백엔드: `memory` (운영 시 `redis`/`kafka` 전환)

## 7. 셀프체크 보고 형식 (고정)
1. 무엇을 발견했는가
2. 무엇을 수정했는가
3. 왜 그렇게 판단했는가
