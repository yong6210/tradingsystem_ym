# Strategy v2 Validation Protocol

최종 갱신: 2026-03-09
상태: Validation design frozen

## 1. 목적
- 전략 v2를 `수익률`이 아니라 `EV`, `하방`, `과최적화 위험`, `운영 적합성` 기준으로 검증한다.

## 2. 비교 축
필수 비교:
1. `A-only` vs `A+B`
2. lock 적용 전 vs 후
3. thesis dedupe 적용 전 vs 후
4. time stop 적용 전 vs 후
5. baseline cost vs stressed cost

## 3. 기본 리포트 팩
각 비교마다 아래를 산출:
1. trades
2. win rate
3. EV
4. p5 EV
5. p50 EV
6. max drawdown
7. ulcer index
8. avg hold bars
9. forced exit ratio
10. information_failure ratio

## 4. Walk-Forward
기본값:
1. train `6 months`
2. test `2 months`
3. rolling step `1 month`

승인 기준:
1. test window의 `mean EV > 0`
2. `p5 EV > -0.8`
3. windows 중 `FAIL` 비중 `<= 25%`

## 5. Monte Carlo
기본값:
1. simulations `5000`
2. cost/slippage 분산 포함
3. thesis cluster dependency를 부분 반영

승인 기준:
1. `p5 EV > -0.6`
2. stressed `max drawdown`이 운영 허용 범위 이내

## 6. PBO
목적:
- parameter sweep 결과가 우연 적합인지 측정

기본값:
1. CSCV 기반 fold 분할
2. parameter families:
   - scoring thresholds
   - transition threshold
   - acceptance/rejection thresholds
   - sizing clamps

판정:
1. `PBO < 0.20`: 통과
2. `0.20 <= PBO < 0.35`: 경고
3. `PBO >= 0.35`: 실패

## 7. DSR
목적:
- 다중 시도 후 선택 편향을 보정한 Sharpe 유사 지표를 본다

판정:
1. `DSR > 0`: 최소 통과
2. `DSR <= 0`: 실패

## 8. Stress Test
필수 시나리오:
1. cost `x1.5`
2. slippage `x2`
3. signal latency `+1 bar`
4. partial fills only
5. shock regime concentration

승인 기준:
1. stressed 환경에서도 `catastrophic loss` 없음
2. A-only의 하방 방어가 A+B보다 우수

## 9. 보고서 구조
1. executive summary
2. comparison table
3. walk-forward section
4. Monte Carlo section
5. PBO / DSR section
6. stress section
7. exit reason / failure decomposition
8. deployment recommendation

## 10. 배포 승인 규칙
라이브 승격 조건:
1. Walk-forward 통과
2. Monte Carlo 통과
3. `PBO < 0.35`
4. `DSR > 0`
5. stressed drawdown 허용 범위 이내
6. A-only가 최소 1차 배포 모드
7. replay output artifact가 있는 scenario는 `strategy_v2_stress_validation.deployment_recommendation`의 replay-backed status를 우선 사용
8. replay-backed scenario는 `replay_output - approximation` divergence threshold도 같이 평가하며, divergence가 warn/fail 범위면 deployment recommendation은 `replay_divergence_warn/fail`을 우선 reason으로 사용한다
9. true market replay runner 교체는 `true_runner_readiness.true_runner_ready=true`일 때만 후보로 본다
10. true market replay runner 승격은 `strategy_v2_stress_replay_assessment.deployment_recommendation.true_runner_promotion_ready=true`일 때만 허용하며, 이는 `true_runner_ready`, `PBO/DSR protocol gate`, `threshold lineage audit PASS`, `selected_trial_from_true_threshold=true`를 동시에 만족해야 한다

## 11. 구현 메모
1. validation report v2/v3와 별개로 `strategy_v2_validation` 리포트 템플릿이 필요
2. comparison 축은 버전 태그와 mode 태그로 분리 저장
3. PBO/DSR은 후행 구현이어도 명세는 지금 고정한다
4. 현재 구현된 비교 축:
   - `A-only` vs `A+B`
   - `transition/shock lock` 적용 전후
   - `thesis dedupe` 적용 전후
   - baseline cost vs stressed cost(`cost x1.5`, `slippage x2`)
   - 추가 stress scenario(`latency +1 bar`, `partial fills only`, `shock concentration`)
5. 현재 validation runtime은 `strategy_v2_pbo_dsr_metrics`로 seeded artifact 기준 PBO/DSR를 계산하고, `strategy_v2_pbo_dsr_design`/`strategy_v2_pbo_dsr_artifact_store`로 design/lineage 상태를 함께 노출한다
6. 현재 validation runtime은 `strategy_v2_stress_replay_assessment`로 stress 근사 유지 여부와 full replay 대체 우선순위를 노출하지만, true market full replay 자체는 아직 계산하지 않는다
7. 현재 validation runtime은 `strategy_v2_stress_replay_lineage`로 execution fill / latency candle / candle path coverage와 fallback anchor source를 노출하며, 이는 full replay writer/runtime 입력 계약의 단일 기준이다
8. 현재 validation runtime은 `strategy_v2_stress_replay_runner_contract`로 scenario readiness, prototype batching, worker input/output contract를 노출하며, 이는 full replay runner/worker 설계의 단일 기준이다
9. 현재 validation runtime은 `strategy_v2_stress_replay_lineage_writer`로 scenario별 replay input batch artifact를 JSON으로 materialize하며, 이는 future replay worker 입력 artifact의 단일 기준이다
10. 현재 validation runtime은 `strategy_v2_stress_replay_output_artifacts`로 latest replay worker output artifact를 읽고 `strategy_v2_stress_validation.replay_output_artifacts` / `replay_output_comparison`으로 approximation 대비 delta를 노출한다
11. replay output artifact가 있는 scenario는 `strategy_v2_stress_validation.deployment_recommendation.scenario_statuses[*].source=replay_output`로 승격되며, `worst_scenario_source`도 함께 기록된다
12. 현재 validation runtime은 `strategy_v2_pbo_dsr_trial_writer`로 runtime proxy lineage를 seed하고, `strategy_v2_pbo_dsr_threshold_runner`로 true threshold-sweep lineage를 분리 seed한다. combined universe 해석은 `selection_rule_counts`와 `selected_trial.writer_source`를 기준으로 한다
13. 현재 validation runtime은 `strategy_v2_stress_replay_prototype_worker`와 `POST /validation/stress-replay-worker/prototype`로 lineage batch artifact를 실제 output artifact로 materialize하지만, 이는 deterministic prototype worker이지 true market replay runner가 아니다
14. 현재 validation runtime은 `strategy_v2_stress_replay_assessment.true_runner_readiness`와 `strategy_v2_stress_replay_runner_contract.true_runner_readiness`로 true runner replacement readiness를 별도 gate로 노출한다
15. 현재 validation runtime은 `strategy_v2_pbo_dsr_metrics.lineage_audit`로 dual-lineage selected-trial source를 감사하고, true threshold lineage가 있는데 selected trial이 runtime proxy면 deployment recommendation을 lineage warning으로 낮춘다
16. 현재 validation runtime은 `strategy_v2_stress_validation.deployment_recommendation.divergence_*`로 replay output과 approximation의 차이를 별도 정책축으로 고정한다
17. 현재 validation runtime은 `strategy_v2_stress_replay_assessment.deployment_recommendation.true_runner_promotion_*`로 true runner execution lineage와 threshold lineage audit를 함께 해석하며, base replacement decision과 actual runner promotion action을 분리해서 노출한다
18. 현재 validation runtime은 `strategy_v2_pbo_dsr_metrics.selection_universe_summary`와 `strategy_v2_pbo_dsr_artifact_store.selection_universe_summary`로 `combined artifact universe`와 `full parameter-sweep universe`를 분리 기록하고, DSR bias adjustment는 `full_parameter_sweep_universe`가 있으면 그 기준을 우선 사용한다. `legacy_combined_benchmark_sharpe`와 `benchmark_sharpe_delta_vs_legacy_combined`는 회귀 비교용 보조 값이다
19. 현재 validation runtime은 `strategy_v2_stress_replay_output_artifacts.lineage_summary`로 replay output provenance를 집계하고, `strategy_v2_stress_replay_assessment.deployment_recommendation.replay_output_lineage_alignment_*`로 selected-trial source audit와 replay output lineage의 정합성을 직접 판단한다
20. 현재 validation runtime은 `strategy_v2_stress_replay_assessment.deployment_recommendation.approval_cross_display`와 `validation_report.deployment_approval_summary`로 threshold lineage winner와 replay-derived worst scenario를 같은 approval template에서 직접 교차 표기한다
21. 현재 validation runtime은 `approval_cross_display.approval_warning_locked/code/message`로 `runtime proxy selected-trial`이 replay-backed downside와 함께 남는 경우 approval template 경고 문구를 직접 고정한다
22. 현재 validation runtime은 `deployment_approval_summary.topline_status/code/message`로 `replay_output_lineage_alignment_*` 경고를 approval template 최상단 승인 문구에 직접 연결한다
23. 현재 validation runtime은 `deployment_approval_summary.topline_summary_line`로 `threshold lineage winner / replay-derived worst scenario / true-runner promotion action`을 한 줄로 요약한다
24. 현재 validation runtime은 `deployment_approval_summary.playbook_go_no_go/code/action/message`로 approval template warning code를 운영 playbook의 `GO / NO_GO / MANUAL_REVIEW` 문구에 직접 매핑한다
25. 현재 validation runtime은 `deployment_approval_summary.topline_message`를 `GO / NO_GO / MANUAL_REVIEW` prefix로 출력하고, 같은 언어를 `operations/checklist.deployment_*`, `scanner.top[*].deployment_*`와 공유한다
26. 현재 validation runtime은 `validation_alert.approval_topline_summary_line`로 approval template one-line summary를 alert payload/재시도 payload/채널 메시지까지 동일하게 전달한다
27. 현재 validation runtime은 `validation_alert.approval_playbook_go_no_go/code/action/message`로 approval template playbook mapping을 alert payload/재시도 payload/outbox payload까지 동일하게 전달한다
28. 현재 runtime portfolio summary는 `GET /portfolio/budget`의 top-level `deployment_go_no_go/code/message`와 markdown summary로 scanner/operations checklist와 같은 `GO / NO_GO / MANUAL_REVIEW` 언어를 공유한다
29. 현재 validation runtime은 `validation_alert.deployment_go_no_go/code/message`를 alert payload에 직접 기록하고, `alerts/metrics.latest_validation_alert`, `operations/checklist.validation_alert_delivery.evidence`, `operations/checklist.alert_channel_slo.evidence.latest_validation_alert`도 같은 필드를 직접 노출한다
30. 현재 validation runtime은 `alerts/metrics.latest_validation_alert.approval_playbook_go_no_go/code/action/message`와 `operations/checklist.alert_channel_slo.evidence.latest_validation_alert`로 alert metrics 경로에서도 playbook mapping을 직접 노출한다
31. 현재 validation runtime은 `operations/checklist.validation_alert_delivery.evidence.approval_playbook_go_no_go/code/action/message`로 validation alert delivery evidence에서도 playbook mapping을 top-level로 직접 노출한다
32. 현재 runtime portfolio summary는 `operations/checklist.portfolio_headroom.evidence.deployment_go_no_go/code/message`로도 직접 노출되어 checklist portfolio evidence가 `/portfolio/budget` top-level 배포 언어를 그대로 따른다
33. 현재 runtime portfolio summary는 `GET /portfolio/budget`의 `playbook_go_no_go/code/action/message`와 markdown summary로 runtime deployment code 기반 운영 액션 문구를 직접 노출한다
34. 현재 validation alert 채널 메시지는 `deployment=<go_no_go>/<code>`를 직접 포함해 `approval=` one-line summary와 같은 메시지에서 배포 언어를 즉시 읽을 수 있게 한다
35. 현재 validation alert 채널 메시지는 `playbook_action=<approval_playbook_action>`도 직접 포함해 운영 액션 문구를 메시지 단독으로 확인할 수 있게 한다
36. 현재 `POST /alerts/test` 응답도 `deployment_*`, `approval_playbook_*`를 top-level로 직접 반환해 manual alert drill 경로가 validation alert payload와 같은 contract를 공유한다
37. 현재 `operations/checklist.portfolio_headroom.evidence.playbook_go_no_go/code/action/message`도 `/portfolio/budget` top-level playbook 필드와 동일하게 직접 노출된다
38. 현재 `POST /operations/checklist` top-level `playbook_go_no_go/code/action/message`도 validation/report/portfolio top-level summary와 같은 수준의 운영 액션 문구를 직접 노출한다
39. 현재 `POST /alerts/subscribe` 응답도 `deployment_*`, `approval_playbook_*`를 top-level로 직접 반환해 manual subscribe 경로가 `alerts/test`와 같은 contract를 공유한다
40. 현재 `POST /validation/report` top-level도 `deployment_*`, `approval_topline_*`, `playbook_*`를 직접 반환하며, `operations/checklist`는 validation deployment/playbook 해석 시 이 top-level contract를 우선 소비한다
41. 현재 `app/services/deployment_contracts.py`가 validation top-level/nested summary, validation alert payload, alert/test/subscribe/metrics/checklist/message formatter consumer의 공통 contract helper다
