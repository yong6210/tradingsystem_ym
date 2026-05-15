# Self-Check 로그 (Living)

현재 기준선: 2026-05-15 SIR canary bootstrap deadlock fix + MICRO_LIVE failure contract + live submit claim + partial-fill lifecycle guard + atomic report stack + boolean parser guard
참고: 각 Iteration의 테스트 수치/리포트 경로는 해당 시점 기록이며, 최신 운영 기준은 "현재 기준선"을 따른다.

## 2026-05-15 SIR Canary Bootstrap Deadlock Fix
### 무엇을 발견했는가
- `session_impulse_retest`는 장기 USDT proxy backtest와 yearly portfolio replay로 선별된 live/core universe를 쓰고 있었다.
- 그런데 live-enabled 상태에서도 최근 약 15시간 shadow 요약의 `recent_closed=0`, `decision=REJECT`, `ev_r=0`, `total_r=0`이 `session_impulse_retest_rollout_not_ready` hard blocker로 들어가 실제 주문 제출을 막을 수 있었다.
- 이 구조는 canary가 시작되지 않으면 live/최근 종료 표본이 생기지 않고, 표본이 없어서 canary가 시작되지 않는 bootstrap deadlock을 만든다.

### 무엇을 수정했는가
- `evaluate_micro_main_live_readiness`에서 short-window shadow evidence blocker를 `shadow_only=true`일 때만 hard blocker로 쓰게 했다.
- `shadow_only=false`인 live-enabled canary에서는 `shadow_not_available`, `no_recent_closed_sample`, short-window shadow EV/total/decision scarcity를 `advisory_blockers`로 남기고 live submit을 막지 않는다.
- 하드 차단은 family disabled, universe 밖, secondary rollout disabled, current core rollout window 밖처럼 live 계약 자체를 어기는 경우에 유지한다.
- zero-sample 상태에서는 `decision=REJECT`, `ev_r=0`, `total_r=0`을 별도 negative evidence로 중복 해석하지 않고 `no_recent_closed_sample` 관측값으로만 남긴다.
- 같은 패턴의 운영 오해를 막기 위해 `transition_edge_variant_live_readiness`도 live-enabled 상태에서는 shadow pass 부족/평가 부족을 `advisory_blockers`로 분리했다.
- 최근 1주일 로그 재검토에서 SIR 후보가 readiness blocker를 통과하더라도 `outcome_approval_penalty=downgrade_to_manual`이 실제 SIR/live execution 표본 0개 상태에서 다시 manual gate로 작동할 수 있음을 확인했다.
- `ExecutionPlanningService`는 `session_impulse_retest` live bootstrap에서 execution degradation manual-review가 material execution sample 없이 나온 경우 자동 제출을 막지 않고 reason-only advisory로 남기게 했다. 단, SIR에 실제 matured/fill/closed execution sample이 생긴 뒤의 manual-review degradation은 계속 `APPROVED_MANUAL`로 낮춘다.

### 운영상 의미
- 검증을 없앤 것이 아니라, live authority를 원래 의도한 장기 replay-validation bridge와 live/core allowlist로 되돌렸다.
- 짧은 shadow 창은 live-enabled canary를 막는 truth source가 아니라, canary가 돌아가는 동안 drift/품질을 보는 관측값이다.
- 주문이 실제로 나가려면 여전히 runtime GO, session contract, safety locks, liquidity gate, duplicate/reentry guard, exchange submit guard를 모두 통과해야 한다.

## 2026-05-10 MICRO_LIVE Failure Contract Drill Guard
### 무엇을 발견했는가
- 운영 가드가 많이 늘었지만, 장애를 사람이 머릿속으로만 상상하면 missing/stale/malformed report, 짧은 macro horizon, alert delivery failure, submit-ready gap 같은 실패가 `PASS`로 숨지 않는지 반복 검증하기 어렵다.
- 기존 incident drill은 control-plane rehearsal 중심이라, 실제 운영 리포트/주문 경로 계약의 negative case를 live 상태 변경 없이 한 번에 검증하는 경로가 부족했다.

### 무엇을 수정했는가
- `scripts/run_micro_live_failure_drill.py`를 추가했다.
- 이 드릴은 temp 파일과 순수 평가 함수만 사용해 실제 주문/실 DB/control switch를 건드리지 않는다.
- 검증 시나리오는 `ops_missing_report`, `ops_malformed_report`, `ops_stale_report`, `macro_short_horizon`, `alert_delivery_failure_contract`, `reconciliation_stale_submission_without_ledger`, `no_order_submit_ready_gap`, `runtime_audit_hard_failure_contract`다.
- timestamp 리포트와 함께 `reports/operations/micro_live_failure_drill/latest.md/latest.json`을 남긴다.
- ops heartbeat가 failure drill 최신성과 내부 `PASS` 상태를 감시하도록 추가했다.
- launchd generator에 daily `failure-drill` job을 추가했다.
- launchd macro calendar refresh가 기본 auto file만 갱신하지 않고, `AUTO_TRADING_MICRO_LIVE_EVENT_BLACKOUT_PATH`가 있으면 live approval/heartbeat가 실제 읽는 configured blackout 계약 파일을 직접 갱신하게 했다.
- launchd 생성 시 `--env-file`을 쓰는 경우도 해당 env 파일의 `AUTO_TRADING_MICRO_LIVE_EVENT_BLACKOUT_PATH`를 우선해 macro refresh output을 정하게 했다.
- launchd plist 생성과 `~/Library/LaunchAgents` 설치 복사를 atomic replace로 바꿔, 중간 종료 시 partial/corrupt plist가 남지 않게 했다.
- `launchctl bootstrap` 실패는 `overall_status=FAIL`과 non-zero exit로 드러내고, 기존 job이 로드되어 있지 않은 `bootout` 실패는 `WARN`으로만 남기게 했다.
- live approval이 읽는 runtime contract builder 3종을 atomic write로 통일했다: macro blackout, strategy-time contract, plan blocklist.
- 세 contract builder 모두 저장 JSON 안에 `output_path`를 포함해, 어떤 파일이 실제 갱신됐는지 payload 자체로 확인할 수 있게 했다.
- worker boot check가 failure-contract drill도 실행하게 해, guard 계약 자체가 깨진 상태에서는 `MICRO_LIVE/LIVE` worker 시작 전에 차단되게 했다.
- `run_worker.py --mode once`에서 boot check 실패 시 unsupported `once` heartbeat를 쓰려다 원래 실패 원인이 가려지는 문제를 막았다.
- worker heartbeat 파일도 UUID 임시 파일과 cleanup을 사용하게 해 같은 프로세스 내 빠른 재기록에서 tmp 충돌 가능성을 줄였다.
- no-order watchdog, ops heartbeat, replay validation bridge의 latest/state writer도 고정 `.tmp` 대신 UUID 임시 파일과 cleanup을 사용하게 했다.
- 공통 `operation_report_io.atomic_write_text`도 예외 시 tmp cleanup을 보장하게 했다.
- runtime guard, boot check, reconciliation watchdog, synthetic canary, no-order watchdog, ops heartbeat, replay validation bridge, session impulse retest runtime audit, failure drill의 timestamp report 쓰기도 atomic으로 통일했다.
- preflight/review/brief/stage/notify/watch 계열 운영 파일 writer도 공통 atomic writer를 쓰게 해, 중간 종료 시 partial markdown/json이 운영 증거로 남는 가능성을 줄였다.
- Binance live/order/user-stream 정규화에서 문자열 boolean(`"false"`, `"0"`, `"no"`)을 Python truthy 문자열로 오판하지 않도록 `_safe_bool`을 추가했다. 이로써 `reduceOnly="false"`가 엔트리 주문을 reduce-only 청산 주문처럼 보이게 하는 방어 취약점을 막았다.
- 알림 dispatcher/retry/heartbeat/watchdog cooldown 경로도 같은 boolean parser를 쓰게 해, `delivered="false"` 같은 문자열 payload가 전송 성공처럼 기록되어 이후 알림을 suppress하는 상황을 막았다.
- live submit/approval/safety lock/rollout/preflight/plan generation/reconciliation/dashboard 계열도 같은 boolean parser를 쓰게 해, `live="false"`, `auto_trading_close_only="false"`, `shadow_only="false"`, `live_enabled="false"` 같은 문자열 설정/페이로드가 주문 승인, 차단, 리컨실리에이션, 운영 표시를 뒤집지 않게 했다.
- 추가 점검에서 no-order/reconciliation watchdog의 `alert`, 운영 대시보드/체크리스트의 `available/advisory_only/accepted`, 포지션 사이징의 `confirm_only`, 백테스트 캐시 플래그도 문자열 boolean에 흔들리지 않게 정리했다.
- `session_impulse_retest` miss detector JSON과 feature calibration latest/snapshot JSON도 UUID 임시 파일 후 atomic replace로 쓰게 해, 중간 종료 시 partial runtime evidence가 남지 않도록 했다.
- operator action priority와 ops stage board의 `new_entries_allowed/readiness gate/blocking` 판정도 문자열 boolean을 안전하게 해석하게 해, 운영 보드가 entry gate 상태를 잘못 표시하지 않게 했다.
- live submit은 Binance 호출 전에 `LIVE_SUBMITTING` claim row를 먼저 커밋하게 해, 같은 intent 동시 호출이 거래소 중복 주문으로 이어지지 않게 했다. claim row에는 `clientOrderId`, sizing, liquidity, tranche 정보를 남겨 장애 시 reconciliation anchor로 쓴다.
- live submitter가 claim 이후 예외를 내거나 malformed response를 돌려도 새 submission을 만들지 않고 같은 claim row를 `LIVE_SUBMIT_ERROR`로 갱신해, retry 전에 거래소 상태 확인이 필요하다는 사실을 DB에 남기게 했다.
- Binance submit response와 user-stream에서 `PARTIALLY_FILLED`가 들어오면 fill ingest payload에 `partial=True`를 전달하게 해, 부분 체결 submission이 `FILLED`로 잘못 승격되는 수명주기 오류를 막았다.
- repaired fill, paper exit monitor, user-stream fill ingest의 `accepted/duplicate/partial` 판정도 문자열 boolean 안전 해석을 쓰게 해, `"false"`가 성공/중복/완전체결처럼 처리되지 않게 했다.
- `paper_lineage_override_applied`, `transition_edge_variant_applied`, `operating_lock.active`, `new_entry_allowed`, stage/preflight/checklist/notify surface의 `available/advisory_only/healthy` 계열도 추가로 문자열 boolean 안전 해석을 적용했다.
- feature calibration과 plan generation의 runtime `available/apply/enabled` 판정도 문자열 boolean 안전 해석으로 맞춰, `"false"` 설정이나 payload가 calibration 적용을 켜는 상황을 막았다.
- session impulse retest auto-route/refresh audit 저장 실패가 이미 생성/제출된 주문 라우팅 결과나 plan refresh 결과를 가리지 않도록, core 결과 commit과 audit commit을 분리하고 audit 실패는 rollback 후 `runtime_audit_error`로 응답에 남기게 했다.
- 대용량 archive 산출물이 untracked로 계속 잡혀 git status/push 작업을 느리게 만들지 않도록 `.gitignore`에 `archives/`를 추가했다.
- `app.services.report_io.atomic_write_text`를 추가하고 operational checklist, validation report, portfolio budget, alert metrics, execution quality, historical walk-forward cache, parameter changelog, stress replay lineage writer, v2 validation/research/stress/PBO 리포트 writer를 atomic replace로 통일했다.
- 추가 문자열 boolean 패스에서 session guidance, scanner operating lock, alert subscription, stage-change 알림, ops stage board, operator action priority, execution dashboard, stress/replay readiness, edge experiment/evolution, outcome control, opportunity capture, kill-condition automation 경로도 `_safe_bool`로 맞췄다.
- 이로써 `"false"`/`"0"`/`"off"` 문자열이 세션 active, operating lock active, subscription active, replay ready, edge comparison ready, post-unlock ready, stress pass, outcome penalty applied 같은 운영 판단을 참으로 뒤집는 잔여 케이스를 줄였다.
- validation report, alpha research, PBO/DSR design/metrics, outcome attribution/funnel/granularity, runtime signoff, replay bridge, paper drill, preflight, plan generation, position sizing, strategy-v2 session bucket, thesis fingerprint, promotion mismatch waterfall까지 추가로 훑어 `available/ready/active/confirm_only/kill_review_triggered` 계열 문자열 boolean 오판을 더 줄였다.
- 특히 `strategy_family_confirm_only`, `active_manual_override`, preflight `kill_review_triggered`, session window `active`, replay bridge material slice 같은 값이 `"false"` 문자열일 때 실제 판단이나 운영 리포트가 반대로 보일 수 있는 경로를 정리했다.
- watchdog/heartbeat의 알림 전달 판정은 `NotificationDispatcher._safe_bool` 클래스 메서드에 직접 의존하지 않게 로컬 parser로 분리했다. 테스트나 장애 대응에서 fake dispatcher를 주입해도 cooldown/notification 경로가 깨지지 않는다.
- 같은 fake dispatcher 취약점이 `notify_entry_surface`, `notify_operator_session_brief`, `notify_stage_change`, `stage_monitor_tick`에도 남아 있어 알림/상태 스냅샷 parser를 dispatcher 클래스에서 분리했다.
- 추가 검색에서 PBO/DSR metrics의 `available`, edge evolution closed-loop feedback, B-continuation activation annotation도 raw truthy 판정이 남아 있어 `_safe_bool`로 맞췄다.
- 모든 `_safe_bool`/`_bool` 계열 false literal에 `"none"`/`"null"`을 추가했다. `default=True`인 `available/advisory_only/fail_closed` 계열에서 문자열 nullish 값이 참으로 뒤집히는 케이스를 막았다.
- Binance websocket kline의 `x` final flag도 `_safe_bool`로 읽게 해, `"false"` 문자열이 마감봉처럼 처리되어 runtime signal timing을 앞당기는 위험을 줄였다.
- `@staticmethod`/`@classmethod` 내부에서 `self._safe_bool` 또는 잘못된 클래스명(`ExecutionApprovalService`)을 참조하던 런타임 NameError를 정리했다. 대상은 execution approval, order intent 응답 직렬화, live contract counting, operator dashboard approval strip, kill-condition automation source summary다.
- runtime worker heartbeat JSON이 깨졌을 때 `missing`으로 숨기지 않고 `status=invalid`로 반환하게 해, readiness 진단에서 corrupt heartbeat와 missing heartbeat를 구분할 수 있게 했다.
- runtime worker heartbeat의 naive ISO timestamp를 로컬 타임존이 아니라 UTC로 고정해서 해석/저장하게 했다. 수동/이전/외부 heartbeat 파일이 timezone 없는 ISO를 남겨도 KST 오프셋 때문에 stale 또는 recovered 판단이 틀어지는 위험을 줄였다.
- micro-main readiness/proxy backtest/reaction variant/promotion mismatch report writer도 공통 atomic write로 바꿔, 검증 산출물이 중간 종료로 partial JSON을 남길 위험을 줄였다.
- README, operating runbook, incident drill playbook, near-100 hardening plan을 같은 명령어 기준으로 갱신했다.

### 왜 그렇게 판단했는가
- 지금 남은 구조적 리스크는 “버그 하나”보다 “실패가 정상처럼 보이는 상태”다.
- negative contract drill을 고정하면 다음부터는 운영 가드 자체가 실패를 숨기는지 먼저 검증할 수 있다.

### 최신 검증 스냅샷
- 정적 검증:
  - `./.venv/bin/python -m py_compile scripts/run_micro_live_failure_drill.py scripts/run_micro_live_ops_heartbeat.py scripts/run_micro_live_no_order_watchdog.py scripts/run_replay_validation_bridge.py scripts/install_micro_live_ops_launchd.py scripts/run_worker.py scripts/operation_report_io.py app/services/runtime_worker_heartbeat.py app/services/strategy_engine.py tests/test_run_worker_boot_check.py tests/test_session_impulse_retest_audit_guard.py`
- 테스트 실행 결과:
  - `./.venv/bin/python -c 'from _pytest.config import main; raise SystemExit(main(["-q","tests/test_run_worker_boot_check.py","tests/test_health_readiness.py::test_worker_heartbeat_replaces_existing_file_atomically","tests/test_micro_live_operational_guards.py::test_launchd_generator_replaces_plists_atomically","tests/test_micro_live_operational_guards.py::test_launchd_installer_copies_plists_atomically","tests/test_micro_live_operational_guards.py::test_launchd_generator_returns_failure_when_load_fails","tests/test_micro_live_operational_guards.py::test_launchd_generator_keeps_unload_failure_as_warning","-q"]))'`
  - `6 passed`
  - UUID tmp writer 직접 검증: `atomic_writers_ok`
  - auto-route audit guard 직접 검증: `audit_guard_ok`
  - worker boot check 직접 검증: `worker_boot_check_once_guard_ok`
  - worker heartbeat 직접 검증: `worker_heartbeat_atomic_ok`
  - launchd plist 직접 검증: `launchd_plist_atomic_ok`
  - 추가 atomic ops writer 정적 검증: `./.venv/bin/python -m py_compile scripts/run_micro_live_runtime_guard.py scripts/run_micro_live_boot_check.py scripts/run_micro_live_synthetic_canary.py scripts/run_live_reconciliation_watchdog.py scripts/run_session_impulse_retest_runtime_audit_report.py scripts/run_micro_live_failure_drill.py scripts/run_micro_live_no_order_watchdog.py scripts/run_micro_live_ops_heartbeat.py scripts/run_replay_validation_bridge.py scripts/run_micro_live_preflight.py scripts/run_runtime_signoff_review.py scripts/stage_monitor_tick.py scripts/ops_stage_board.py scripts/notify_entry_surface.py scripts/notify_operator_session_brief.py scripts/notify_stage_change.py scripts/paper_lineage_watch_tick.py scripts/watch_paper_candidate_drill.py`
  - 추가 atomic ops writer diff check: `git diff --check`
  - boolean parser 정적 검증: `./.venv/bin/python -m py_compile app/integrations/binance_futures.py app/services/strategy_engine.py app/services/execution_coordinator.py app/services/notification_dispatcher.py app/services/alert_retry_queue.py tests/test_binance_client.py tests/test_binance_trade_api.py`
  - 확장 boolean parser 정적 검증: `./.venv/bin/python -m py_compile app/services/execution_approval.py app/services/order_intents.py app/services/safety_locks.py app/services/execution_reconciliation.py app/services/live_order_lifecycle.py app/services/execution_operator_dashboard.py app/services/plan_generator.py app/services/fast_failure_guard.py app/services/portfolio_risk_overlay.py app/services/micro_main_live_readiness.py app/services/micro_main_universe_policy.py app/services/micro_main_strategy_research.py`
  - 보조 운영/리포트 boolean parser 정적 검증: `./.venv/bin/python -m py_compile app/services/b_continuation_activation.py app/services/multi_strategy_ab.py app/services/feature_calibration.py app/services/historical_walk_forward_proof.py app/services/portfolio_budget_report.py app/services/strategy_v2_pbo_dsr_trial_writer.py app/services/strategy_v2_scalp_experiment.py app/services/validation_payload_cache.py`
  - 추가 운영 표면/atomic writer 정적 검증: `./.venv/bin/python -m py_compile app/services/notification_dispatcher.py scripts/run_live_reconciliation_watchdog.py scripts/run_micro_live_no_order_watchdog.py app/services/execution_operator_dashboard.py app/services/operational_checklist.py app/services/portfolio_budget_report.py app/services/scanner.py app/services/strategy_cluster_balance.py app/services/strategy_indicators.py app/services/strategy_engine.py app/services/portfolio_risk_overlay.py app/services/position_sizing.py app/services/historical_walk_forward_proof.py app/services/feature_calibration.py app/services/multi_strategy_ab.py`
  - 운영 stage/action 보드 정적 검증: `./.venv/bin/python -m py_compile app/services/operator_action_priority.py scripts/ops_stage_board.py`
  - live submit claim/추가 boolean parser 정적 검증: `./.venv/bin/python -m py_compile app/services/execution_coordinator.py app/services/order_intents.py app/services/position_state_machine.py app/services/execution_operator_dashboard.py app/services/operational_checklist.py app/services/kill_condition_automation.py app/services/strategy_engine.py app/services/plan_generator.py scripts/run_micro_live_preflight.py scripts/collect_operator_surface_divergence_snapshot.py scripts/run_paper_candidate_drill.py scripts/stage_monitor_tick.py scripts/ops_stage_board.py scripts/notify_stage_change.py scripts/run_post_live_pruning_review.py scripts/notify_entry_surface.py scripts/watch_paper_candidate_drill.py`
  - live submit claim/추가 boolean parser diff check: `git diff --check -- app/services/execution_coordinator.py app/services/order_intents.py app/services/position_state_machine.py app/services/execution_operator_dashboard.py app/services/operational_checklist.py app/services/kill_condition_automation.py app/services/strategy_engine.py app/services/plan_generator.py scripts/run_micro_live_preflight.py scripts/collect_operator_surface_divergence_snapshot.py scripts/run_paper_candidate_drill.py scripts/stage_monitor_tick.py scripts/ops_stage_board.py scripts/notify_stage_change.py scripts/run_post_live_pruning_review.py scripts/notify_entry_surface.py scripts/watch_paper_candidate_drill.py`
  - partial-fill lifecycle/atomic report stack 정적 검증: `./.venv/bin/python -m py_compile app/services/strategy_engine.py app/services/execution_coordinator.py app/services/report_io.py app/services/alpha_research_pipeline.py app/services/strategy_v2_stress_replay_assessment.py app/services/strategy_v2_pbo_dsr_design.py app/services/strategy_family_edge_review.py app/services/strategy_v2_scalp_experiment.py app/services/replay_evidence_review.py app/services/strategy_v2_stress_validation.py app/services/strategy_v2_pbo_dsr_trial_writer.py app/services/strategy_v2_pbo_dsr_artifact_store.py app/services/strategy_v2_stress_replay_prototype_worker.py app/services/strategy_v2_stress_replay_lineage.py app/services/historical_walk_forward_split_review.py app/services/strategy_v2_validation.py app/services/strategy_v2_thesis_validation.py app/services/strategy_v2_lock_validation.py app/services/strategy_v2_pbo_dsr_metrics.py app/services/strategy_v2_stress_replay_output_artifacts.py app/services/strategy_v2_stress_replay_runner_contract.py app/services/strategy_v2_pbo_dsr_threshold_runner.py app/services/live_alpha_operating_review.py app/services/plan_generator.py app/services/feature_calibration.py app/services/historical_walk_forward_proof.py app/services/parameter_changelog.py app/services/strategy_v2_stress_replay_lineage_writer.py scripts/stage_monitor_tick.py scripts/ops_stage_board.py scripts/notify_stage_change.py`
  - partial-fill lifecycle/atomic report stack diff check: `git diff --check -- docs/SELF_CHECK_LOG.md app/services/strategy_engine.py app/services/execution_coordinator.py app/services/report_io.py app/services/alpha_research_pipeline.py app/services/strategy_v2_stress_replay_assessment.py app/services/strategy_v2_pbo_dsr_design.py app/services/strategy_family_edge_review.py app/services/strategy_v2_scalp_experiment.py app/services/replay_evidence_review.py app/services/strategy_v2_stress_validation.py app/services/strategy_v2_pbo_dsr_trial_writer.py app/services/strategy_v2_pbo_dsr_artifact_store.py app/services/strategy_v2_stress_replay_prototype_worker.py app/services/strategy_v2_stress_replay_lineage.py app/services/historical_walk_forward_split_review.py app/services/strategy_v2_validation.py app/services/strategy_v2_thesis_validation.py app/services/strategy_v2_lock_validation.py app/services/strategy_v2_pbo_dsr_metrics.py app/services/strategy_v2_stress_replay_output_artifacts.py app/services/strategy_v2_stress_replay_runner_contract.py app/services/strategy_v2_pbo_dsr_threshold_runner.py app/services/live_alpha_operating_review.py app/services/plan_generator.py app/services/feature_calibration.py app/services/historical_walk_forward_proof.py app/services/parameter_changelog.py app/services/strategy_v2_stress_replay_lineage_writer.py scripts/stage_monitor_tick.py scripts/ops_stage_board.py scripts/notify_stage_change.py`
  - 추가 boolean hardening 정적 검증: `./.venv/bin/python -m py_compile app/db/repositories.py app/services/scanner.py app/services/alert_metrics.py app/services/forward_stress_regime_validation.py app/services/edge_evolution_rule.py app/services/replay_evidence_review.py app/services/strategy_v2_stress_replay_runner_contract.py app/services/strategy_v2_stress_replay_output_artifacts.py app/services/strategy_v2_stress_replay_lineage_writer.py app/services/strategy_v2_stress_replay_prototype_worker.py scripts/notify_stage_change.py app/services/edge_experiment_review.py app/services/outcome_control_trace.py app/services/opportunity_capture.py app/services/kill_condition_automation.py app/services/feature_calibration.py app/services/strategy_v2_stress_validation.py app/services/strategy_engine.py app/services/operator_action_priority.py app/services/execution_operator_dashboard.py app/services/session_guidance.py app/services/execution_friction_measurement.py app/services/execution_degradation_advisory.py scripts/stage_monitor_tick.py scripts/ops_stage_board.py`
  - 추가 boolean hardening diff check: `git diff --check -- docs/SELF_CHECK_LOG.md app/db/repositories.py app/services/scanner.py app/services/alert_metrics.py app/services/forward_stress_regime_validation.py app/services/edge_evolution_rule.py app/services/replay_evidence_review.py app/services/strategy_v2_stress_replay_runner_contract.py app/services/strategy_v2_stress_replay_output_artifacts.py app/services/strategy_v2_stress_replay_lineage_writer.py app/services/strategy_v2_stress_replay_prototype_worker.py scripts/notify_stage_change.py app/services/edge_experiment_review.py app/services/outcome_control_trace.py app/services/opportunity_capture.py app/services/kill_condition_automation.py app/services/feature_calibration.py app/services/strategy_v2_stress_validation.py app/services/strategy_engine.py app/services/operator_action_priority.py app/services/execution_operator_dashboard.py app/services/session_guidance.py app/services/execution_friction_measurement.py app/services/execution_degradation_advisory.py scripts/stage_monitor_tick.py scripts/ops_stage_board.py`
  - 추가 report/preflight/plan boolean hardening 정적 검증: `./.venv/bin/python -m py_compile app/services/validation_report.py app/services/alpha_research_pipeline.py app/services/strategy_v2_pbo_dsr_design.py app/services/outcome_funnel_operating_kpis.py app/services/outcome_bucket_granularity.py app/services/alt_data_family_research.py app/services/outcome_attribution.py app/services/strategy_v2_pbo_dsr_metrics.py app/services/historical_walk_forward_proof.py app/services/thesis_fingerprint.py app/services/position_sizing.py app/services/strategy_v2_validation.py app/services/plan_generator.py scripts/setup_micro_main_prop_alerts.py scripts/generate_operator_session_brief.py scripts/run_split_review_followup.py scripts/run_runtime_signoff_review.py scripts/run_paper_candidate_drill.py scripts/run_replay_validation_bridge.py scripts/notify_operator_session_brief.py scripts/run_micro_live_boot_check.py scripts/run_micro_live_failure_drill.py scripts/run_micro_live_preflight.py scripts/analyze_promotion_mismatch_waterfall.py`
  - 추가 report/preflight/plan boolean hardening diff check: `git diff --check -- docs/SELF_CHECK_LOG.md app/services/validation_report.py app/services/alpha_research_pipeline.py app/services/strategy_v2_pbo_dsr_design.py app/services/outcome_funnel_operating_kpis.py app/services/outcome_bucket_granularity.py app/services/alt_data_family_research.py app/services/outcome_attribution.py app/services/strategy_v2_pbo_dsr_metrics.py app/services/historical_walk_forward_proof.py app/services/thesis_fingerprint.py app/services/position_sizing.py app/services/strategy_v2_validation.py app/services/plan_generator.py scripts/setup_micro_main_prop_alerts.py scripts/generate_operator_session_brief.py scripts/run_split_review_followup.py scripts/run_runtime_signoff_review.py scripts/run_paper_candidate_drill.py scripts/run_replay_validation_bridge.py scripts/notify_operator_session_brief.py scripts/run_micro_live_boot_check.py scripts/run_micro_live_failure_drill.py scripts/run_micro_live_preflight.py scripts/analyze_promotion_mismatch_waterfall.py`
  - notification/fake-dispatcher 회귀 검증: `./.venv/bin/pytest -q tests/test_notify_operator_session_brief.py tests/test_entry_surface_scripts.py -q`
  - 결과: `12 passed`
  - stage notification fake-dispatcher 회귀 검증: `./.venv/bin/pytest -q tests/test_stage_monitor_scripts.py::test_dispatch_stage_notification_truncates_message_for_discord -q`
  - 결과: `1 passed`
  - `./.venv/bin/pytest -q tests/test_micro_live_operational_guards.py -q`
  - `57 passed`
  - nullish boolean parser 정적 스캔: `_safe_bool/_bool` 중 `"true"/"false"`를 처리하면서 `"none"/"null"`이 빠진 함수 `0건`
  - static/classmethod self-reference AST 스캔: `0건`
  - 추가 정적 검증: `rg -l '"none", "null"' app scripts | xargs ./.venv/bin/python -m py_compile`
  - 추가 정적 검증: `./.venv/bin/python -m py_compile app/services/runtime_worker_heartbeat.py app/services/execution_approval.py app/services/execution_operator_dashboard.py app/services/strategy_engine.py app/services/kill_condition_automation.py scripts/operation_report_io.py scripts/run_micro_main_live_readiness.py scripts/run_micro_main_usdt_proxy_backtest.py scripts/run_reaction_gate_variant_backtest.py scripts/analyze_promotion_mismatch_waterfall.py scripts/run_replay_validation_bridge.py tests/test_notification_dispatcher.py tests/test_binance_trade_api.py tests/test_health_readiness.py`
  - 추가 diff check: `rg -l '"none", "null"' app scripts | xargs git diff --check --`
  - 추가 diff check: `git diff --check -- app/services/runtime_worker_heartbeat.py app/services/execution_approval.py app/services/execution_operator_dashboard.py app/services/strategy_engine.py app/services/kill_condition_automation.py scripts/operation_report_io.py scripts/run_micro_main_live_readiness.py scripts/run_micro_main_usdt_proxy_backtest.py scripts/run_reaction_gate_variant_backtest.py scripts/analyze_promotion_mismatch_waterfall.py scripts/run_replay_validation_bridge.py tests/test_notification_dispatcher.py tests/test_binance_trade_api.py tests/test_health_readiness.py`
  - 추가 타깃 회귀 검증: `./.venv/bin/pytest -q tests/test_notification_dispatcher.py tests/test_binance_trade_api.py tests/test_health_readiness.py::test_health_worker_corrupt_heartbeat_is_invalid_not_missing tests/test_kill_condition_automation.py tests/test_execution_operator_dashboard.py tests/test_execution_transition.py -k 'micro_live_submit or live_submit or execution_lane_tracker or notification or binance or corrupt_heartbeat or kill_condition or operator_dashboard' -q`
  - 결과: `42 passed`
  - 추가 실행 경로 회귀 검증: `./.venv/bin/pytest -q tests/test_session_impulse_retest_execution_path.py -q`
  - 결과: `73 passed`
  - 추가 실행 경로 회귀 검증: `./.venv/bin/pytest -q tests/test_micro_live_preflight.py -q`
  - 결과: `21 passed`
  - 추가 실행 경로 회귀 검증: `./.venv/bin/pytest -q tests/test_api_smoke.py -q`
  - 결과: `1 passed`
  - 추가 실행 경로 회귀 검증: `./.venv/bin/pytest -q tests/test_binance_client.py -q`
  - 결과: `20 passed`
  - 추가 실행 경로 회귀 검증: `./.venv/bin/pytest -q tests/test_execution_transition.py -q`
  - 결과: `52 passed`
  - heartbeat timezone 회귀 검증: `./.venv/bin/pytest -q tests/test_health_readiness.py -q`
  - 결과: `25 passed`
  - heartbeat/worker/session 통합 회귀 검증: `./.venv/bin/pytest -q tests/test_health_readiness.py tests/test_micro_live_preflight.py tests/test_session_impulse_retest_execution_path.py -q`
  - 결과: `119 passed`
  - timezone parser 재검색: `fromisoformat(...).astimezone(...)` 직접 패턴 `0건`
  - 중복 class/method AST 스캔: `0건`
  - 전체 Python 컴파일 검증: `find app scripts tests -name '*.py' -print0 | xargs -0 ./.venv/bin/python -m py_compile`
  - 최신 전체 회귀 검증: `./.venv/bin/pytest -q -rs`
  - 결과: `968 passed, 1 skipped`
  - 이번 추가 수정 후 전체 회귀는 재시도했지만 pytest 출력 없이 실행 세션이 종료되어 확정 결과로 기록하지 않는다. 현재 확정값은 위 정적 검증과 타깃 테스트다.
- 드릴 실행 결과:
  - `./.venv/bin/python scripts/run_micro_live_failure_drill.py --no-fail-exit`
  - 결과: `PASS`, scenario_count `8`, failed_count `0`
  - latest: `reports/operations/micro_live_failure_drill/latest.md`, `latest.json`
- heartbeat 확인:
  - `./.venv/bin/python scripts/run_micro_live_ops_heartbeat.py --no-fail-exit`
  - 결과: `WATCH`, hard failure `0`; `failure_drill=PASS`

## 2026-05-10 MICRO_LIVE Content-Aware Ops Heartbeat Guard
### 무엇을 발견했는가
- ops heartbeat가 리포트 freshness만 보면, 최신 no-order/replay/boot report 안에 `ALERT/WATCH/FAIL`이 있어도 스케줄은 정상처럼 보일 수 있었다.
- 이 구조는 “파일은 생성됐지만 내용은 문제”인 상태를 놓칠 수 있다.

### 무엇을 수정했는가
- `run_micro_live_ops_heartbeat.py`가 최신 markdown/json report의 `overall_status`, `status`, `evaluation.status`를 읽도록 보강했다.
- hard failure와 watch를 분리해 `FAIL`과 `WATCH`를 구분한다.
- 리포트 job 기본 패턴을 실제 report 파일로 좁혀 `state.json` 같은 상태 파일이 최신 리포트를 가리지 않게 했다.
- 상태를 읽어야 하는 report에서 status가 없으면 `content_status_missing` failure로 처리한다.
- macro blackout 계약은 `windows`를 직접 읽어 future horizon이 최소 기준 이상인지 heartbeat에서 확인하게 했다.
- macro blackout 감사는 glob 최신 파일보다 `.env`의 `AUTO_TRADING_MICRO_LIVE_EVENT_BLACKOUT_PATH`를 우선해 live approval과 같은 계약을 본다.
- macro blackout 파일 mtime이 stale이어도 horizon이 충분하면 hard failure가 아니라 `WATCH`로 분리한다.
- heartbeat 알림 메시지는 hard failure와 watch를 `긴급/주의`로 나눠 보여준다.
- 같은 heartbeat issue 조합은 state-file cooldown으로 반복 발송을 억제하고, issue 조합이 바뀌면 즉시 다시 보낸다.
- cooldown state는 알림 전송이 `delivered=True`로 확인된 경우에만 기록해, 실패한 알림 시도가 다음 알림을 막지 않게 했다.
- heartbeat는 timestamp 리포트와 함께 `latest.md/latest.json` 고정 alias도 써서 운영자가 최신 파일을 찾지 않아도 되게 했다.
- heartbeat latest alias와 cooldown state는 atomic replace로 써서 중간 실패 시 partial file이 남지 않게 했다.
- 현재 WATCH 원인인 no-order watchdog과 replay validation bridge도 `latest.md/latest.json` alias를 쓰도록 맞췄다.
- no-order watchdog도 알림 전송 성공이 확인된 경우에만 cooldown state를 기록하게 했다.
- 현재 실제 heartbeat는 hard failure 0개, watch 2개다. watch 원인은 `no_order_watchdog=ALERT`, `replay_validation_bridge=WATCH`다.

### 왜 그렇게 판단했는가
- 운영자가 봐야 하는 것은 “스케줄이 돌았나”와 “그 결과가 안전한가” 둘 다다.
- freshness-only PASS는 주문 미진입, replay bridge 혼합 증거, Binance rule drift 같은 상태를 숨길 수 있으므로 content-aware heartbeat가 더 안전하다.

## 2026-05-10 MICRO_LIVE Replay Bridge Confidence/Slice Guard
### 무엇을 발견했는가
- replay validation bridge가 평균 EV와 전체 집계만 보면, 특정 방향/패밀리/엔트리모델 슬라이스가 약한데도 통과 후보처럼 보일 수 있었다.
- 평균 EV가 양수여도 표본 변동성을 고려한 하한이 음수면 라이브 검토 후보로 보기 어렵다.

### 무엇을 수정했는가
- `run_replay_validation_bridge.py`에 `ev_r_lower_95`와 `win_rate_lower_95`를 추가했다.
- 기본 bridge 기준에 `min_ev_lower_r=0.0`을 추가해 EV 95% 하한이 음수인 심볼을 차단한다.
- `direction`, `strategy_family`, `entry_model`별 material slice 진단을 추가했다.
- 전체 집계가 통과해도 material slice가 약하면 `ELIGIBLE_FOR_MANUAL_BRIDGE_REVIEW_WITH_SLICE_WARNINGS`로 낮추고, live approval은 그대로 변경하지 않는다.

### 왜 그렇게 판단했는가
- replay-backed sampling을 검토하려면 “평균적으로 좋다”보다 “불리한 하위구간이 어디인지 알고 들어간다”가 더 중요하다.
- 현재 11개 live/core 심볼 기준 bridge 결과는 `BCHUSDC`, `BTCUSDC`만 clean manual-review 후보이고, `ADAUSDC`, `AVAXUSDC`는 slice warning 후보이며, 나머지는 아직 bridge floor 미달이다.

## 2026-05-10 MICRO_LIVE Validation Root-Cause/Flow Diagnosis Guard
### 무엇을 발견했는가
- `validation_do_not_deploy`가 보여도 표본 부족, EV/승률 문제, 점수 floor, risk gate, runtime candidate block 중 무엇이 핵심 원인인지 즉시 구분하기 어려웠다.
- 포트폴리오 live-vs-replay parity는 집계 비율만으로는 `신호가 없었는지 / intent는 있었는데 승인에서 막혔는지 / 제출 루프에서 끊겼는지`를 심볼별로 빠르게 분리하기 어려웠다.
- Discord no-order 알림이 운영자가 바로 읽기에는 verbose했다.

### 무엇을 수정했는가
- approval snapshot의 `validation_block_detail`에 `primary_cause`와 `root_causes`를 추가했다.
- 기존 DB에 남아 있는 legacy blocked intent도 lifecycle report에서 root-cause detail을 보정해 보여준다.
- `run_live_replay_parity_audit.py`가 심볼별 `flow_diagnosis.stage`를 산출하고, 전체 live universe에서는 stage/reason counts를 집계한다.
- replay cadence는 충분하지만 모든 intent가 approval에서 막힌 심볼은 `PASS` 대신 `WATCH`로 표시한다.
- `run_replay_validation_bridge.py`를 추가해 replay cache가 보수적 bridge 기준을 넘는지 audit-only로 산출한다. live approval은 변경하지 않는다.
- no-order Discord 메시지를 `intent/제출/원인/상세/다음` 중심으로 축약했다.

### 왜 그렇게 판단했는가
- 지금 주문 미진입 상태는 submit 버그만 찾는 방식으로는 부족하다. signal/plan 생성, approval, intent submission, exchange reject/error를 분리해야 다음 조치가 정확하다.
- 현재 로컬 3일 로그 기준 live intent 11건은 모두 제출 전 승인에서 차단됐고, 주요 원인은 `validation_sample_missing` 9건과 `rollout_session_not_allowed` 2건이다.

## 2026-05-10 MICRO_LIVE Worker Boot/Parity/Heartbeat Guard
### 무엇을 발견했는가
- boot check는 있었지만 `run_worker.py` 시작 경로에 강제되지 않아, 운영자가 수동으로 빼먹을 수 있었다.
- 단일 심볼 parity만으로는 11개 live universe 전체에서 어떤 심볼이 flow 미달인지 한 번에 보기 어려웠다.
- launchd plist는 생성됐지만 스케줄이 실제로 리포트를 계속 만드는지 감시하는 heartbeat가 없었다.
- `validation_do_not_deploy`는 주문 차단의 핵심 사유였지만, 최근 blocked intent에서 grade/risk/deployment context를 바로 읽기 어려웠다.

### 무엇을 수정했는가
- `run_worker.py`가 `MICRO_LIVE`/`LIVE` 모드에서 시작 전 `run_micro_live_boot_check.py`를 강제 실행하고, 실패 시 live routing을 시작하지 않도록 했다.
- `run_live_replay_parity_audit.py --all-live-symbols`를 추가해 11개 live symbol 전체의 replay 기대 빈도 대비 live intent 빈도를 집계한다.
- `run_micro_live_ops_heartbeat.py`를 추가해 runtime guard, no-order watchdog, reconciliation watchdog, synthetic canary, boot check, Binance rule drift, macro blackout report freshness를 확인한다.
- no-order/runtime guard의 blocked intent diagnostics에 `validation_do_not_deploy` 상세 context를 붙였다.
- launchd generator에 `ops-heartbeat` job을 추가했다.

### 왜 그렇게 판단했는가
- live worker 시작 전 실패를 막는 것은 사후 알림보다 강한 가드다.
- 포트폴리오 합산 빈도가 괜찮아도 개별 심볼이 장기간 0 flow면 운영상 점검 대상이므로 개별 ALERT를 전체 ALERT로 끌어올린다.

## 2026-05-10 MICRO_LIVE Operational Guard Closure
### 무엇을 발견했는가
- no-order watchdog은 intent->submission 공백은 잡지만, submission->Binance ledger/user-stream/reconciliation 공백은 별도 감시가 필요했다.
- live-vs-replay parity audit가 local API에 먼저 의존해, 웹 서버가 내려간 상태에서는 baseline을 못 읽는 운영 취약점이 있었다.
- 반복 점검은 문서화돼 있었지만 macOS에서 같은 guard를 주기적으로 실행하는 표준 plist 생성 경로가 없었다.

### 무엇을 수정했는가
- `run_live_reconciliation_watchdog.py`를 추가해 stale live submission, ledger terminal mismatch, open ledger/position user-stream stale, fresh critical reconciliation event를 감지한다.
- `run_micro_live_boot_check.py`를 추가해 worker 시작 전 runtime guard, reconciliation watchdog, synthetic canary를 한 번에 확인한다.
- `install_micro_live_ops_launchd.py`를 추가해 runtime guard, no-order watchdog, reconciliation watchdog, synthetic canary, boot check, rule drift, macro calendar refresh plist를 생성한다.
- `run_live_replay_parity_audit.py`가 parity에 필요한 active-contract cadence와 replay baseline을 local DB/파일에서 먼저 계산하고, 실패할 때만 local API로 fallback하도록 바꿨다.
- macro blackout fallback contract 복원 로직이 고정 15분 pre-window를 가정하지 않고 현재 `--pre-minutes` 값을 반영하도록 수정했다.

### 왜 그렇게 판단했는가
- "주문이 안 들어간다" 문제는 signal 부재, approval block, submission 미생성, exchange ledger 미정착, user-stream stale을 분리해야 원인과 조치가 정확해진다.
- launchd는 live authority가 아니라 감시 자동화다. 실제 주문 제출 여부는 기존 approval/safety/execution gate가 계속 결정한다.

## 2026-05-10 MICRO_LIVE Runtime Guard Documentation Sync
### 무엇을 발견했는가
- README는 최신 MICRO_LIVE 운영 스크립트를 일부 담고 있었지만, go-live checklist와 operating runbook이 같은 실행 순서를 공유하지 않았다.
- go-live checklist 안에서 현재 live 계약이 `BTCUSDC` only와 `BTCUSDC/ETHUSDC` live 계약으로 동시에 적혀 있었다.
- `.env` 예시가 없어 현재 canary allowlist, sizing, liquidity gate, blackout path를 안전하게 재현하기 어려웠다.

### 무엇을 수정했는가
- README, go-live checklist, operating runbook을 `BTCUSDC + sweep_reversal + LIMIT` live 계약으로 맞추고 `ETHUSDC`는 advisory/proof comparison으로 고정했다.
- runtime guard, live order lifecycle report, no-order watchdog, synthetic canary, macro blackout builder를 운영 순서에 연결했다.
- `.env.example`을 추가해 실제 live submit은 꺼둔 채 현재 canary 계약과 fail-closed liquidity gate 값을 문서화했다.

### 왜 그렇게 판단했는가
- live 제출 직전 문서는 전략 설명보다 재현 가능한 guard 순서와 설정 경계가 더 중요하다.
- `no trade` 상태를 signal 부재, approval block, submit skip, order failure, fill 없음으로 분리해야 운영자가 gate를 잘못 완화하지 않는다.

## 2026-03-09 Iteration #126
### 무엇을 발견했는가
- `GET /execution/operator-ui`는 한국어 요약과 상단 핵심 숫자는 정리됐지만, 화면이 여전히 세로 스택 중심이라 `대표 플랜`을 보면서 동시에 `후보 목록 / 승인 / 락 / 최근 intent`를 옆에서 훑기 어려웠다.
- 특히 사용자가 요청한 `카드형 + 옆 목록` 운영 데스크 형태와는 아직 거리가 있었다.

### 무엇을 수정했는가
- `/Users/yumin/Documents/trading/app/services/execution_operator_ui.py`를 메인 카드 컬럼 + 우측 사이드바 목록 레이아웃으로 재구성했다.
- 메인 컬럼에는 `한눈에 보는 현재 상태`, `핵심 카드`, `대표 플랜`, `현재 진입 가이드`, `열린 주문 / 포지션`, `리컨실리에이션`을 유지했다.
- 우측 사이드바에는 `실행 후보 목록`, `활성 플랜 목록`, `스캐너 대표 후보`, `승인 / 체크리스트`, `포트폴리오 / 알림 / 체결 품질`, `최근 Intent`, `락 / 롤아웃 정책`을 카드형 목록으로 재배치했다.
- 회귀 테스트와 README, 체크리스트 기준선을 현재 layout 기준으로 동기화했다.

### 왜 그렇게 판단했는가
- 이 화면의 핵심 사용 시나리오는 운영자가 메인 카드에서 `지금 할 일`을 읽고, 사이드바에서 `왜 허용/차단됐는지`, `지금 어떤 후보가 살아있는지`를 동시에 확인하는 것이다.
- 따라서 새 데이터나 판단 로직을 추가하는 것보다, 기존 source-of-truth를 메인/사이드 구조로 재배치하는 편이 사용성 개선에 직접적이었다.

### 최신 검증 스냅샷
- 정적 검증: `./.venv/bin/python -m py_compile app/services/execution_operator_ui.py`
- API smoke 실행 결과: `1 passed` (`./.venv/bin/pytest -q tests/test_api_smoke.py -q`)

## 2026-03-09 Iteration #123
### 무엇을 발견했는가
- auto-trading transition 회귀 중 `strategy_mode=RESEARCH` plan이 micro-live/rollout gate보다 늦게 평가돼 `APPROVED_SHADOW` 대신 차단될 수 있었다.
- 일부 transition 테스트가 로컬 `.env`를 직접 읽어 실제 운영 설정에 따라 흔들렸고, PBO/DSR recompute 회귀도 runtime `strategy_version`과 fixture version drift가 생기면 실패할 수 있었다.

### 무엇을 수정했는가
- `ExecutionPlanningService.approve(...)`에서 `strategy_mode=RESEARCH`를 rollout/live gate보다 먼저 `APPROVED_SHADOW`로 처리하도록 우선순위를 조정했다.
- auto-trading transition 테스트가 `_env_file=None` 기준 settings를 사용하도록 정리하고, scanner/overlay도 동일 settings 객체를 재사용하도록 맞췄다.
- PBO/DSR recompute 회귀는 fixture plan version을 현재 runtime `strategy_version`에 맞춰 생성하도록 보정했다.
- `/Users/yumin/Documents/trading/docs/AUTO_TRADING_TRANSITION_CHECKLIST.md`, `/Users/yumin/Documents/trading/docs/CHECKLIST.md`, `/Users/yumin/Documents/trading/docs/PLAN.md`, `/Users/yumin/Documents/trading/README.md`, `/Users/yumin/Documents/trading/docs/SELF_CHECK_LOG.md`를 `Iteration #123` 기준으로 동기화했다.

### 왜 그렇게 판단했는가
- 이 단계에서 중요한 건 새 기능 추가보다 approval precedence와 테스트 결정성을 고정하는 것이다.
- `.env` 의존 테스트와 runtime version drift를 방치하면 운영 설정 변화가 회귀 실패로 번져 실제 transition 안정성을 과장하거나 과소평가하게 된다.

### 최신 검증 스냅샷
- 타깃 회귀 실행 결과: `7 passed` (`./.venv/bin/pytest -q tests/test_auto_trading_transition_phase1.py tests/test_strategy_v2_pbo_dsr_trial_writer.py -k 'approval_service_covers_manual_shadow_allowlist_stale_and_no_go or auto_trading_settings_defaults_and_preview_approval_api_paths or recompute_learning_seeds_trial_writer_and_pbo_dsr_metrics'`)
- 전체 테스트 실행 결과: `217 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)

## 2026-03-09 Iteration #122
### 무엇을 발견했는가
- `scripts/watch_paper_candidate_drill.py`와 관련 README/runbook/checklist 일부는 이미 반영됐지만, `PLAN`과 `SELF_CHECK_LOG`, 상세 전환 체크리스트 기준선이 아직 이전 Iteration에 머물러 있었다.
- 이 상태는 기능 자체보다 living docs 신뢰도를 떨어뜨려, 운영자가 현재 기준선과 helper 가용 상태를 잘못 읽을 위험이 있었다.

### 무엇을 수정했는가
- `/Users/yumin/Documents/trading/docs/AUTO_TRADING_TRANSITION_CHECKLIST.md`, `/Users/yumin/Documents/trading/docs/CHECKLIST.md`, `/Users/yumin/Documents/trading/docs/PLAN.md`, `/Users/yumin/Documents/trading/docs/SELF_CHECK_LOG.md`를 `Iteration #122` 기준으로 동기화했다.
- `PLAN`에 `Phase ZL-55. PAPER Lineage Watcher Helper`를 추가해 helper 목적, 구현 방식, 산출 리포트 경로를 실행 계획서에 명시했다.

### 왜 그렇게 판단했는가
- 지금 단계는 새 기능보다 운영 helper의 반복 가능성과 문서 일관성이 더 중요하다.
- watcher helper가 실제로 존재하는데 living docs에 동일 기준선으로 안 올라가 있으면, 이후 운영 절차가 다시 수동 메모에 의존하게 된다.

### 최신 검증 스냅샷
- 코드 변경 없음. docs-only 기준선 정렬만 수행했다.
- helper 자체 최신 검증 상태 유지:
  - `./.venv/bin/python -m py_compile scripts/watch_paper_candidate_drill.py`
  - `./.venv/bin/python scripts/watch_paper_candidate_drill.py --max-attempts 1 --interval-seconds 1 --no-write-report`
- 최근 helper 결과:
  - eligible lineage candidate 없음
  - operational next step은 `PAPER` lineage 대상 family 후보가 나올 때까지 watcher를 돌리는 것

## 2026-03-09 Iteration #120
### 무엇을 발견했는가
- `operator-dashboard`, runbook, go-live checklist, incident drill, operator UI까지는 있었지만, 실제 `MICRO_LIVE` 직전 점검을 한 번에 실행하는 helper와 첫 live 운영 사이클 이후 pruning review reopen 여부를 판정하는 helper가 living docs 기준선에는 없었다.
- 운영 전환은 구현보다 반복 가능한 명령 절차가 더 중요하므로, runtime helper가 문서 기준선에 올라와 있지 않으면 실제 운영 단계에서 다시 수동 jq 해석으로 돌아갈 위험이 있었다.

### 무엇을 수정했는가
- `/Users/yumin/Documents/trading/scripts/run_micro_live_preflight.py`를 기준선에 반영하고, `health/operator/safety/validation/checklist/alerts/scanner`를 묶어 `READY_FOR_MICRO_LIVE` vs `NOT_READY`를 판단하는 helper로 문서화했다.
- `/Users/yumin/Documents/trading/scripts/run_post_live_pruning_review.py`를 기준선에 반영하고, `order_submissions + operator-dashboard + validation + checklist`를 묶어 pruning review reopen 여부를 판단하는 helper로 문서화했다.
- `/Users/yumin/Documents/trading/docs/AUTO_TRADING_TRANSITION_CHECKLIST.md`, `/Users/yumin/Documents/trading/docs/CHECKLIST.md`, `/Users/yumin/Documents/trading/docs/PLAN.md`를 `Iteration #120` 기준으로 동기화했다.

### 왜 그렇게 판단했는가
- 지금 단계의 병목은 새 기능이 아니라 운영 전환의 반복 가능성이다.
- live 전환 전 preflight와 post-live pruning review는 사람마다 다르게 수행하면 의미가 약해지므로, helper와 보고서 경로를 living docs에 고정하는 편이 맞다.

### 최신 검증 스냅샷
- 코드 변경 없음. 문서/기준선 정렬만 수행했다.
- 직전 helper 검증 상태 유지:
  - `./.venv/bin/python -m py_compile scripts/run_micro_live_preflight.py scripts/run_post_live_pruning_review.py`
  - `./.venv/bin/python scripts/run_micro_live_preflight.py --symbol BTCUSDC --days 7 --no-write-report`
  - `./.venv/bin/python scripts/run_post_live_pruning_review.py --symbol BTCUSDC --days 7 --no-write-report`
- 최근 생성 리포트:
  - `/Users/yumin/Documents/trading/reports/operations/micro_live_preflight/micro_live_preflight_BTCUSDC_20260309T051523Z.md`
  - `/Users/yumin/Documents/trading/reports/operations/pruning_reviews/post_live_pruning_review_BTCUSDC_20260309T051524Z.md`

## 2026-03-09 Iteration #119
### 무엇을 발견했는가
- operator runtime surface는 이미 `GET /execution/operator-dashboard` JSON으로 충분했지만, 실제 운영에서는 jq 없이 바로 보는 얇은 브라우저 표면이 없어 다시 JSON 해석 단계가 필요했다.
- 체크리스트와 계획서에도 operator UI가 optional hold로 남아 있어, 실제 구현 상태와 living docs 기준선이 어긋나 있었다.

### 무엇을 수정했는가
- `/Users/yumin/Documents/trading/app/services/execution_operator_ui.py`를 추가해 `dashboard + checklist + validation`을 같은 origin에서 읽는 얇은 HTML operator surface를 만들었다.
- `/Users/yumin/Documents/trading/app/api/execution_routes.py`에 `GET /execution/operator-ui`를 추가했다.
- `/Users/yumin/Documents/trading/tests/test_api_smoke.py`에 HTML route smoke를 추가해 `text/html` 응답과 runtime endpoint reference를 고정했다.
- `/Users/yumin/Documents/trading/README.md`, `/Users/yumin/Documents/trading/docs/AUTO_TRADING_TRANSITION_CHECKLIST.md`, `/Users/yumin/Documents/trading/docs/CHECKLIST.md`, `/Users/yumin/Documents/trading/docs/PLAN.md`, `/Users/yumin/Documents/trading/docs/AUTO_TRADING_OPERATING_RUNBOOK.md`, `/Users/yumin/Documents/trading/docs/AUTO_TRADING_LIVE_GO_LIVE_CHECKLIST.md`를 `Iteration #119` 기준으로 동기화했다.

### 왜 그렇게 판단했는가
- 이 단계의 목적은 새 판단이나 새 source-of-truth를 만드는 것이 아니라, 기존 runtime contract를 operator가 더 빨리 읽게 하는 것이다.
- `operator-dashboard`만으로도 기능은 충분하지만, 라이브 운영에서는 `dashboard/checklist/validation`을 같은 화면에서 바로 보는 얇은 표면이 있는 편이 훨씬 실용적이다.

### 최신 검증 스냅샷
- 타깃 회귀 실행 결과: `1 passed` (`./.venv/bin/pytest -q tests/test_api_smoke.py -q`)

## 2026-03-09 Iteration #117
### 무엇을 발견했는가
- execution approval/intent/reconcile/safety 기능은 이미 있었지만, operator가 신규 진입 허용 여부와 blocking reason을 한 번에 보는 runtime surface가 없었다.
- shadow/paper/micro-live 운영 절차와 go-live 판단 기준도 Living 문서에는 흩어져 있었고, 고정된 runbook/checklist 문서가 없었다.

### 무엇을 수정했는가
- `/Users/yumin/Documents/trading/app/services/execution_operator_dashboard.py`, `/Users/yumin/Documents/trading/app/api/execution_routes.py`, `/Users/yumin/Documents/trading/app/schemas/execution.py`를 추가/갱신해 `GET /execution/operator-dashboard`를 열었다.
- `/Users/yumin/Documents/trading/docs/AUTO_TRADING_OPERATING_RUNBOOK.md`를 추가해 pre-flight, candidate review, preview/approve/intent/submit, reconcile, close-only, kill-switch 절차를 고정했다.
- `/Users/yumin/Documents/trading/docs/AUTO_TRADING_LIVE_GO_LIVE_CHECKLIST.md`를 추가해 `SHADOW -> PAPER -> MICRO_LIVE -> LIVE` 승격 조건과 no-go 조건을 고정했다.
- `/Users/yumin/Documents/trading/README.md`, `/Users/yumin/Documents/trading/docs/AUTO_TRADING_TRANSITION_CHECKLIST.md`, `/Users/yumin/Documents/trading/docs/CHECKLIST.md`, `/Users/yumin/Documents/trading/docs/PLAN.md`를 `Iteration #117` 기준으로 동기화했다.

### 왜 그렇게 판단했는가
- submit path만 있어서는 operator가 실제 운영 중 무엇이 막고 있는지 빠르게 판단할 수 없다. approval/intent/order/position/reconcile/safety를 한 화면으로 묶은 runtime surface가 필요하다.
- 자동매매 전환은 기능보다 운영 절차가 먼저 고정돼야 한다. runbook과 go-live checklist가 없으면 shadow/paper/micro-live 전환이 사람마다 달라진다.

### 최신 검증 스냅샷
- 타깃 회귀 실행 결과: `2 passed` (`./.venv/bin/pytest -q tests/test_execution_operator_dashboard.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `213 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)

## 2026-03-09 Iteration #118
### 무엇을 발견했는가
- incident drill의 `reconcile` 시나리오에서 `OrderSubmission.submitted_at`가 naive datetime이면 aware UTC `now`와 직접 비교되어 runtime `TypeError`가 발생했다.
- incident drill playbook/script는 이미 있었지만, living docs와 README 기준선에는 아직 완료 항목으로 반영되지 않았다.

### 무엇을 수정했는가
- `/Users/yumin/Documents/trading/app/services/execution_reconciliation.py`에서 `latest_submission_ts`를 `_utc(...)`로 정규화하도록 수정했다.
- `/Users/yumin/Documents/trading/tests/test_execution_transition.py`에 naive `submitted_at` 기반 `FILL_EVENT_GAP` 회귀 테스트를 추가했다.
- `./.venv/bin/python scripts/run_execution_incident_drill.py --symbol BTCUSDC --scenario dashboard --scenario reconcile --no-write-report`를 재실행해 runtime drill이 실제로 통과하는 것을 확인했다.
- `/Users/yumin/Documents/trading/README.md`, `/Users/yumin/Documents/trading/docs/AUTO_TRADING_TRANSITION_CHECKLIST.md`, `/Users/yumin/Documents/trading/docs/CHECKLIST.md`, `/Users/yumin/Documents/trading/docs/PLAN.md`를 `Iteration #118` 기준으로 동기화하고 incident drill을 완료 항목으로 승격했다.

### 왜 그렇게 판단했는가
- incident drill은 optional 문서가 아니라 live 운영 직전 복원력 검증 경로다. reconcile 시나리오가 여기서 깨지면 playbook 자체의 신뢰가 무너진다.
- 이 버그는 timestamp timezone 형태에 따라 재현되는 비교 문제라서, helper 정규화와 회귀 테스트로 잠그는 것이 가장 직접적이다.

### 최신 검증 스냅샷
- 타깃 회귀 실행 결과: `14 passed` (`./.venv/bin/pytest -q tests/test_execution_transition.py tests/test_api_smoke.py`)
- incident drill runtime 확인: 성공 (`./.venv/bin/python scripts/run_execution_incident_drill.py --symbol BTCUSDC --scenario dashboard --scenario reconcile --no-write-report`)
- 전체 테스트 실행 결과: `214 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)

## 2026-03-09 Iteration #116
### 무엇을 발견했는가
- `Auto Trading Phase 1D`는 이미 동작하고 있었지만, `order_intents` 응답이 approval/deployment/playbook 근거를 nested snapshot 안에만 넣고 있어서 운영/API 소비 계층에서 다시 파싱해야 했다.
- duplicate thesis도 runtime active-plan 관점이 먼저라서, 실제 execution-layer에서 이미 열린 intent/submission이 있는 경우를 더 직접적으로 막지 못했다.

### 무엇을 수정했는가
- `/Users/yumin/Documents/trading/app/services/order_intents.py`에 execution-layer duplicate thesis 판정을 보강했다. 동일 `thesis_fingerprint` 기준으로 열린 `order_intents + order_submissions`를 우선 확인하고, 동일 symbol 또는 동일 `thesis_primary_symbol` 범위에서 열린 intent/submission이 있으면 `SKIP_DUPLICATE`로 처리하도록 바꿨다. runtime active-plan dedupe는 fallback으로만 남겼다.
- `/Users/yumin/Documents/trading/app/services/strategy_engine.py`, `/Users/yumin/Documents/trading/app/schemas/execution.py`를 갱신해 `POST /execution/order-intents` 응답이 `allowed_execution_mode`, `deployment_*`, `playbook_*`, `source_of_truth_hint=execution_approval_snapshot`를 top-level로 직접 노출하게 했다.
- `/Users/yumin/Documents/trading/docs/AUTO_TRADING_TRANSITION_CHECKLIST.md`, `/Users/yumin/Documents/trading/docs/CHECKLIST.md`, `/Users/yumin/Documents/trading/docs/PLAN.md`를 `Iteration #116` 기준으로 동기화했다.

### 왜 그렇게 판단했는가
- 자동매매 전환에서 duplicate thesis는 scanner 설명용 dedupe보다 execution 직전의 열린 intent/submission 충돌을 먼저 봐야 실제 submit 중복을 안정적으로 막을 수 있다.
- `order_intents`는 approval 이후 submit 직전 의사결정 ledger이므로, nested snapshot만 남기면 운영/API 소비 계층이 같은 계약을 반복 파싱하게 된다. top-level flattening이 있어야 replay/debug 가치가 높아진다.

### 최신 검증 스냅샷
- 타깃 회귀 실행 결과: `24 passed` (`./.venv/bin/pytest -q tests/test_execution_transition.py tests/test_auto_trading_transition_phase1.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `212 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)

## 2026-03-09 Iteration #115
### 무엇을 발견했는가
- Phase 1B/1C execution preview/approval semantics는 이미 활성화됐지만, 상위 문서와 route import가 아직 provisional 단계 표현과 중복 schema 경로를 일부 유지하고 있었다.
- 특히 `app/api/routes.py`는 `app.schemas.api`와 `app.schemas.execution`의 동명 타입을 함께 import해서, preview/approve route contract가 선언상으로는 불명확한 상태였다.

### 무엇을 수정했는가
- `/Users/yumin/Documents/trading/app/api/routes.py`에서 `POST /execution/plans/preview`, `POST /execution/approve-plan`의 duplicate route 정의를 제거하고 Phase 1 API contract 경로를 단일화했다.
- `/Users/yumin/Documents/trading/app/schemas/api.py`에 approval reason `blocking` 필드와 `rollout_policy` payload를 추가해 실제 approval service 반환값과 schema 선언을 일치시켰다.
- `/Users/yumin/Documents/trading/docs/CHECKLIST.md`, `/Users/yumin/Documents/trading/docs/PLAN.md`, `/Users/yumin/Documents/trading/docs/TRADINGVIEW_PINE_MIRROR_GUIDE.md`를 Phase 1C 활성화 상태에 맞춰 갱신했다.

### 왜 그렇게 판단했는가
- active backlog는 `AUTO_TRADING_TRANSITION_CHECKLIST.md` 하나로 관리하더라도, 상위 문서와 실제 route contract가 현재 구현과 충돌하면 다음 phase에서 다시 잘못된 기준선을 불러온다.
- preview/approve endpoint는 이미 real payload를 반환하므로, schema 경로와 문서도 그 사실을 직접 반영해야 유지보수와 OpenAPI가 일관된다.

## 2026-03-09 Iteration #114
### 무엇을 발견했는가
- PR1 route skeleton을 너무 빨리 최종 approval/intent shape처럼 열면, route 존재 자체가 approval 활성화로 오해될 수 있다.
- 특히 이 저장소는 deployment/playbook 언어가 이미 강해서, mock `APPROVED_*`나 fake `submit_decision`이 들어가면 프론트와 운영 계층이 잘못된 안정감을 가질 위험이 있다.

### 무엇을 수정했는가
- `/Users/yumin/Documents/trading/docs/AUTO_TRADING_TRANSITION_CHECKLIST.md`에 PR1 execution route skeleton 원칙을 추가했다.
- `POST /execution/plans/preview`, `POST /execution/approve-plan`, `POST /execution/order-intents`는 PR1에서 provisional wrapper만 반환하도록 체크리스트를 수정했다.
- `implementation_status`, `source_of_truth_hint`, `submit_supported`를 PR1 공통 metadata로 고정하고, mock approval/intent semantic field를 금지했다.
- `/Users/yumin/Documents/trading/docs/PLAN.md`와 `/Users/yumin/Documents/trading/docs/CHECKLIST.md`에도 같은 원칙을 반영했다.

### 왜 그렇게 판단했는가
- PR1의 목적은 approval 시스템을 흉내 내는 것이 아니라 타입/설정/HTTP surface를 정직하게 고정하는 것이다.
- provisional wrapper를 쓰면 route shape는 먼저 열 수 있고, approval semantics는 이후 PR에서 안전하게 활성화할 수 있다.

## 2026-03-09 Iteration #113
### 무엇을 발견했는가
- 기존 체크리스트는 active backlog를 한 줄 수준으로만 관리해서, Auto Trading 전환처럼 계약과 구현 순서를 강하게 고정해야 하는 작업에는 부족했다.
- 특히 `allowed_execution_mode`, stale/dedupe 정의, intent snapshot 범위, Phase 1 acceptance criteria가 문서상으로는 충분히 못 박혀 있지 않았다.

### 무엇을 수정했는가
- `/Users/yumin/Documents/trading/docs/AUTO_TRADING_TRANSITION_CHECKLIST.md`를 상세 실행 체크리스트 source-of-truth로 추가했다.
- 메인 `/Users/yumin/Documents/trading/docs/CHECKLIST.md`는 기준선/다음 포커스/상세 체크리스트 포인터 중심으로 재정리했다.
- `/Users/yumin/Documents/trading/docs/CONTEXT_NOTE.md`에 앞으로도 `목적 / 구현 방식 / 완료 기준 / 검증` 형식으로 체크리스트를 유지한다는 규칙을 추가했다.
- Auto Trading Phase 1에 대해 mode cap, stale/dedupe 정의, intent snapshot, acceptance criteria, 권장 PR 순서를 상세 체크리스트에 반영했다.
- `/Users/yumin/Documents/trading/docs/PLAN.md`에도 같은 착수 원칙을 추가했다.

### 왜 그렇게 판단했는가
- 이 단계에서 중요한 건 코드를 빨리 쓰는 것보다 approval/intent 중심의 실행 계약을 먼저 고정하는 것이다.
- 문서가 구체적이지 않으면 구현 순서가 다시 커지고, 기존 runtime contract를 깨는 방향으로 쉽게 미끄러진다.

## 2026-03-04 Iteration #1
### 무엇을 발견했는가
- 기존 `scoring/metrics` 파일과 신규 엔진 간 인터페이스 충돌
- sqlite timezone naive/aware 혼합 오류
- 계획 필터에서 TP1 보험성 목표까지 최소 RR로 강제하던 부정합

### 무엇을 수정했는가
- `risk_gate/scanner/strategy_engine` 통합 API 정리
- timezone 정규화(만료/정렬)
- rr_min 정의를 TP2/TP3 중심으로 조정
- 테스트/스모크 보강 후 통과

### 왜 그렇게 판단했는가
- 기존 자산 유지 요구를 충족하면서 회귀를 막기 위해 양방향 호환이 필요
- 시간대 오류는 운영 중 치명적 장애 포인트
- TP1은 보험성 익절이므로 활성화 필터 기준으로 부적절

## 2026-03-04 Iteration #2
### 무엇을 발견했는가
- 실전 운영에 필요한 자동화(유니버스 sync/outbox 상태/워커)가 부족
- 이벤트 발행의 재처리 상태를 외부에서 확인하기 어려움

### 무엇을 수정했는가
- `/internal/binance/sync-universe`, `/internal/events/outbox/status` 추가
- `EventOutboxRepository.status_counts`, `EventBus.status_snapshot` 추가
- `scripts/run_worker.py` once/loop 모드 구현 및 실행 경로(import) 수정

### 왜 그렇게 판단했는가
- 데이터/이벤트 파이프라인은 수동 실행보다 자동 워커가 필수
- outbox 상태 가시성 없이는 장애 탐지/복구 판단이 어려움
- 운영 스크립트는 현장 실행성이 가장 중요

## 2026-03-04 Iteration #3
### 무엇을 발견했는가
- 지속 문서화/체크리스트 관리 파일이 저장소에 부재

### 무엇을 수정했는가
- `docs/PLAN.md`, `docs/CONTEXT_NOTE.md`, `docs/CHECKLIST.md`, `docs/SELF_CHECK_LOG.md` 생성
- 완료/미완료 작업을 체크리스트에 반영하고 다음 단일 작업 지정

### 왜 그렇게 판단했는가
- 요청하신 운영 규칙(선 계획/순차 실행/셀프체크)을 지속적으로 지키려면
  대화가 아니라 저장소 내 Living 문서가 기준점이 되어야 함

## 2026-03-04 Iteration #4
### 무엇을 발견했는가
- 전략 성능 관련 핵심 업그레이드(레짐 분리/동적 가중치/자동 비활성화)가 코드에는 반영됐지만 운영 문서에는 충분히 반영되지 않음
- 체크리스트에 테스트 수치와 실제 구현 상태(WS/워커 병렬/ready 외부체크)가 최신 코드와 불일치

### 무엇을 수정했는가
- `PlanGenerator`에 레짐 프로파일(`trend/range/shock`) 기반 임계값/가중치 적용
- 학습 통계에 `ev_r`를 추가하고 음수 EV 셋업 자동 비활성화 규칙 적용
- `ContextSnapshot`에 `regime_label` 추가
- 관련 테스트를 추가/보강하여 전체 테스트 통과 확인(16 passed)

### 왜 그렇게 판단했는가
- 신호 정확도보다 \"나쁜 구간에서 안 하는 능력\"이 장기 성능에 더 큰 영향을 주므로, 레짐·품질·리스크를 결합한 차단 정책이 필수
- 학습 신호를 진입 품질에 직접 연결하지 않으면 자동 개선 루프가 약해짐

## 2026-03-04 Iteration #5
### 무엇을 발견했는가
- Living 문서가 최신 코드 상태를 충분히 설명하지 못해 운영/튜닝 시 판단 기준이 분산됨
- README의 설치 명령이 일부 셸에서 글로빙 이슈를 유발할 수 있음

### 무엇을 수정했는가
- `README.md` 문서 목록에 전략 운영 매뉴얼 추가, 개발 의존성 설치 명령 보정
- `docs/PLAN.md`를 최신 구현/우선순위 기준으로 전면 갱신
- `docs/CONTEXT_NOTE.md`에 의사결정 우선순위/신호 남발 방지 원칙을 명문화
- `docs/CHECKLIST.md`를 코드 기준으로 재정렬하고 완료/미완료 상태 업데이트
- `docs/STRATEGY_OPERATING_MANUAL.md` 신규 작성(전략 운용 기준/튜닝 절차 문서화)

### 왜 그렇게 판단했는가
- 운영 품질은 코드 자체뿐 아니라 \"같은 판단 기준\"을 팀이 공유하는 문서에서 결정됨
- 문서와 코드가 동기화되어야 회귀/과최적화/운영 실수가 줄어듦

## 2026-03-04 Iteration #6
### 무엇을 발견했는가
- 체크리스트 우선순위였던 Binance WS 상시 수집 루프가 실제 엔진 ingest 경로에는 아직 연결되지 않음
- SQLite에서 읽힌 naive timestamp와 aware timestamp 비교로 WS ingest가 반복 실패할 수 있음

### 무엇을 수정했는가
- `StrategyEngine.stream_binance_klines` 추가(멀티 interval, 재연결 백오프, max_messages 종료 지원)
- `scripts/run_worker.py`에 `--ws-stream`, `--ws-symbols`, `--ws-intervals`, `--ws-max-messages` 옵션 추가
- `DataQualityGate`에 UTC 정규화 로직 추가(naive/aware 비교 안정화)
- WS ingest/품질 게이트 회귀 테스트 추가 후 전체 테스트 통과(20 passed)
- 문서(README/PLAN/CHECKLIST) 상태를 최신 구현으로 갱신

### 왜 그렇게 판단했는가
- 실시간 전략 운영은 REST 백필만으로는 신호 지연이 커서, WS ingest 상시 연결이 필수
- timestamp 비교 오류는 실시간 파이프라인에서 가장 빈번한 장애 유형이라 선제 차단이 필요
- 기능 추가와 함께 테스트/문서를 동기화해야 운영 신뢰성이 유지됨

## 2026-03-04 Iteration #7
### 무엇을 발견했는가
- 유니버스 동기화 워커가 심볼을 순차 처리해 top30 기준 처리 시간이 길어질 수 있음
- 동시성 제한이 없으면 과도한 API 호출/DB 부하를 제어하기 어려움

### 무엇을 수정했는가
- `StrategyEngine.sync_universe_from_binance`에 심볼 병렬 처리와 동시성 상한(`symbol_concurrency`) 추가
- 워커 CLI/API에 동시성 옵션을 노출(`--symbol-concurrency`, `symbol_concurrency` query)
- 병렬 경로 테스트를 추가하고 전체 테스트 통과(21 passed)
- CHECKLIST/PLAN/README/운영 매뉴얼을 최신 상태로 갱신

### 왜 그렇게 판단했는가
- 병렬화는 실시간 운용에서 처리 지연을 줄이는 가장 직접적인 성능 개선 수단
- 동시성 상한은 성능과 안정성(API rate/DB lock) 사이 균형을 맞추기 위한 필수 장치
- 코드/테스트/문서를 함께 갱신해야 운영자가 실제로 안전하게 기능을 활용할 수 있음

## 2026-03-04 Iteration #8
### 무엇을 발견했는가
- `POST /validation/report`의 `refresh=false`가 실제로는 무시되고 강제로 재계산되어 파라미터 의미가 불명확했음
- `get_engine` 경로에서 요청마다 `init_db()`를 반복 호출해 불필요한 오버헤드/혼선을 만들 여지가 있었음

### 무엇을 수정했는가
- `refresh=false` 요청 시 명시적 400 응답으로 계약을 명확화(`refresh=true`만 지원)
- DB 초기화 로직에 1회 초기화 가드(락+플래그) 추가
- API 스모크 테스트에 `refresh=false -> 400` 검증 케이스 추가
- 전체 테스트 재검증 완료(21 passed)

### 왜 그렇게 판단했는가
- 파라미터는 문서/코드/동작이 일치해야 운영 실수를 줄일 수 있음
- 초기화는 멱등적으로 1회만 수행하는 것이 성능/안정성 모두에 유리함
- 테스트로 계약을 고정해야 이후 회귀를 막을 수 있음

### 이번에 의도적으로 보류한 변경
- 외부 의존성(거래소/redis/kafka)을 `/health/ready` 기본 체크에 바로 넣는 변경은 보류
- 이유: 로컬 개발/테스트 환경에서 불필요한 degraded를 유발하고, 운영/개발 환경 분리 정책이 먼저 필요함
- 상태 업데이트: 이 보류 항목은 Iteration #9에서 해제되어 `db/binance_rest/event_backend` 체크로 구현 완료

## 2026-03-04 Iteration #9
### 무엇을 발견했는가
- 체크리스트 우선순위 1~3(`리포트 FAIL/WARN 자동 알림`, `/health/ready` 외부 의존성, 통합/장애 테스트)가 미완료 상태였음
- 검증 리포트가 WARN/FAIL이어도 운영자 알림 없이 파일 생성만 되어 즉시 대응이 어려웠음

### 무엇을 수정했는가
- `StrategyEngine.recompute_learning`에 WARN/FAIL 자동 알림 로직 추가(`validation_warn` 레코드 + `validation.warn/fail` 이벤트 발행)
- 알림 쿨다운(`validation_alert_cooldown_seconds`)과 시스템 채널(`validation_alert_channel`) 설정 추가
- `/health/ready`를 `db/binance_rest/event_backend` 외부 의존성 점검으로 확장
- 장애 시나리오 테스트 추가(이벤트 퍼블리시 실패 복구, WS 재연결)
- Binance 실연결 통합 테스트(옵트인: `RUN_BINANCE_LIVE=1`) 추가
- 문서(README/PLAN/CHECKLIST/CONTEXT/MANUAL)와 체크리스트 상태를 최신 코드 기준으로 갱신

### 왜 그렇게 판단했는가
- 검증 결과는 생성 자체보다 \"운영자에게 즉시 도달\"하는 알림 경로가 있어야 실전 가치가 생김
- readiness는 DB만 보는 수준으로는 운영 위험을 조기 감지하기 어렵고, 외부 의존성까지 포함해야 함
- 장애/실연결 테스트는 회귀 방지뿐 아니라 실제 운영 전 리스크를 정량적으로 낮추는 최소 안전장치임

## 2026-03-04 Iteration #10
### 무엇을 발견했는가
- 기존 전략은 컨플루언스/EV 게이트는 강하지만, 실행 직전 2차 품질 판정(meta filter)이 없어
  약한 시그널이 통과할 여지가 있었음
- OB/FVG/유동성/트렌드 프록시의 실제 기여도를 정량화하는 자동 루프가 부재했음

### 무엇을 수정했는가
- `PlanGenerator`에 메타 필터(2차 실행 게이트) 추가(`meta_score`, `meta_threshold`, `meta_reason`)
- 피처 중요도(Ablation) 서비스 추가 및 엔진 연동
- `GET /validation/feature-importance` API 추가
- 검증 리포트에 Feature Importance 섹션 추가
- 관련 테스트 추가/보강 후 전체 테스트 통과(31 passed, 1 skipped)
- PLAN/CHECKLIST/README/CONTEXT/매뉴얼 문서 동기화

### 왜 그렇게 판단했는가
- 장기 성능은 “진입 능력”보다 “저품질 신호 차단 능력”에 크게 좌우됨
- 피처 중요도를 수치화해야 감(heuristic)이 아닌 데이터 기반으로 가중치를 조정할 수 있음
- 코드/테스트/문서를 동시에 맞춰야 운영 중 오해와 회귀를 줄일 수 있음

### 최신 검증 스냅샷
- 기본 테스트 실행 결과: `31 passed, 1 skipped` (`tests/test_binance_live_integration.py`는 `RUN_BINANCE_LIVE=1`일 때만 실행)

## 2026-03-04 Iteration #11
### 무엇을 발견했는가
- Iteration #8 변경사항(계약 명확화/DB init guard)이 최신 기준으로 오해될 수 있었고, 기준선 표기가 필요했음
- 최신 상태는 Iteration #9에서 `/health/ready` 외부 의존성 체크와 테스트 확장이 반영된 상태였음

### 무엇을 수정했는가
- 코드 재검증으로 핵심 상태를 확인:
  - `refresh=false -> 400` 유지(`app/api/routes.py`)
  - `init_db()` 1회 가드 유지(`app/db/session.py`)
  - `/health/ready` 외부 의존성 체크 유지(`app/services/health_check.py`, `app/api/routes.py`)
- 문서에 현재 기준선(Iteration #9) 및 최신 테스트 스냅샷(`31 passed, 1 skipped`)을 명시

### 왜 그렇게 판단했는가
- 전략 운영 문서는 “현재 기준선”이 분명해야 리뷰/운영 의사결정에서 혼선을 줄일 수 있음
- 과거 이터레이션의 변경 내역은 유지하되, 최신 기준과 검증 수치를 함께 명시해야 실무 추적성이 높아짐

## 2026-03-04 Iteration #13
### 무엇을 발견했는가
- `Timescale 실환경 실행 검증`은 스크립트는 준비되어 있었지만, 실제 컨테이너 실행 기반 PASS 증빙이 필요했음
- 다음 미완료 항목이던 `파라미터 변경 이력 자동 CHANGELOG`는 엔진 경로에 자동 생성 루프가 아직 없었음

### 무엇을 수정했는가
- Docker Timescale(`timescale/timescaledb:latest-pg14`)에서 `verify_timescale_runtime.py` 실실행 후 PASS 확인
  - 산출물: `reports/timescale/validation_docker_e2e.md`
- `ParameterChangelogService`를 추가해 설정 스냅샷 비교 기반 변경 이력 자동 생성 구현
  - 경로: `reports/params/PARAM_CHANGELOG.md`, `reports/params/snapshots/latest.json`
  - `POST /validation/report` 실행 시 자동 반영(`parameter_changelog` 응답 필드 추가)
- 관련 테스트 추가/보강:
  - `tests/test_parameter_changelog.py` 신규
  - `tests/test_api_smoke.py` 응답 필드 검증 확장
- PLAN/CHECKLIST/README/CONTEXT/매뉴얼 문서를 최신 상태로 동기화

### 왜 그렇게 판단했는가
- 체크리스트 완료 기준은 “구현 존재”가 아니라 “재현 가능한 실실행 PASS 증빙”까지 포함해야 함
- 파라미터 이력은 운영 중 가장 자주 깨지는 추적 포인트라 자동화하지 않으면 회귀 분석이 어려움
- 검증 API와 문서에 동일 계약을 반영해야 운영자가 실제로 기능을 사용할 수 있음

### 최신 검증 스냅샷
- Timescale runtime validation: `PASS` (`reports/timescale/validation_docker_e2e.md`)
- 기본 테스트 실행 결과: `33 passed, 1 skipped`

## 2026-03-04 Iteration #12 (Earlier)
### 무엇을 발견했는가
- `Timescale 실환경 실행 검증`이 체크리스트 미완료 상태였고, 기존 마이그레이션은 실제 Timescale 규칙과 충돌 가능성이 있었음
- 실측 결과, 하이퍼테이블 전환 시 PK가 파티션 시간 컬럼을 포함하지 않아 마이그레이션이 실패함
- `pip install -e '.[integration]'`가 패키지 자동 발견(`reports`) 문제로 실패해 온보딩/검증 자동화에 장애가 있었음

### 무엇을 수정했는가
- Timescale 마이그레이션 보강:
  - `candles_pkey -> (id, ts)`, `zone_outcomes_pkey -> (id, entry_ts)`로 재정의 후 하이퍼테이블 전환
- 실환경 검증 자동화:
  - `scripts/verify_timescale_runtime.py` 추가
  - 절차: `Base.create_all -> SQL migrations -> seed write/read -> compression policy job 실행 -> 하이퍼테이블/압축/청크 검증`
  - PASS 리포트 생성: `reports/timescale/validation_20260304_141822.md`
- 패키징 보강:
  - `pyproject.toml`에 `setuptools` 패키지 탐색 범위(`app*`) 고정
  - `integration` extras에 `psycopg[binary]` 추가
- 문서/체크리스트 갱신:
  - README에 Timescale 검증 실행 커맨드 추가
  - CHECKLIST에서 `Timescale 실환경 실행 검증` 완료 처리 및 다음 단일 작업 갱신

### 왜 그렇게 판단했는가
- Timescale 전환 실패는 운영 배포 차단 이슈이므로 SQL 레벨 호환성을 먼저 고정해야 함
- 검증은 수동 메모가 아니라 재실행 가능한 스크립트와 리포트 산출물로 남겨야 회귀를 막을 수 있음
- 설치/온보딩 명령 실패는 개발 속도와 검증 재현성을 직접 떨어뜨리므로 즉시 수정이 필요함

### 최신 검증 스냅샷
- Timescale runtime validation: `PASS`
- 기본 테스트 실행 결과: `31 passed, 1 skipped`

## 2026-03-04 Iteration #14
### 무엇을 발견했는가
- `파라미터 변경 이력 자동 CHANGELOG`는 엔진 연동은 있었지만, 회귀 방지 테스트와 수동 실행 경로가 부족했음
- 연속 실행 시 snapshot 파일명이 동일 초 단위로 충돌해 증적이 덮어써질 수 있었음

### 무엇을 수정했는가
- `ParameterChangelogService` 안정화:
  - 동일 초 snapshot 충돌 시 마이크로초 suffix를 붙여 파일 덮어쓰기를 방지
- 테스트 보강:
  - `tests/test_parameter_changelog.py` 신규 추가(초기화/무변경/변경감지 검증)
  - `tests/test_validation_alerts.py`에 `parameter_changelog` 응답 검증 추가
- 운영 실행 경로 추가:
  - `scripts/generate_parameter_changelog.py` 신규 추가(수동 트리거)
- 문서 동기화:
  - README/운영 매뉴얼에 changelog 수동 생성 커맨드 반영
  - CHECKLIST에서 `파라미터 변경 이력 자동 CHANGELOG` 완료 처리

### 왜 그렇게 판단했는가
- 자동 생성 기능은 “코드 존재”보다 “테스트로 계약 고정 + 운영자가 즉시 실행 가능한 커맨드”가 있어야 실전에서 유지됨
- 변경 이력 파일이 덮어써지면 튜닝 회귀 분석이 불가능해지므로 snapshot 보존성이 핵심임
- 문서/체크리스트와 코드가 함께 업데이트되어야 팀 운영 기준이 흔들리지 않음

### 최신 검증 스냅샷
- 기본 테스트 실행 결과: `33 passed, 1 skipped` (`RUN_BINANCE_LIVE=1` 실연결 테스트는 opt-in)

## 2026-03-04 Iteration #15
### 무엇을 발견했는가
- 체크리스트의 다음 단일 포커스였던 `운영 알림 채널 연동(telegram/discord/push) 실배선`이 코드상 미완료 상태였음
- 기존 `validation WARN/FAIL` 알림은 DB/이벤트 기록만 수행하고, 외부 채널 전달 결과를 추적할 수 없었음
- 운영자가 실채널 연결을 즉시 검증할 API가 없어 배포 전 점검이 불편했음

### 무엇을 수정했는가
- `NotificationDispatcher` 서비스 신규 추가
  - 채널: `telegram`, `discord`, `push`, `system`
  - 미설정 시 안전 스킵(`*_not_configured`) 처리
  - 전송 결과(`delivered/skipped/reason/status_code`) 표준화
- `StrategyEngine` 연동:
  - `recompute_learning` WARN/FAIL 알림에서 외부 채널 전송 수행
  - `validation_alert.delivery` 및 alert payload에 delivery 결과 저장
  - 운영 점검용 `send_test_alert` 추가
- API 확장:
  - `POST /alerts/test` 추가
  - `POST /alerts/subscribe` 응답 모델 고정
- 테스트 보강:
  - `tests/test_notification_dispatcher.py` 신규
  - `tests/test_validation_alerts.py` 외부 채널 전달/저장 검증 추가
  - `tests/test_api_smoke.py`에 `/alerts/test` 스모크 추가
- 문서 동기화:
  - README/PLAN/CONTEXT/CHECKLIST/운영 매뉴얼 갱신

### 왜 그렇게 판단했는가
- 실전 운영에서는 “알림 생성”보다 “알림 도달”이 중요하므로 채널 실배선과 전달 결과 추적이 필수임
- 채널 설정 누락은 흔한 운영 실수이므로 실패보다 안전 스킵 + 명확한 사유 반환이 운영 안정성에 유리함
- 배포 전 점검 API가 있어야 운영자가 경로 이상을 빠르게 분리 진단할 수 있음

### 최신 검증 스냅샷
- 기본 테스트 실행 결과: `38 passed, 1 skipped` (`RUN_BINANCE_LIVE=1` 실연결 테스트는 opt-in)

## 2026-03-04 Iteration #16
### 무엇을 발견했는가
- `validation_alert_channel=system` 경로가 기존에는 외부 전송을 수행하지 않아, 운영 기본값에서 실배선 효과가 제한됐음
- `system` 팬아웃 동작(설정된 telegram/discord/push로 전파)을 검증하는 테스트가 부족했음
- 중간 작업으로 들어간 미사용 설정/서비스가 유지보수 혼선을 만들 수 있었음

### 무엇을 수정했는가
- `NotificationDispatcher` 보강:
  - `system` 채널을 설정된 라우트로 fanout 전송하도록 변경
  - fanout 집계 결과(`routes`, `results`, `system_delivered_all/system_partial_delivery/system_no_routes_configured`) 반환
- 테스트 보강:
  - `tests/test_notification_dispatcher.py`에서 system no-route/fanout 시나리오 검증 추가
  - `tests/test_validation_alerts.py`의 기본 system 사유값을 최신 동작으로 갱신
- 구조 정리:
  - 미사용 `notification_*` 설정 및 미사용 서비스 파일 제거
- 문서 동기화:
  - README/PLAN/CONTEXT/운영 매뉴얼에 system fanout 동작 반영

### 왜 그렇게 판단했는가
- 운영 기본 채널이 `system`인 환경에서 실제 전달 경로가 비어 있으면 알림 신뢰성이 낮아짐
- fanout은 채널 단일 장애에 대한 복원력을 높이고, 구조화된 결과는 장애 분류를 빠르게 함
- 미사용 코드/설정 제거는 이후 회귀와 오판 가능성을 줄이는 기본 위생 작업임

### 최신 검증 스냅샷
- 기본 테스트 실행 결과: `38 passed, 1 skipped` (`RUN_BINANCE_LIVE=1` 실연결 테스트는 opt-in)

## 2026-03-04 Iteration #17
### 무엇을 발견했는가
- 체크리스트 단일 포커스였던 `Timescale 부하/장기보관 시나리오 검증`의 실행 증빙이 아직 없었음
- 대량 chunk 환경에서 Timescale `run_job()` compression policy가 부분 실패 예외를 던질 수 있었음
- `drop_chunks`는 현재 함수 시그니처(`relation`, `older_than`)를 맞추지 않으면 실패함

### 무엇을 수정했는가
- `scripts/benchmark_timescale_load_retention.py` 신규 추가
  - 대량 입력 생성(12 symbols, 150 days, 5m/15m + outcomes)
  - 쿼리 지연 avg/p95 측정(`recent_300bars`, scanner 7/30/90d, outcome aggregation)
  - 정책 실행 시간 측정(`compression job`, `manual_compress fallback`, `drop_chunks`)
  - 체크/용량/행수 변화를 포함한 Markdown 리포트 자동 생성
- 호환성 보강
  - 하이퍼테이블 용량 조회를 `hypertable_detailed_size` 기반으로 정합화
  - `drop_chunks(relation => ..., older_than => ...)` 호출로 수정
  - policy/drop 실행 예외를 캡처하여 `ok/error`로 리포트에 반영
- Docker 실측 PASS 확보
  - 산출물: `reports/timescale/load_retention_docker_e2e.md`
- 문서 동기화
  - README/PLAN/CHECKLIST/CONTEXT/운영 매뉴얼 갱신

### 왜 그렇게 판단했는가
- 인프라 최적화는 구현 여부보다 실측 수치와 재현 가능한 리포트가 핵심임
- 정책 잡 실패 가능성을 리포트로 노출하고 fallback을 갖춰야 운영 복원력이 올라감
- 체크리스트 완료는 코드 변경만이 아니라 PASS 아티팩트까지 포함되어야 함

### 최신 검증 스냅샷
- Timescale load/retention benchmark: `PASS` (`reports/timescale/load_retention_docker_e2e.md`)
- 기본 테스트 실행 결과: `38 passed, 1 skipped` (`RUN_BINANCE_LIVE=1` 실연결 테스트는 opt-in)

## 2026-03-04 Iteration #18
### 무엇을 발견했는가
- 대량 `executemany` 경로에서 PostgreSQL 연결이 종료될 수 있어, Timescale 벤치마크 실행 안정성이 떨어질 수 있었음
- 기존 벤치마크 스크립트는 임계치 기반 PASS/WARN 판정과 정책 전후 행수/청크 변화 요약이 운영 관점에서 부족했음
- 문서의 Timescale 벤치마크 실행 커맨드가 최신 실측 경로와 일부 불일치했음

### 무엇을 수정했는가
- `scripts/benchmark_timescale_retention.py` 신규 추가
  - 배치 커밋 기반 대용량 적재(5m/15m candles + zone_outcomes)
  - 쿼리 지연(`recent/aggregate/scanner/outcome`) p50/p95/max 측정
  - `policy_compression`/`policy_retention` 실행 시간 측정 및 행수/청크 전후 비교
  - 임계치 기반 `PASS/WARN/FAIL` 판정 + Markdown 리포트 생성
- Docker Timescale 실측 재검증
  - 산출물: `reports/timescale/benchmark_docker_e2e.md`
  - 결과: `PASS` (candles 691,200 rows, outcomes 30,000 rows, retention 삭제 확인)
- 문서 동기화
  - `README.md`, `docs/PLAN.md`, `docs/CHECKLIST.md`, `docs/CONTEXT_NOTE.md`, `docs/STRATEGY_OPERATING_MANUAL.md` 업데이트

### 왜 그렇게 판단했는가
- 인프라 성능 검증은 “동작 여부”보다 “재현 가능한 계측 + 임계치 판정”이 있어야 운영 의사결정에 직접 사용할 수 있음
- 정책 실행 전후의 실제 삭제량/압축량이 확인되어야 장기보관 정책이 의도대로 적용되는지 판단 가능함
- 코드/문서/체크리스트 경로가 일치해야 온보딩과 운영 점검에서 혼선을 줄일 수 있음

### 최신 검증 스냅샷
- Timescale load/retention benchmark: `PASS` (`reports/timescale/benchmark_docker_e2e.md`)
- 기본 테스트 실행 결과: `38 passed, 1 skipped` (`RUN_BINANCE_LIVE=1` 실연결 테스트는 opt-in)

## 2026-03-04 Iteration #19
### 무엇을 발견했는가
- 체크리스트 단일 포커스였던 `포트폴리오 리스크 오버레이(심볼 상관/동시 노출 제한)`가 스캐너 랭킹 경로에 아직 반영되지 않았음
- 기존 스캐너는 EV/신뢰도 중심 정렬만 수행해, 동방향 고상관 후보가 동시에 상위에 노출될 수 있었음
- 기존 노출 상태(ARMED~PARTIAL_EXIT)를 스캐너 노출 제한에 반영하는 저장소 조회 메서드가 없었음

### 무엇을 수정했는가
- `PortfolioRiskOverlayService` 신규 추가
  - 상관도 계산(5m returns) + 고상관 cluster 차단
  - 총 노출/방향 노출 상한 적용
  - 고상관 정도 기반 점수 패널티 적용
- `ScannerService` 연동
  - 스캐너 최종 랭킹에 오버레이 필터 적용
  - 리스크 CLOSED 상태는 기존 동작(상위만 반환) 유지
- `PlanRepository` 확장
  - 기존 노출 상태 조회 `list_exposure_candidates()` 추가
- `StrategyEngine.scanner_top` 연동
  - 기존 노출(symbol, direction) 전달 + 설정 기반 PLANNED 포함 옵션 추가
- 설정 추가(`app/core/config.py`)
  - `portfolio_overlay_*` 파라미터군(활성화, 상관 임계치, 노출 한도, 패널티 계수)
- 테스트 보강
  - `tests/test_portfolio_overlay.py` 신규(고상관 차단/방향 노출 제한/기존 노출 반영)
- 문서 동기화
  - README/PLAN/CHECKLIST/CONTEXT/운영 매뉴얼 업데이트

### 왜 그렇게 판단했는가
- 실전 성능은 단일 셋업 품질뿐 아니라 포트폴리오 차원의 과집중 회피에 크게 좌우됨
- 동시 노출 제한은 고상관 손실 동조화를 줄이는 직접적인 리스크 완화 장치임
- 체크리스트 단일 포커스는 코드/테스트/문서가 동시에 닫혀야 운영 기준으로 사용 가능함

### 최신 검증 스냅샷
- 기본 테스트 실행 결과: `41 passed, 1 skipped` (`RUN_BINANCE_LIVE=1` 실연결 테스트는 opt-in)

## 2026-03-04 Iteration #20
### 무엇을 발견했는가
- 포트폴리오 오버레이 적용 이후에도, 실제 집행 품질(슬리피지/미체결 원인)을 자동으로 추적하는 리포트 경로가 부재했음
- 현재 데이터 구조에서 plan/outcome/candle을 결합하면 실전형 fill-rate와 미체결 원인 분해를 자동화할 수 있었음
- API 레벨에서 실행 품질을 즉시 조회할 엔드포인트가 없어 운영 대시보드 연결성이 낮았음

### 무엇을 수정했는가
- `ExecutionQualityService` 신규 추가
  - 지표: `fill_rate`, `slippage_bps(avg/p50/p95/max)`, `by_entry_model`
  - 미체결 원인 분해: `not_reached_entry`, `touch_no_fill`, `touch_no_confirmation`, `missing_market_data`
  - Markdown 리포트 자동 생성(`reports/execution/quality_<symbol>_<utc>.md`)
- 엔진/API/스크립트 연동
  - 엔진 메서드: `StrategyEngine.execution_quality_report(...)`
  - API: `GET /execution/quality?symbol=...&days=...&write_report=...`
  - 스크립트: `scripts/generate_execution_quality_report.py`
- 저장소/스키마 확장
  - `CandleRepository.list_range(...)` 추가
  - `PlanRepository.list_recent(...)` 추가
  - 응답 스키마에 `ExecutionQualityOut` 추가
- 테스트 보강
  - `tests/test_execution_quality.py` 신규
  - `tests/test_api_smoke.py`에 `/execution/quality` 스모크 추가
- 문서 동기화
  - README/PLAN/CHECKLIST/CONTEXT/운영 매뉴얼 업데이트

### 왜 그렇게 판단했는가
- 전략 성능은 진입 신호 품질과 별개로 집행 품질에 크게 좌우되므로, 자동 계측 리포트가 있어야 튜닝 우선순위를 올바르게 잡을 수 있음
- 미체결 원인을 분해하면 라우팅/조건/유효시간 파라미터 조정 포인트를 빠르게 찾을 수 있음
- API와 스크립트를 함께 제공해야 운영 배치/대시보드/수동 점검 모두에서 재사용 가능함

### 최신 검증 스냅샷
- 기본 테스트 실행 결과: `42 passed, 1 skipped` (`RUN_BINANCE_LIVE=1` 실연결 테스트는 opt-in)

## 2026-03-04 Iteration #21
### 무엇을 발견했는가
- 체크리스트 단일 포커스였던 `알림 채널 장애 격리`가 기존 구현에서는 단건 전송 실패를 즉시 실패로 처리해, 연속 장애 구간에서 동일 채널 재호출이 반복될 수 있었음
- 채널별 재시도/백오프/서킷브레이커가 없어 일시 장애와 지속 장애를 분리 대응하기 어려웠음
- 테스트는 기본 fanout/전송성공만 검증하고, 재시도 및 서킷브레이커 동작 회귀를 고정하지 못하고 있었음

### 무엇을 수정했는가
- `NotificationDispatcher` 보강
  - 채널 전송에 `alert_retry_attempts`, `alert_retry_backoff_seconds` 기반 재시도/백오프 추가
  - 채널별 서킷브레이커 추가(`alert_circuit_breaker_failures`, `alert_circuit_breaker_cooldown_seconds`)
  - 서킷 오픈 시 `reason=circuit_open`으로 즉시 skip 처리
  - 테스트 격리를 위한 `NotificationDispatcher.reset_circuit_state()` 추가
- 설정/추적 보강
  - `app/core/config.py`에 alert retry/circuit 설정 추가
  - `TRACKED_PARAMETER_KEYS`에 alert retry/circuit 설정 반영
- 테스트 보강
  - `tests/test_notification_dispatcher.py`에 재시도 성공 케이스 추가
  - `tests/test_notification_dispatcher.py`에 서킷브레이커 오픈/차단 케이스 추가
- 문서 동기화
  - README/PLAN/CHECKLIST/CONTEXT/운영 매뉴얼 갱신

### 왜 그렇게 판단했는가
- 알림 채널 장애는 전략 판단 오류보다 운영 대응 지연을 크게 만들 수 있어, 전송 경로 자체의 복원력 정책이 필수임
- 재시도는 일시 장애 완화에, 서킷브레이커는 지속 장애 격리에 효과적이며 두 정책을 함께 써야 채널 과부하를 줄일 수 있음
- 코드/설정/테스트/문서를 같이 고정해야 운영자가 실제 장애 시 동일한 판단 기준을 재현할 수 있음

### 최신 검증 스냅샷
- 기본 테스트 실행 결과: `44 passed, 1 skipped` (`RUN_BINANCE_LIVE=1` 실연결 테스트는 opt-in)

## 2026-03-04 Iteration #22
### 무엇을 발견했는가
- 사용자가 요청한 업그레이드 5개 항목(실체결 연동, 중요도 캘리브레이션, 리스크 버짓 v2, 실행 품질 v2, 알림 복원력 v2)이 기존 문서에 분산되어 있어 단일 참조 기획서가 없었음
- PLAN/CHECKLIST/매뉴얼에는 구현 상태는 있었지만, vNext 관점의 승인 기준/순서/DoD가 한 문서로 정리되지 않았음

### 무엇을 수정했는가
- 신규 기획 문서 추가: `docs/UPGRADE_ROADMAP_VNEXT.md`
  - 5개 Epic의 목표/핵심 설계/DoD/추진 순서/승인 조건 문서화
- 연계 문서 동기화
  - `README.md`에 로드맵 문서 링크 추가
  - `docs/PLAN.md`에 vNext 로드맵 섹션 추가
  - `docs/CHECKLIST.md`에 `I. vNext 기획` 섹션 추가(설계 승인 체크 항목)
  - `docs/CONTEXT_NOTE.md`에 로드맵 준수 규칙 추가
  - `docs/STRATEGY_OPERATING_MANUAL.md`에 vNext 착수 규칙 추가

### 왜 그렇게 판단했는가
- 구현 우선순위가 명확해야 “지금 무엇을 왜 하는지”가 흔들리지 않고, 기능 추가가 산발적으로 퍼지는 것을 방지할 수 있음
- Epic 단위 DoD와 승인 조건을 문서에 고정해야 회귀 없이 순차적으로 품질을 올릴 수 있음

### 최신 검증 스냅샷
- 이번 이터레이션은 문서화 작업이며 코드 동작 변경 없음

## 2026-03-04 Iteration #23
### 무엇을 발견했는가
- 체크리스트 단일 포커스였던 `포지션 상태머신 실집행 연동`이 실제 코드에는 enum/문서만 있고, 체결 이벤트 기준의 상태 전이 경로가 없었음
- 기존 엔진은 plan 상태를 `PLANNED/ARMED` 중심으로만 다루고 있어 `ENTERED/PARTIAL_EXIT/CLOSED`를 실체결 기반으로 반영할 방법이 부족했음
- 중복 체결 이벤트 재주입(멱등성) 보장이 없어 실운영 시 상태/집계가 흔들릴 리스크가 있었음

### 무엇을 수정했는가
- 체결 원장 추가
  - `app/db/models.py`: `execution_fills` 테이블 모델 추가(`fill_id`, `stage`, `from_state/to_state`, `state_changed`, 가격/수량/수수료)
  - `app/db/repositories.py`: `ExecutionFillRepository` 추가
- 상태 전이 서비스 추가
  - `app/services/position_state_machine.py` 신규
  - 단방향 전이 규칙 적용: `TRIGGERED -> ENTERED -> PARTIAL_EXIT -> CLOSED`
  - `fill_id` 멱등 처리(중복 재주입 시 상태 불변)
- 엔진/API 연동
  - `app/services/strategy_engine.py`: `ingest_execution_fill(...)` 추가
  - 전이 이벤트 outbox 발행: `entry.triggered`, `trade.closed`
  - `app/api/routes.py`: `POST /internal/execution/fills` 추가(미존재 plan 404, symbol mismatch 400)
  - `app/schemas/api.py`: `ExecutionFillIn/ExecutionFillOut` 추가
- 테스트 보강
  - `tests/test_position_state_machine.py` 신규(정상 전이/멱등/역전이 차단)
  - `tests/test_execution_fill_api.py` 신규(API 상태 전이/404 계약)
- 문서 동기화
  - `README.md`, `docs/PLAN.md`, `docs/CHECKLIST.md`, `docs/CONTEXT_NOTE.md`, `docs/STRATEGY_OPERATING_MANUAL.md` 업데이트

### 왜 그렇게 판단했는가
- 포지션 상태머신은 실체결 이벤트를 기준으로 작동해야 실행 품질/학습 루프의 원본 데이터 정합성이 확보됨
- 체결 이벤트는 네트워크/거래소 재전송이 빈번하므로 `fill_id` 멱등 키가 없으면 상태 오염과 지표 왜곡이 발생하기 쉬움
- 단방향 전이와 API 계약(404/400)을 고정하면 운영/연동 단계에서 오류 원인 분리가 빨라지고 회귀를 줄일 수 있음

### 최신 검증 스냅샷
- 기본 테스트 실행 결과: `48 passed, 1 skipped` (`RUN_BINANCE_LIVE=1` 실연결 테스트는 opt-in)

## 2026-03-07 Iteration #24
### 무엇을 발견했는가
- 기존 `ExecutionQualityService`는 여전히 `zone_outcomes` 기반 추정 매칭이 중심이라, 이미 도입한 `execution_fills` 체결 원장을 실행 품질 지표에 거의 반영하지 못하고 있었음
- 슬리피지 외에 실제 운영에서 필요한 `entry latency`, `fee`, `stage coverage`, `source transparency`가 없어 체결 경로 개선 포인트를 구체적으로 분리하기 어려웠음
- 미체결 원인 분해도 `triggered`까지 왔지만 `entry`가 안 된 케이스를 별도 구분하지 못했음

### 무엇을 수정했는가
- `ExecutionQualityService` 재구성
  - `execution_fills`를 1차 데이터 소스로 사용
  - `zone_outcomes`는 체결 원장이 없는 과거 데이터에만 fallback으로 사용
  - 지표 추가: `fill_sources`, `stage_counts`, `entry_latency_seconds`, `fees`
  - entry model별 `partial_exit_rate`, `closed_rate`, `execution_source_rate` 추가
  - 미체결 사유에 `triggered_no_entry` 추가
- 저장소/엔진 연동
  - `ExecutionFillRepository.list_for_plans(...)` 추가
  - `StrategyEngine`의 execution quality 경로에 `fill_repo` 연동
  - API 스키마에 신규 필드 반영
- 테스트/문서 동기화
  - `tests/test_execution_quality.py` 보강(`execution_fills` 우선 집계 + fallback 공존 검증)
  - `tests/test_api_smoke.py`에 신규 응답 필드 계약 검증 추가
  - README/PLAN/CHECKLIST/CONTEXT/운영 매뉴얼 업데이트

### 왜 그렇게 판단했는가
- 실행 품질 리포트는 “실제 체결 기준”으로 봐야 개선 우선순위를 정확히 잡을 수 있으므로, 체결 원장 우선 구조가 맞음
- fallback을 완전히 제거하면 과거 데이터 가시성이 사라지므로, 원장 우선 + 레거시 fallback 구조가 운영 전환에 가장 현실적임
- source/latency/fee/stage 지표가 있어야 라우팅 문제, 체결 지연, 비용 누적, 부분청산 패턴을 서로 다른 문제로 분리해서 다룰 수 있음

### 최신 검증 스냅샷
- 기본 테스트 실행 결과: `49 passed, 1 skipped` (`RUN_BINANCE_LIVE=1` 실연결 테스트는 opt-in)

## 2026-03-07 Iteration #25
### 무엇을 발견했는가
- 문서와 테스트는 이미 `execution_fills` 우선 집계 계약(`fill_sources`, `stage_counts`, `triggered_no_entry`, entry-model별 execution coverage)을 전제로 하고 있었지만, 실제 소스 파일 `app/services/execution_quality.py`는 누락된 상태였음
- 이 드리프트 때문에 실행 품질 리포트 기능은 소스 기준으로는 재현 불가능했고, 계약과 구현의 일치성이 깨져 있었음

### 무엇을 수정했는가
- `app/services/execution_quality.py` 소스 복구 및 계약 재정렬
  - `execution_fills` 우선, `zone_outcomes` fallback 구조 복원
  - `fill_sources`, `stage_counts`, `entry_latency_seconds`, `fees` 지표 출력 정합화
  - 미체결 사유 `triggered_no_entry` 및 entry-model별 `execution_source_rate`/`partial_exit_rate`/`closed_rate` 반영
- README 보강
  - 실행 품질 리포트의 데이터 소스 우선순위(`execution_fills -> zone_outcomes fallback`) 명시

### 왜 그렇게 판단했는가
- 이 기능은 운영 의사결정에 직접 쓰이는 리포트라서 문서/테스트/실제 소스가 모두 같은 계약을 따라야 함
- 체결 원장 기반 지표는 슬리피지, 지연, 체결 단계 커버리지를 실제 운영 데이터로 보게 해주므로 추정 기반 집계보다 우선해야 함

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `49 passed, 1 skipped` (`.venv/bin/python -m pytest -q`)

## 2026-03-07 Iteration #26
### 무엇을 발견했는가
- 알림 채널은 재시도/서킷브레이커까지는 있었지만, 채널별 전달 성공률과 p95 지연을 운영 기준으로 확인하는 집계 경로가 없었음
- `validation_alert.delivery`와 `/alerts/test` 결과는 저장되고 있었지만, `system` fanout의 leaf 채널 성과와 현재 서킷 오픈 상태를 한 번에 보는 API가 없었음

### 무엇을 수정했는가
- 알림 관측성 보강
  - `NotificationDispatcher`에 `latency_ms` 측정 추가
  - 현재 서킷 상태 스냅샷 `NotificationDispatcher.circuit_snapshot()` 추가
- 집계 서비스/API/스크립트 추가
  - `app/services/alert_metrics.py` 신규
  - `GET /alerts/metrics?days=...&write_report=...` 추가
  - `scripts/generate_alert_metrics_report.py` 추가
  - 리포트 출력: `reports/alerts/alert_metrics_<UTC>.md`
- 집계 지표
  - `overall`(leaf 채널 기준), `channel_metrics`, `circuit_state`
  - 채널별 `success_rate`, `failure_rate`, `latency_ms`, `circuit_open_count`, `slo`
- 테스트/문서 동기화
  - `tests/test_alert_metrics.py` 신규
  - `tests/test_notification_dispatcher.py`, `tests/test_api_smoke.py` 보강
  - README/PLAN/CHECKLIST/CONTEXT/운영 매뉴얼 업데이트

### 왜 그렇게 판단했는가
- 운영 알림은 “보낸다”보다 “얼마나 안정적으로 도달하는가”를 수치로 봐야 대응이 빨라짐
- `system` fanout은 상위 집계와 leaf 채널 성과를 분리해서 봐야 실제 병목 채널을 찾을 수 있음
- 서킷브레이커 상태를 현재 시점 스냅샷으로 같이 노출해야, 실패율 리포트와 실시간 복구 상태를 하나의 판단 흐름으로 연결할 수 있음

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `50 passed, 1 skipped` (`.venv/bin/python -m pytest -q`)

## 2026-03-07 Iteration #27
### 무엇을 발견했는가
- `PlanGenerator`는 이미 runtime importance calibration 훅(`importance_calibration`)을 받을 수 있었지만, 실제 엔진/API/리포트 경로에는 연결되지 않아 죽은 경로로 남아 있었음
- `feature_calibration` 서비스 초안은 plan generator가 기대하는 snapshot 구조(`by_regime`, `feature_weights_active`, `matched_samples`)와 어긋나 있어서 runtime 적용 근거로 쓰기 어려웠음
- `validation/report`도 피처 중요도까지만 포함하고 있어, “왜 가중치가 바뀌었는지”를 운영자가 바로 확인할 수 없었음

### 무엇을 수정했는가
- 온라인 캘리브레이션 최소 루프 구현
  - `app/services/feature_calibration.py` 재구성
  - EWMA 점수, bounded delta, latest snapshot 저장, Markdown 리포트 생성
  - runtime snapshot 구조를 `by_regime.feature_weights_active` 기준으로 정규화
- 엔진/API/리포트 연동
  - `StrategyEngine.refresh_symbol(...)`가 latest calibration snapshot을 플랜 생성에 반영
  - `StrategyEngine.recompute_learning(...)`가 `feature_importance`와 `feature_calibration`을 함께 계산
  - `GET /validation/feature-calibration` 추가(기존 `/validation/importance-calibration` alias 유지)
  - `POST /validation/report` 응답/Markdown에 `feature_calibration` 포함
  - 스크립트 추가: `scripts/generate_feature_calibration_report.py`
- 테스트/문서 동기화
  - 신규 테스트: `tests/test_feature_calibration.py`
  - 보강 테스트: `tests/test_validation_report.py`, `tests/test_api_smoke.py`
  - README/PLAN/CHECKLIST/CONTEXT/운영 매뉴얼 업데이트

### 왜 그렇게 판단했는가
- 중요도 온라인 캘리브레이션의 핵심은 “가중치를 계산한다”가 아니라, 계산된 가중치가 실제 플랜 생성과 검증 리포트에 동일하게 적용되는 것이다
- snapshot 스키마와 runtime 계약이 다르면 운영 중 어떤 가중치가 실제 집행에 반영됐는지 추적할 수 없으므로, `by_regime` 단일 구조로 정렬하는 편이 맞다
- bounded delta와 snapshot 기반 runtime 적용을 고정해야 레짐 변화에는 적응하면서도 과도한 가중치 진동은 막을 수 있다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `52 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #28
### 무엇을 발견했는가
- 중요도 온라인 캘리브레이션 경로는 엔진/API에는 연결되어 있었지만, 테스트가 여전히 snapshot-only/ablation-only 가정에 묶여 있어 실제 `plan -> outcome` 매칭 기반 보정 계약을 고정하지 못하고 있었음
- `feature_calibration_min_generated_plans` 설정값이 실제 서비스에서는 사용되지 않아, generated plan 표본이 부족한 상태에서도 runtime 보정이 열릴 수 있는 드리프트가 있었음
- 운영 문서도 “Ablation 결과를 EWMA로 반영”하는 수준으로만 적혀 있어, 실제 runtime 보정 근거(`confluence_components x realized R`)와 달라져 있었음

### 무엇을 수정했는가
- `FeatureCalibrationService` 보강
  - `baseline.generated_plans < feature_calibration_min_generated_plans`이면 `insufficient_generated_plans`로 차단
- 회귀 테스트 재정렬
  - `tests/test_feature_calibration.py`를 실제 계약 기준으로 교체
  - 최근 `plans.validity.confluence_components`와 `zone_outcomes`를 매칭해
    `recommended_weights`, `zone_type_multipliers`, snapshot/report persistence, runtime payload를 검증
  - `PlanGenerator`가 `feature_weights_active`, `feature_calibration_samples`, `zone_type_multiplier_active`를 validity에 남기는지 검증
- 문서 동기화
  - README/PLAN/CHECKLIST/CONTEXT/운영 매뉴얼에 outcome-grounded calibration, minimum gates, legacy alias, 최신 테스트 기준선 반영

### 왜 그렇게 판단했는가
- 이 루프의 본질은 “분석 리포트가 있다”가 아니라, 최근 실현 결과를 근거로 runtime 가중치가 제한된 범위 안에서만 움직이고 있다는 점을 계약으로 고정하는 것이다
- generated plan 표본 하한이 없으면 우연한 소수 샘플에 runtime 가중치가 흔들릴 수 있으므로, `matched_samples`와 별도로 minimum gate를 두는 편이 안전하다
- 운영 문서가 실제 계산 근거와 다르면, 나중에 가중치 변화 원인을 잘못 해석해 잘못된 수동 튜닝으로 이어질 가능성이 크다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `53 passed, 1 skipped` (`.venv/bin/python -m pytest -q`)

## 2026-03-07 Iteration #29
### 무엇을 발견했는가
- 기존 포트폴리오 오버레이는 상관도/노출 수 기반 v1이라, 문서에서 요구한 `상관 + 변동성 + 레짐` 버짓을 실제 스캐너 판단에 반영하지 못하고 있었음
- 스캐너 API도 차단/패널티 결과만 보여 주고, 운영자가 왜 특정 후보가 밀렸는지 설명할 `risk_budget_score`와 동적 cap 정보가 없었음

### 무엇을 수정했는가
- 포트폴리오 리스크 버짓 v2 최소 루프 구현
  - `PortfolioRiskOverlayService`에 5m realized volatility 계산 추가
  - 레짐별 cap multiplier(`range/trend/shock`)와 regime penalty 추가
  - `risk_budget_score`와 exposure pressure penalty를 스캐너 랭킹/차단 로직에 반영
- 스캐너 응답 계약 확장
  - `regime`, `risk_budget_score`, `portfolio_volatility`
  - `portfolio_total_cap`, `portfolio_directional_cap`, `portfolio_cluster_cap`
- 테스트/문서 동기화
  - `tests/test_portfolio_overlay.py`에 shock cap 축소 / 고변동성 penalty 회귀 추가
  - `tests/test_api_smoke.py`에 새 scanner 응답 필드 검증 추가
  - README/PLAN/CHECKLIST/CONTEXT/운영 매뉴얼 업데이트

### 왜 그렇게 판단했는가
- 포트폴리오 버짓은 별도 리포트보다 스캐너 선별 경로에 직접 걸어야 실전 동작에 의미가 있다
- 상관도만으로는 shock 구간의 동조화 손실을 충분히 줄이기 어려워서, 변동성과 레짐을 함께 cap에 반영하는 편이 맞다
- 운영자가 결과를 튜닝하려면 “왜 패널티가 걸렸는가”가 응답에 드러나야 하므로 risk budget 필드 노출이 필요하다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `55 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #30
### 무엇을 발견했는가
- 최신 전략 논의(`transition`, `acceptance/rejection`, `A-only`, `exit engine`, `thesis dedupe`)는 대화로는 정리됐지만, 파일 기준 단일 참조 문서가 없어 운영 문서와 분리된 상태였음
- 기존 운영 매뉴얼은 현재 구현 기준 설명에는 충분했지만, 아직 구현 전인 전략 설계 청사진을 체계적으로 담기엔 범위가 부족했음

### 무엇을 수정했는가
- 전략 청사진 문서 신규 작성
  - `docs/STRATEGY_V2_BLUEPRINT.md`
  - 상태/전략군/판정표/acceptance-rejection/사이징/exit/lock/thesis dedupe/A-only를 단일 문서로 고정
- Living 문서 연결
  - `README.md` 문서 목록에 청사진 추가
  - `docs/PLAN.md`에 전략 설계 기준선 섹션 추가
  - `docs/CHECKLIST.md`에 전략 v2 청사진 문서화 항목 추가
  - `docs/CONTEXT_NOTE.md`에 전략 해석 우선순위와 transition/A-only 규칙 추가
  - `docs/STRATEGY_OPERATING_MANUAL.md`에 청사진 참조 기준 추가
  - `docs/UPGRADE_ROADMAP_VNEXT.md`에 전략 설계 기준선 링크 추가

### 왜 그렇게 판단했는가
- 구현 문서와 전략 설계 문서를 분리하지 않으면, 아직 코드화되지 않은 전략 논의가 운영 규칙과 섞여 해석되는 문제가 생긴다
- 최신 전략안은 패턴 설명보다 상태/락/운영 규율이 중심이라, 별도 청사진 문서로 고정하는 편이 가장 명확하다
- 체크리스트와 계획서까지 같이 갱신해야 이후 구현 턴에서 어떤 내용이 `설계 확정`인지 혼동이 없다

### 최신 검증 스냅샷
- 문서화 전용 변경으로 테스트는 재실행하지 않음
- 코드 기준 최신 회귀 결과는 `55 passed, 1 skipped`

## 2026-03-07 Iteration #31
### 무엇을 발견했는가
- `STRATEGY_V2_BLUEPRINT`만으로는 운영 단계와 구현 단계가 한 문서에 섞여 있어, 실전 체크리스트와 코드 스펙으로 바로 옮기기엔 아직 추상도가 높았음
- 특히 `A-only 운영`, `acceptance/rejection 세부 계약`, `구현 항목 분해`가 분리되어 있지 않으면 다음 구현 턴에서 다시 전략 논의를 반복할 가능성이 컸음

### 무엇을 수정했는가
- 세부 전략 문서 추가
  - `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md`
  - `docs/STRATEGY_V2_ACCEPTANCE_REJECTION_SPEC.md`
  - `docs/STRATEGY_V2_IMPLEMENTATION_CHECKLIST.md`
- Living 문서 연결
  - `README.md` 문서 목록 확장
  - `docs/PLAN.md`에 운영/신호/구현 기준선 링크 추가
  - `docs/CHECKLIST.md`에 신규 문서화 항목 추가
  - `docs/CONTEXT_NOTE.md`, `docs/STRATEGY_OPERATING_MANUAL.md`, `docs/UPGRADE_ROADMAP_VNEXT.md`에 참조 규칙 추가

### 왜 그렇게 판단했는가
- 전략 문서는 `청사진`, `운영 플레이북`, `신호 스펙`, `구현 체크리스트`로 나눠야 다음 단계에서 해석/운영/개발 책임이 분리된다
- 특히 acceptance/rejection은 전략의 핵심 분기라서, 청사진의 요약 설명만으로는 구현/검증 기준을 고정하기 어렵다
- A-only 플레이북을 분리해 두면 실전 운영 규율을 구현 완료 전에도 독립적으로 검토할 수 있다

### 최신 검증 스냅샷
- 문서화 전용 변경으로 테스트는 재실행하지 않음
- 코드 기준 최신 회귀 결과는 `55 passed, 1 skipped`

## 2026-03-07 Iteration #32
### 무엇을 발견했는가
- 전략 v2 문서가 이미 많이 정리됐지만, 마지막 남은 핵심 명세(`transition` 정량 기준, thesis fingerprint, exit schema, validation/PBO/DSR)가 빠져 있어 “기획 완료”라고 부르기엔 아직 구현 계약이 모자랐음
- 특히 이 4개가 없으면 다음 구현 턴에서 다시 전략 해석 논의로 돌아가거나, execution/validation 레이어마다 다른 기준을 쓰게 될 가능성이 있었음

### 무엇을 수정했는가
- 정량/계약 문서 추가
  - `docs/STRATEGY_V2_TRANSITION_REGIME_SPEC.md`
  - `docs/STRATEGY_V2_THESIS_FINGERPRINT_SPEC.md`
  - `docs/STRATEGY_V2_EXIT_EVENT_SCHEMA.md`
  - `docs/STRATEGY_V2_VALIDATION_PROTOCOL.md`
- 기존 전략 문서 상태 승격
  - `STRATEGY_V2_BLUEPRINT`: finalized
  - `STRATEGY_V2_A_ONLY_PLAYBOOK`: finalized
  - `STRATEGY_V2_ACCEPTANCE_REJECTION_SPEC`: frozen
  - `STRATEGY_V2_IMPLEMENTATION_CHECKLIST`: ready for implementation
- Living 문서 동기화
  - `README.md`, `docs/PLAN.md`, `docs/CHECKLIST.md`, `docs/CONTEXT_NOTE.md`, `docs/STRATEGY_OPERATING_MANUAL.md`, `docs/UPGRADE_ROADMAP_VNEXT.md`
  - 전략 v2 기획 완료 기준 체크 항목 추가

### 왜 그렇게 판단했는가
- 전략 기획을 끝내려면 “좋은 아이디어”가 아니라 “구현 시 해석 차이가 나지 않는 계약”까지 있어야 한다
- transition/exit/validation/thesis는 전략 성능과 운영 안정성을 직접 흔드는 영역이라, 후순위 메모가 아니라 고정 문서로 분리하는 편이 맞다
- 이제는 더 이상 전략 브레인스토밍보다 구현 우선순위 관리가 중요하므로, 문서 상태를 `finalized / frozen / ready for implementation`으로 올렸다

### 최신 검증 스냅샷
- 문서화 전용 변경으로 테스트는 재실행하지 않음
- 코드 기준 최신 회귀 결과는 `55 passed, 1 skipped`

## 2026-03-07 Iteration #33
### 무엇을 발견했는가
- 실행 품질 리포트는 `execution_fills` 기반 v2까지는 반영됐지만, 실제 롤아웃 판단에 필요한 `strategy_version` 비교와 상세 미체결 사유 분해가 빠져 있었음
- 이 상태에서는 집행 악화가 특정 버전 문제인지, 라우팅/확인 실패인지, 단순 미도달인지 구분이 약해서 다음 튜닝 우선순위를 잘못 잡을 위험이 있었음

### 무엇을 수정했는가
- 실행 품질 리포트 v3 구현
  - `ExecutionQualityService`에 `by_strategy_version`, `version_comparison`, `fill_events_total`, `unfilled_reason_details` 추가
  - 상세 사유 분해 추가: `expired_without_touch`, `expired_after_touch_limit`, `expired_after_touch_confirmation`, `timed_out_after_trigger`, `order_rejected`, `cancelled_before_entry`
  - Markdown 리포트에 버전 비교 섹션 추가
- API/테스트/문서 동기화
  - `ExecutionQualityOut` 스키마 확장
  - `tests/test_execution_quality.py`에 버전 비교/거절 사유 회귀 추가
  - `tests/test_api_smoke.py`에 신규 응답 필드 검증 추가
  - `README.md`, `docs/PLAN.md`, `docs/CHECKLIST.md`, `docs/CONTEXT_NOTE.md`, `docs/STRATEGY_OPERATING_MANUAL.md`, `docs/UPGRADE_ROADMAP_VNEXT.md` 업데이트

### 왜 그렇게 판단했는가
- 전략 변경은 `strategy_version` 단위로 롤아웃하므로, 실행 품질도 같은 축으로 비교 가능해야 운영 의사결정이 일관된다
- 미체결 원인을 세분하지 않으면 `확인 실패`, `트리거 후 시간초과`, `거절`, `미도달`이 한 버킷으로 섞여 라우터/집행 개선 방향을 왜곡한다
- 이번 단계의 핵심은 새 신호 추가가 아니라 `실제 집행 데이터 -> 리포트/API -> 테스트 -> 운영 문서`를 같은 스키마로 고정하는 데 있다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `56 passed, 1 skipped` (`.venv/bin/python -m pytest -q -rs`)

## 2026-03-07 Iteration #34
### 무엇을 발견했는가
- 알림 채널은 즉시 재시도/서킷브레이커/SLO까지는 있었지만, 실패 전송을 앱 재시작 이후에도 이어서 처리할 재시도 큐와 dead-letter 경로가 없어 운영 복원력이 부족했음
- `/alerts/metrics`도 성공률과 지연은 보여 줬지만, 실제 SLO 예산이 얼마나 소진됐는지와 큐 적체 상태는 바로 보이지 않았음

### 무엇을 수정했는가
- 알림 복원력 v2 후속 구현
  - `alert_retry_queue` 테이블 및 저장소 추가
  - `AlertRetryQueueService` 추가(재시도 큐, dead-letter, manual requeue)
  - 엔진의 실제 전송 경로(`validation alert`, `alerts/test`)에 큐 적재 연동
- API/운영 도구 확장
  - `GET /internal/alerts/retry-queue/status`
  - `POST /internal/alerts/retry-queue/process`
  - `POST /internal/alerts/retry-queue/dead-letter/requeue`
  - `scripts/process_alert_retry_queue.py`
- metrics 확장
  - `alerts/metrics`에 `retry_queue`, `overall.error_budget`, `channel_metrics.*.error_budget` 추가
- 테스트/문서 동기화
  - `tests/test_alert_retry_queue.py` 신규 추가
  - `tests/test_alert_metrics.py`, `tests/test_api_smoke.py` 확장
  - README/PLAN/CHECKLIST/CONTEXT/운영 매뉴얼/로드맵 업데이트

### 왜 그렇게 판단했는가
- 서킷브레이커는 즉시 보호에는 유효하지만, 실패 전송을 나중에 복구할 큐와 dead-letter가 없으면 결국 운영자가 수동으로 놓친 알림을 추적해야 한다
- error budget은 단순 성공률보다 운영 우선순위를 더 잘 드러내므로, SLO 옆에 같이 노출해야 채널 품질 저하를 조기에 잡을 수 있다
- 이번 단계도 핵심은 새 알림 채널을 추가하는 게 아니라 `실패 -> 큐 -> 재시도 -> dead-letter -> metrics/report`를 단일 경로로 고정하는 데 있다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `58 passed, 1 skipped` (`.venv/bin/python -m pytest -q -rs`)

## 2026-03-07 Iteration #35
### 무엇을 발견했는가
- 포트폴리오 리스크 오버레이는 스캐너 후보를 잘 걸러주고 있었지만, 현재 노출과 남은 버짓, 차단 사유를 한 번에 확인하는 운영 경로가 없었음
- 이 상태에서는 `total/directional/cluster` 중 어떤 한도가 실제 병목인지 API/리포트에서 바로 분리되지 않아, 포트폴리오 파라미터 조정 우선순위가 흐려질 수 있었음

### 무엇을 수정했는가
- 포지션/포트폴리오 통합 버짓 리포트 구현
  - `PortfolioRiskOverlayService`에 `assess_rows`, `exposure_metrics`, `budget_caps_for_regime` 추가
  - `PortfolioBudgetReportService` 추가(`current_exposure`, `headroom_by_regime`, `current_positions`, `blocked_reason_counts`)
  - API 추가: `GET /portfolio/budget`
  - 스크립트 추가: `scripts/generate_portfolio_budget_report.py`
- 테스트/문서 동기화
  - `tests/test_portfolio_budget_report.py` 신규 추가
  - `tests/test_api_smoke.py`에 `/portfolio/budget` 계약 검증 추가
  - `README.md`, `docs/PLAN.md`, `docs/CHECKLIST.md`, `docs/CONTEXT_NOTE.md`, `docs/STRATEGY_OPERATING_MANUAL.md`, `docs/UPGRADE_ROADMAP_VNEXT.md` 업데이트

### 왜 그렇게 판단했는가
- 포트폴리오 버짓은 스캐너 점수만으로는 충분하지 않고, “현재 얼마를 이미 쓰고 있는지”와 “왜 다음 후보가 막혔는지”가 같은 스냅샷에 있어야 운영자가 바로 판단할 수 있다
- 특히 `blocked_reason_counts`가 없으면 cap 초과가 총노출 문제인지 방향 편중인지 상관 클러스터 문제인지 섞여 보여, 잘못된 파라미터 튜닝으로 이어질 수 있다
- 이번 단계의 핵심은 새 전략 로직 추가가 아니라 `현재 노출 -> 후보 평가 -> headroom -> 리포트/API`를 동일한 계산 기준으로 고정하는 데 있다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `59 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #36
### 무엇을 발견했는가
- 전략 v2 구현 체크리스트의 첫 코드화 항목이 아직 비어 있었고, 특히 `transition` 상태가 엔진에 없어서 `mixed/no-trade`, `confirm only`, `shock/transition lock` 규칙을 실제로 표현할 수 없었음
- 이 상태에서는 뒤의 acceptance/rejection classifier나 thesis dedupe를 넣더라도, 가장 앞단의 시장 상태 분류가 `trend/range/shock` 3단계로만 닫혀 있어서 v2 운영 규칙이 중간에서 누락될 위험이 있었음

### 무엇을 수정했는가
- 전략 v2 상태 엔진 1차 코드화
  - `ContextSnapshot`에 `transition_score`, `transition_state`, `transition_features`, `transition_unlock_candidate`, `transition_lock_reason` 추가
  - `ContextEngine`에 transition 진단 로직 추가
    - `opposing_impulse_conflict`
    - `bidirectional_sweep_churn`
    - `reaction_failure_cluster`
    - `wick_dominance`
    - `state_disagreement`
    - `zone_invalidation_churn`
  - `PlanGenerator`에 transition lock 연결
    - `transition_confirmed` -> 하드 차단
    - `transition_watch` -> `LIMIT` 금지, `CONFIRM` 강등
  - `refresh_symbol` 응답에 `transition_score/state/lock_reason` 노출
- 테스트/문서 동기화
  - `tests/test_context_engine_transition.py` 신규 추가
  - `tests/test_plan_quality_gates.py`에 transition confirmed/watch 회귀 추가
  - `docs/STRATEGY_V2_IMPLEMENTATION_CHECKLIST.md` 상태 엔진 3개 항목 완료 처리
  - Living 문서(README/PLAN/CHECKLIST/CONTEXT/운영 매뉴얼/로드맵) 갱신

### 왜 그렇게 판단했는가
- v2의 핵심은 새로운 패턴 추가가 아니라 `no-trade`를 더 잘 만드는 데 있고, 그 첫 번째 분기점이 `transition` 상태 엔진이다
- transition이 빠진 상태에서 classifier나 전략군 라우팅을 먼저 넣으면, 나중에 상위 상태 분류가 바뀌면서 하위 로직 계약이 다시 흔들릴 가능성이 크다
- 따라서 이번 단계는 “전략군 추가”보다 “시장 상태를 잘못 읽는 구간을 먼저 막는 것”을 우선한 구현이 맞다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `62 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #37
### 무엇을 발견했는가
- 전략 v2 문서에는 `acceptance/rejection` 판정이 고정돼 있었지만, 런타임 엔진에는 이를 일관되게 계산하고 `mixed=no-trade`를 강제하는 서비스가 없었음
- 이 상태에서는 같은 sweep 이벤트를 setup마다 다르게 해석할 수 있어, 이후 전략군 라우팅을 넣더라도 기준이 흔들릴 위험이 있었음

### 무엇을 수정했는가
- `AcceptanceRejectionClassifierService` 추가
  - 입력 계약 고정: `ATR`, `reclaim_bars`, `outside_close_count`, `dwell_time_bars`, `inefficiency_created`, `retest_hold`
  - 분류 결과: `rejection_confirmed`, `rejection_tentative`, `acceptance_confirmed`, `acceptance_tentative`, `mixed`
- `PlanGenerator` 연동
  - `mixed` -> 신규 플랜 생성 차단
  - `acceptance_*` -> reversal 성격 후보 차단
  - `rejection_tentative` -> `confirm only`
  - `validity`에 reaction score/input/log 저장
- 테스트/문서 동기화
  - `tests/test_acceptance_rejection_classifier.py`, `tests/test_plan_quality_gates.py` 확장
  - Living 문서 및 전략 v2 구현 체크리스트 갱신

### 왜 그렇게 판단했는가
- 상태 엔진 다음 단계는 패턴 추가가 아니라 “같은 반응을 같은 방식으로 읽는 계약”을 고정하는 것이고, classifier가 그 최소 단위다
- classifier 없이 strategy family를 먼저 넣으면, family routing이 사실상 불안정한 임시 규칙 위에 올라가게 된다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `67 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #38
### 무엇을 발견했는가
- classifier까지 붙은 상태에서도 `rejection` 이벤트가 실제로 어떤 전략군으로 승격되고 어떤 레짐에서 차단되는지가 엔진에 없었음
- 특히 `trend non-extreme`, `shock`, `transition_watch`에서 `Sweep Reversal` 예외 규칙을 코드로 잠그지 않으면, v2 운영 문서와 실제 플랜 생성이 다시 벌어질 수 있었음

### 무엇을 수정했는가
- `StrategyFamilyRouter` 추가
  - `sweep_reversal` family score/grade(A/B/C) 계산
  - family-specific routing (`A clean -> LIMIT`, `A -> SWEEP_CONFIRM`, `B/C -> CONFIRM`)
  - `trend non-extreme`, `shock non-A`, `transition_watch non-A` 차단
- `PlanGenerator` 연동
  - rejection 기반 candidate만 `sweep_reversal` family로 승격
  - fixed split `40/40/20`, time stop `3~5 bars`, family metadata 저장
- API/scanner 확장
  - `strategy_family`, `strategy_grade` 노출
- 테스트/문서 동기화
  - `tests/test_strategy_family_router.py` 신규 추가
  - `tests/test_plan_quality_gates.py`, `tests/test_api_smoke.py` 확장
  - README/PLAN/CHECKLIST/CONTEXT/운영 매뉴얼/로드맵 갱신

### 왜 그렇게 판단했는가
- 전략 v2는 `상태 -> 반응 -> 전략군` 순서가 닫혀야 하고, 그 첫 전략군이 `Sweep Reversal`이다
- 라우팅과 entry model, time stop, split이 분리돼 있으면 운영자는 같은 setup을 API/문서/실행 경로마다 다르게 해석하게 된다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `72 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #39
### 무엇을 발견했는가
- `Sweep Reversal`까지는 붙었지만, `trend` 레짐의 주력 전략군인 `Trend Continuation Pullback`이 아직 없어 강추세 구간에서도 generic v1 플랜이 그대로 남아 있었음
- 이 상태에서는 `healthy pullback`, `protected low/high hold`가 깨진 저품질 trend candidate도 family-level block 없이 통과할 수 있었음

### 무엇을 수정했는가
- `StrategyFamilyRouter`에 `trend_continuation` family 추가
  - `trend` regime only
  - `OB/FVG` execution zone only
  - `impulse quality`, `healthy pullback`, `protected level hold` 점수화
  - `A -> LIMIT`, `B/C -> CONFIRM`
  - split `30/30/40`, time stop `5~8 bars`
- `PlanGenerator` 연동
  - trend continuation candidate는 family router 기준으로 통과/차단
  - low-quality trend candidate는 generic fallback 우회 없이 차단
- 테스트/문서 동기화
  - `tests/test_strategy_family_router.py`에 trend continuation 라우팅/차단 케이스 추가
  - `tests/test_plan_quality_gates.py`에 trend continuation validity 메타데이터 저장 검증 추가
  - README/PLAN/CHECKLIST/CONTEXT/운영 매뉴얼/로드맵 갱신

### 왜 그렇게 판단했는가
- 전략 v2의 우선순위는 `trend: Trend Continuation Pullback > Sweep Reversal at extreme only`라서, 두 번째 family를 넣어야 레짐 우선순위가 실제 엔진에서 닫힌다
- family-level block이 없으면 문서상 금지된 약한 pullback이 generic plan으로 우회할 수 있어, 전략군 분기의 의미가 약해진다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `75 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #40
### 무엇을 발견했는가
- `Sweep Reversal`, `Trend Continuation`까지는 family routing이 붙었지만, `Range Rotation`은 아직 live family인지 research-only family인지 엔진에서 구분되지 않았음
- 이 상태에서는 range reversal 후보가 향후 generic plan이나 다른 family로 섞일 위험이 있었고, 문서의 `research only` 규칙이 코드에 고정돼 있지 않았음

### 무엇을 수정했는가
- `StrategyFamilyRouter`에 `range_rotation` family 추가
  - `range` regime only
  - reversal signal 기반
  - `range_definition`, `edge_proximity`, `liquidity_grab`, `reversal_quality`, `range_width`, `htf_conflict`, `session_quality` 점수화
  - live 승격은 막고 `range_rotation_research_only` reason으로 명시적 차단
  - `range center`는 `range_rotation_range_center_block`으로 별도 차단
- `PlanGenerator` 연동
  - range rotation family가 인식되면 generic fallback으로 우회하지 않고 live plan 생성 차단
- 테스트/문서 동기화
  - `tests/test_strategy_family_router.py`에 research-only / center-block 케이스 추가
  - `tests/test_plan_quality_gates.py`에 research-only block 통합 케이스 추가
  - README/PLAN/CHECKLIST/CONTEXT/운영 매뉴얼/로드맵 갱신

### 왜 그렇게 판단했는가
- 이번 단계의 목적은 `Range Rotation` 성능을 바로 여는 것이 아니라, family를 연구용으로 격리해 실거래 경로와 섞이지 않게 만드는 데 있다
- research/live 분리가 없으면 이후 운영 모드(`A_ONLY`, `RESEARCH`)를 붙일 때 이미 생성된 plan 계약을 다시 흔들게 된다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `78 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #41
### 무엇을 발견했는가
- family routing을 세 개까지 올린 뒤에도, family가 없는 generic 후보는 여전히 runtime에서 생성될 수 있었고 특히 `OB-only`, `FVG-only`, `trendline-led` 같은 문서상 금지 패턴이 우회할 수 있었음
- 이 상태에서는 전략 문서가 “execution zone is secondary”라고 고정해도, 실제 엔진에서는 execution zone 자체가 독립 신호처럼 남아 있게 됨

### 무엇을 수정했는가
- `PlanGenerator`에 generic pattern-only block 추가
  - family 없음
  - nearby liquidity 없음
  - reaction 없음
  - runtime 5m candle 기준
  - 위 조건에서 `OB-only`, `FVG-only`, `trendline-led` 차단
- 현재 `trendline-led`는 별도 trendline detector가 없으므로 `trend_proxy` 우세 generic setup을 proxy로 차단
- 테스트/문서 동기화
  - `tests/test_plan_quality_gates.py`에 `OB-only`, `FVG-only`, `trendline-led` 차단 회귀 추가
  - README/PLAN/CHECKLIST/CONTEXT/운영 매뉴얼/로드맵 갱신

### 왜 그렇게 판단했는가
- v2의 핵심 원칙은 `Location -> Liquidity -> Reaction -> Execution` 순서이고, execution zone만으로 통과하는 generic 경로가 남아 있으면 이 원칙이 무너진다
- family routing을 먼저 고정한 뒤 pattern-only block을 넣어야, 차단 기준이 “무조건 zone 금지”가 아니라 “family 없이 zone만 남은 경우 금지”로 안정적으로 작동한다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `81 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #42
### 무엇을 발견했는가
- `thesis fingerprint` 스펙 문서는 고정됐지만, plan 생성/scanner/portfolio overlay가 서로 다른 기준으로 후보를 보면서 동일 아이디어 중복 배치를 실제로 막지 못하고 있었음
- 특히 active exposure와 신규 scanner 후보 사이에 shared cluster identity가 없어, 같은 thesis를 다른 심볼로 반복 제안하는 경로가 열려 있었음

### 무엇을 수정했는가
- `app/services/thesis_fingerprint.py` 추가
  - direction/regime/strategy family/liquidity narrative/event class/time bucket/correlation cluster 기준 fingerprint 정규화
  - equivalent narrative, rejection/acceptance group, adjacent 30m bucket 판정 구현
- `PlanGenerator` 연동
  - `plan.validity`에 `thesis_fingerprint`, `thesis_cluster_id`, `thesis_cluster_size`, `thesis_primary_symbol`, `thesis_rejected_reason` 저장
- `PortfolioRiskOverlayService` 연동
  - active thesis cluster 빌드
  - `thesis_duplicate_blocked`, `thesis_active_cap_reached` reason 추가
  - `GET /scanner/top`, `GET /portfolio/budget` 응답에 thesis 필드 노출
- 리포트/테스트/문서 동기화
  - `tests/test_thesis_fingerprint.py` 신규 추가
  - `tests/test_plan_quality_gates.py`, `tests/test_portfolio_overlay.py`, `tests/test_portfolio_budget_report.py`, `tests/test_api_smoke.py` 확장
  - Living 문서와 v2 구현 체크리스트 갱신

### 왜 그렇게 판단했는가
- 전략 v2의 `One thesis, one risk` 원칙은 scoring보다 먼저 execution/scanner 공용 identity가 있어야 성립한다
- sizing v2 이전 단계에서는 최소한 `same thesis duplicate block`과 `active thesis cluster cap`이 먼저 들어가야, 이후 `thesis_factor`가 이미 일관된 cluster 기준 위에서 작동할 수 있다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `86 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #43
### 무엇을 발견했는가
- `strategy_family_components`는 저장되고 있었지만 family마다 key가 제각각이라, A/B/C score 해석과 후속 sizing/리포트에서 공통 계약으로 재사용하기 어려웠음
- 문서의 `Location / Liquidity / Reaction / Invalidation / Session` score bucket과 코드의 raw component가 직접 연결되지 않아 운영자가 같은 점수를 다른 방식으로 해석할 위험이 있었음

### 무엇을 수정했는가
- `StrategyFamilyDecision.scorecard` 추가
  - family별 raw component 유지
  - 공통 bucket(`location`, `liquidity`, `reaction`, `invalidation`, `session`, `trendline_bonus`) 저장
  - `grade_thresholds`, `bucket_caps`, `score`, `score_ex_trendline`, `trendline_bonus_source` 저장
- `PlanGenerator` 연동
  - `validity`에 `strategy_scorecard`, `strategy_scorecard_buckets`, `strategy_scorecard_raw_components`, `strategy_scorecard_trendline_bonus` 저장
- `GET /scanner/top` 응답 연동
  - scanner row에 `strategy_scorecard` 노출
- 출력 계약 보정
  - 기존/부트스트랩 plan도 `GET /plans/top`에서 scorecard 키가 항상 존재하도록 기본값 주입
- 테스트/문서 동기화
  - `tests/test_strategy_family_router.py`, `tests/test_plan_quality_gates.py`, `tests/test_api_smoke.py` 확장
  - Living 문서와 v2 구현 체크리스트 갱신

### 왜 그렇게 판단했는가
- sizing v2와 validation 비교 리포트는 raw family 점수만으로는 부족하고, 공통 bucket 계약이 먼저 고정돼야 한다
- `trendline`은 현재 detector가 없으므로 score를 흔드는 primary factor가 아니라 explicit bonus-only placeholder로 남기는 편이 더 정확하다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `86 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #44
### 무엇을 발견했는가
- scorecard 이후에도 실제 리스크 추천값이 plan/scanner/portfolio마다 공통 계약으로 저장되지 않아, 같은 후보를 다른 화면에서 서로 다른 size로 해석할 여지가 있었음
- `transition_watch` sizing 규칙은 코드 설계와 일부 스펙 문서가 서로 다르게 적혀 있어 운영 해석 충돌 위험이 있었음

### 무엇을 수정했는가
- `PositionSizingService`를 추가해 `grade_risk x regime_factor x reaction_factor x thesis_factor x execution_factor` 공식을 코드화
- `strategy_sizing`, `recommended_risk_r`를 plan `validity`, scanner, portfolio budget report에 공통 저장/노출
- thesis active count 기반 clamp와 `transition_watch/transition_confirmed=0.00R`, `mixed=0.00R` 규칙을 회귀 테스트로 고정
- legacy `/plans/top` payload에도 sizing 기본값이 항상 존재하도록 보정
- `docs/STRATEGY_V2_TRANSITION_REGIME_SPEC.md`의 `transition_watch` size factor를 현재 구현과 동일하게 수정

### 왜 그렇게 판단했는가
- v2의 다음 단계인 mode 분리와 exit engine은 “이 후보를 얼마까지 허용하는가”라는 공통 sizing 계약이 먼저 고정돼야 안정적으로 붙일 수 있다
- 전략 점수와 thesis dedupe만 있고 size contract가 없으면 운영자는 같은 신호를 환경마다 다르게 해석하게 되고, 실제 실수는 이 지점에서 발생한다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `91 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #45
### 무엇을 발견했는가
- sizing 계약이 들어간 뒤에도 운영 모드가 코드에 없어서, `A-only` 기본 운영 규칙과 `A+B/RESEARCH` 비교 축이 여전히 문서에만 머물러 있었음
- mode를 곧바로 plan generator에 강하게 걸면 아직 남아 있는 legacy generic plan 회귀가 깨지는 문제가 있었음

### 무엇을 수정했는가
- `StrategyModeService`를 추가해 `A_ONLY`, `A_PLUS_B`, `RESEARCH` 정책을 코드화
- `scanner`와 `portfolio budget report`에 `daily_trade_limit`, `max_total_risk_r`, `shadow_only`를 실제 적용
- `GET /portfolio/budget`에 `strategy_mode`, `mode_policy`, `mode_stats`를 추가하고 리포트 파일명도 mode별로 분리
- `RESEARCH`는 `recommended_risk_r = 0.00`으로 고정했고, `A_ONLY/A_PLUS_B`는 family-tagged 후보에 대해 grade/family 제한을 적용
- legacy generic plan은 현재 회귀 호환을 위해 mode hard block에서 임시 passthrough로 유지

### 왜 그렇게 판단했는가
- mode 분리는 exit engine보다 먼저 있어야 이후 `A-only vs A+B` 검증과 daily lock이 같은 운영 축 위에서 작동한다
- 다만 현재 코드베이스는 아직 legacy generic plan이 남아 있어, mode strictness를 한 번에 100% 적용하면 기존 엔진 경로를 불필요하게 깨뜨린다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `97 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #46
### 무엇을 발견했는가
- 전략 v2 문서는 `exit_reason`, family time stop, `rejection -> acceptance` 반전 강제 청산을 요구하고 있었지만, 실제 체결 경로는 `CLOSED`만 저장하고 종료 사유를 표준화하지 못하고 있었음
- execution quality와 validation report도 종료 사유를 공통 지표로 쓰지 않아, 신호 문제와 청산 문제를 같은 축에서 비교하기 어려웠음

### 무엇을 수정했는가
- `ExitReason` enum과 `ExitEngineService`를 추가해 종료 이벤트 메타데이터를 표준화
- `PositionStateMachineService`에 family time stop / classification flip 기반 `time_failure`, `information_failure` 판정과 `plan.validity.final_exit_*` 저장을 연결
- `/internal/execution/fills`에 `exit_reason`, `held_bars`, `classification_before_exit`, `classification_after_exit`, `trigger_detail` 입력 계약을 추가
- `ExecutionQualityService`에 `exit_reasons`, `final_exit_reasons`, `target_exit_ratio`, `forced_exit_ratio`, `information_failure_ratio`, `time_failure_ratio`, `by_strategy_family` 집계를 추가
- `ValidationReportService`에 exit-quality summary 섹션을 추가하고 `POST /validation/report` 응답에도 `execution_quality`를 포함
- 관련 회귀 테스트와 living 문서를 현재 계약으로 동기화

### 왜 그렇게 판단했는가
- exit engine의 목적은 단순히 체결 상태를 `CLOSED`로 바꾸는 것이 아니라, 왜 청산됐는지를 execution ledger, 리포트, validation에서 같은 언어로 추적하게 만드는 데 있음
- time stop과 information failure를 같은 계약으로 잠가야 이후 daily/session lock과 A-only vs A+B 비교가 의미 있는 운영 데이터 위에서 돌아감

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `101 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #47
### 무엇을 발견했는가
- 기존 `risk_gate`는 인프라/점프/장기 손실 streak만 다뤘고, 전략 v2 문서가 요구한 `daily/session lock`은 코드에 없었음
- 운영자는 `risk_state=CLOSED`가 떠도 그 이유가 infra인지, 일일 손실 잠금인지, 세션 잠금인지 구분할 수 없었음

### 무엇을 수정했는가
- `OperatingLockService`를 추가해 `daily_realized_r`, `daily loss streak`, `A-grade loss streak`, `session_realized_r`, `session loss streak` 기반 잠금 계산을 구현
- unlock 정책을 코드화
  - daily: `next UTC day`
  - session: `current session end`
- `StrategyEngine`에 operating lock 합성 추가
  - `refresh_symbol`, `scanner_top`, `portfolio_budget_report`, `metrics`에 `risk_reason`, `operating_lock` 반영
- API/리포트 계약 확장
  - `GET /metrics/strategy`에 `risk_reason`, `operating_lock`
  - `GET /scanner/top` row에 `risk_reason`, `operating_lock`
  - `GET /portfolio/budget`에 top-level `operating_lock`
- 설정/파라미터 changelog 추적 키 추가
  - `operating_lock_*`, `trading_session_*`
- 회귀 테스트 추가
  - `tests/test_operating_lock.py`
  - `tests/test_portfolio_budget_report.py`
  - `tests/test_api_smoke.py`

### 왜 그렇게 판단했는가
- daily/session lock은 mode/sizing 이후에 붙는 운영 계층이라, scanner와 portfolio report가 같은 잠금 스냅샷을 공유해야 실제 운영 판단이 일관된다
- 잠금 자체보다 `왜 잠겼는가`와 `언제 풀리는가`를 API로 바로 볼 수 있어야 다음 단계인 validation 비교 리포트가 의미 있는 운영 데이터를 사용한다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `106 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #48
### 무엇을 발견했는가
- `docs/STRATEGY_V2_VALIDATION_PROTOCOL.md`는 첫 비교 축으로 `A-only` vs `A+B`를 고정했지만, 실제 엔진의 validation 경로에는 mode 비교 집계와 별도 `strategy_v2_validation` 템플릿이 없었음
- 기존 validation report는 WF/MC와 exit quality까지는 보여줬지만, `A_ONLY`가 왜 기본 배포 모드인지 운영 데이터로 바로 설명하지 못했음

### 무엇을 수정했는가
- `StrategyV2ValidationService`를 추가해 `closed v2 plans`의 `strategy_family`, `strategy_grade`, `final_exit_*` 메타데이터로 `A_ONLY`, `A_PLUS_B`, `B_INCREMENTAL` 비교를 계산
- 지표를 고정함
  - `trades`
  - `win_rate`
  - `EV`
  - `p5/p50 EV`
  - `max_drawdown`
  - `ulcer_index`
  - `avg_hold_bars`
  - `forced_exit_ratio`
  - `information_failure_ratio`
  - `time_failure_ratio`
- `POST /validation/report` 응답에 `strategy_v2_validation`을 추가하고, 기본 validation markdown에도 `Strategy v2 Mode Comparison` 섹션을 삽입
- 별도 템플릿 `reports/validation/strategy_v2_validation_<SYMBOL>_<VERSION>_<UTC>.md`를 생성하도록 연결
- 관련 회귀 테스트와 living 문서를 Iteration #48 기준으로 동기화

### 왜 그렇게 판단했는가
- 전략 v2의 핵심 운영 메시지는 `A-only가 기본 배포 모드`라는 점인데, 그 근거가 execution/exit 메타데이터와 같은 계약 위에서 자동 집계되지 않으면 이후 lock/stress 비교도 해석이 흔들림
- PBO/DSR 전체 구현 전에라도, 첫 비교 축을 현재 데이터 계약으로 먼저 잠가 두는 편이 다음 validation 항목을 순차적으로 붙이기 가장 안전함

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `108 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #49
### 무엇을 발견했는가
- `docs/STRATEGY_V2_BLUEPRINT.md`는 전략의 단일 참조 청사진이지만, 일부 문구가 이미 구현된 런타임 계약과 맞지 않았음
- 특히 `implementation pending`, acceptance/rejection 판정 문구, `Range Rotation` live entry, `BTC 우선`, `dead session`/`same thesis 해석 실수 2회` 같은 항목이 `설계 목표`와 `현재 자동화`를 구분하지 못하고 있었음

### 무엇을 수정했는가
- 청사진 문서를 `설계 목표 + 현재 구현 메모` 구조로 정리
- 현재 코드 기준으로 오해 소지가 큰 항목을 바로잡음
  - acceptance/rejection tentative 단계
  - `Range Rotation` research-only
  - exit engine의 자동 추론 범위
  - shock 대응의 실제 구현 범위
  - thesis primary symbol 선정 규칙
  - `dead session`, `same thesis 해석 실수 2회`의 비자동화 상태
- 연동 문서도 같이 갱신
  - `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md`
  - `docs/STRATEGY_V2_IMPLEMENTATION_CHECKLIST.md`
  - `docs/CHECKLIST.md`
  - `docs/PLAN.md`
  - `docs/CONTEXT_NOTE.md`
  - `docs/STRATEGY_OPERATING_MANUAL.md`
  - `docs/UPGRADE_ROADMAP_VNEXT.md`

### 왜 그렇게 판단했는가
- 이 단계의 목적은 새 기능 추가보다 “문서가 현재 코드를 정확히 설명하도록 만드는 것”에 있음
- 청사진이 과장된 상태로 남아 있으면 다음 validation/stress 비교 단계에서 운영 규칙과 하드 게이트를 잘못 해석하게 됨

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `108 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #50
### 무엇을 발견했는가
- validation 프로토콜의 두 번째 비교 축인 `transition/shock lock 적용 전후`는 문서에는 있었지만, 실제 validation 경로에는 아직 자동 비교 리포트가 없었음
- 현재 코드가 저장하는 메타데이터로는 `before/after`를 완전 재현할 수 없고, `transition 제거 + shock 계정 영향 clamp` 수준의 현재 계약 기반 근사가 필요했음

### 무엇을 수정했는가
- `StrategyV2LockValidationService`를 추가해 saved plan metadata 기준 `before_lock` vs `after_lock` 비교를 계산
- `POST /validation/report` 응답에 `strategy_v2_lock_validation`을 추가하고, 기본 validation markdown에도 `Transition / Shock Lock Comparison` 섹션을 삽입
- 별도 템플릿 `reports/validation/strategy_v2_lock_validation_<SYMBOL>_<VERSION>_<UTC>.md`를 생성하도록 연결
- 관련 회귀 테스트와 living 문서를 Iteration #50 기준으로 동기화

### 왜 그렇게 판단했는가
- 이 비교 축의 목적은 현재 lock 계약이 계정 하방에 어떤 영향을 주는지 먼저 보는 데 있고, 완전한 counterfactual fill simulation이 없더라도 saved metadata 기준 근사를 먼저 잠그는 편이 다음 validation 축으로 넘어가기에 더 안전함
- 특히 transition은 `trade 제거`, shock은 `size clamp`라는 현재 런타임 의미를 validation에서도 같은 언어로 보여줘야 운영 판단이 맞는다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `110 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #51
### 무엇을 발견했는가
- validation 프로토콜의 세 번째 비교 축인 `thesis dedupe 적용 전후`는 문서에는 있었지만, 실제 validation 경로에는 아직 자동 비교 리포트가 없었음
- 이 비교 축은 심볼 단위가 아니라 포트폴리오 단위여야 하므로, 기존 `symbol-only recent plans` 재사용으로는 의미 있는 결과가 나오지 않았음

### 무엇을 수정했는가
- `StrategyV2ThesisValidationService`를 추가해 글로벌 `closed v2 plans` 기준 `before_dedupe` vs `after_dedupe` 비교를 계산
- 현재 계약 기준 근사를 고정함
  - later overlapping same-thesis trade 제거
  - active thesis cluster cap 초과 trade 제거
  - ENTRY fill 시각 우선, 없으면 `valid_from` 폴백
- `POST /validation/report` 응답에 `strategy_v2_thesis_validation`을 추가하고, 기본 validation markdown에도 `Thesis Dedupe Comparison` 섹션을 삽입
- 별도 템플릿 `reports/validation/strategy_v2_thesis_validation_<SYMBOL>_<VERSION>_<UTC>.md`를 생성하도록 연결
- 관련 회귀 테스트와 living 문서를 Iteration #51 기준으로 동기화

### 왜 그렇게 판단했는가
- `One thesis, one risk`는 포트폴리오 규칙이므로, validation도 글로벌 closed plans를 같은 계약으로 재구성해야 실제 운영 하방을 설명할 수 있음
- full counterfactual portfolio replay 없이도, 저장된 thesis/fill 메타데이터를 이용해 dedupe가 drawdown에 미치는 방향성을 먼저 잠가 두는 편이 다음 stress/PBO 축으로 넘어가기에 안전함

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `112 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #52
### 무엇을 발견했는가
- validation 프로토콜의 다섯 번째 비교 축인 `baseline cost vs stressed cost`는 문서에는 있었지만, 실제 validation 경로에는 아직 자동 비교 리포트가 없었음
- `final_exit_realized_r`는 fee/entry slippage를 자동 포함하지 않기 때문에, saved closed plan만 그대로 쓰면 stress 비교가 비용 축을 제대로 반영하지 못했음

### 무엇을 수정했는가
- `StrategyV2StressValidationService`를 추가해 `baseline_cost` vs `stressed_cost` 비교를 계산
- 현재 계약 기준 근사를 고정함
  - `execution_fills`가 있으면 actual fee + entry slippage 우선
  - 없으면 `plan.cost_est`를 fee/slippage component로 분해해 폴백
  - stress multiplier는 고정값 `cost x1.5`, `slippage x2`
- `POST /validation/report` 응답에 `strategy_v2_stress_validation`을 추가하고, 기본 validation markdown에도 `Stressed Cost Comparison` 섹션을 삽입
- 별도 템플릿 `reports/validation/strategy_v2_stress_validation_<SYMBOL>_<VERSION>_<UTC>.md`를 생성하도록 연결
- 관련 회귀 테스트와 living 문서를 Iteration #52 기준으로 동기화

### 왜 그렇게 판단했는가
- stress 비교의 목적은 현재 비용 계약이 하방에 얼마나 민감한지 먼저 보는 데 있고, full order-book replay 없이도 saved plan/fill 메타데이터만으로 현재 운영 위험을 충분히 근사할 수 있음
- 이 축을 먼저 잠가 두면 이후 `latency +1 bar`, `partial fills only`, `shock concentration` 같은 stress 시나리오도 같은 validation 경로에 순차적으로 붙일 수 있음

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `114 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)

## 2026-03-07 Iteration #53
### 무엇을 발견했는가
- validation 프로토콜에는 `PBO/DSR` 명세가 이미 고정돼 있었지만, 실제 runtime validation 경로에는 이를 보여주는 계약이 없어서 문서와 API 사이에 공백이 있었음
- 현 시점 데이터 저장 구조로는 `CSCV/PBO`, `DSR` 수치 계산을 바로 붙이기 어렵고, 설계 readiness와 blocker를 먼저 노출하는 편이 더 정확했음

### 무엇을 수정했는가
- `StrategyV2PboDsrDesignService`를 추가해 `design_ready / available / implementation_status / blocked_by / next_steps` payload와 markdown 템플릿을 생성하도록 연결
- `POST /validation/report` 응답에 `strategy_v2_pbo_dsr_design`을 추가하고, 기본 validation markdown에도 `PBO / DSR Design Status` 섹션을 삽입
- 회귀 테스트(`tests/test_strategy_v2_pbo_dsr_design.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #53 기준으로 동기화

### 왜 그렇게 판단했는가
- 아직 계산되지 않은 PBO/DSR을 계산된 것처럼 노출하면 validation 해석 자체가 왜곡된다
- 반대로 설계 contract를 지금 고정해 두면, 이후 artifact store와 fold ranking 저장이 들어와도 runtime/API/report 스키마를 다시 흔들지 않고 순차 확장할 수 있다

### 최신 검증 스냅샷
- 전체 테스트 실행 결과: `115 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-07 Iteration #54
### 무엇을 발견했는가
- 실전 운영 체크리스트는 문서에 있었지만, 실제로는 `/health/ready`, `/validation/report`, `/alerts/metrics`, `/portfolio/budget`, `/metrics/strategy`를 운영자가 따로 열어 봐야 했음
- 특히 `POST /alerts/test`는 자동 실행하면 부작용이 있으므로, 자동화와 수동 확인 항목을 분리한 집계가 필요했음

### 무엇을 수정했는가
- `OperationalChecklistService`를 추가해 `health/validation/alerts/outbox/risk/portfolio/execution/PBO-DSR design`을 단일 payload와 markdown으로 집계
- `POST /operations/checklist`와 `scripts/generate_operational_checklist_report.py`를 추가
- 최근 알림 테스트는 `AlertSubscription(type=test)` 이력만 보고, 없으면 blocking `MANUAL`로 처리하도록 계약을 고정
- 관련 회귀 테스트(`tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #54 기준으로 동기화

### 왜 그렇게 판단했는가
- 운영 점검은 “데이터가 있는가”보다 “지금 출발 가능한가”를 빠르게 판단하는 게 중요하므로, 분산된 근거를 한 곳에 모아야 한다
- 반대로 실제 채널 테스트를 endpoint가 자동으로 날리게 만들면 운영 부작용이 생기므로, 최근 성공 이력 기반 `MANUAL`/`PASS` 구분이 더 안전하다

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `3 passed` (`.venv/bin/pytest -q tests/test_operational_checklist.py tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `117 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-07 Iteration #55
### 무엇을 발견했는가
- validation 프로토콜의 stress test 항목에는 `latency +1 bar`, `partial fills only`, `shock regime concentration`이 있었지만, 실제 런타임은 `cost x1.5 / slippage x2`만 계산하고 있었음
- 현재 저장 구조로는 full replay가 어렵기 때문에, `plan/fill/candle` 메타데이터 기반 근사를 먼저 같은 stress payload 안에 붙이는 편이 현실적이었음

### 무엇을 수정했는가
- `StrategyV2StressValidationService`를 확장해 `latency_plus_1_bar`, `partial_fills_only`, `shock_concentration` 시나리오를 추가
- `POST /validation/report`와 stress markdown에 `scenario_metrics`, `scenario_comparison`, `scenario_summary`, `worst_scenario`, `scenario_statuses`를 노출
- 회귀 테스트(`tests/test_strategy_v2_stress_validation.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #55 기준으로 동기화

### 왜 그렇게 판단했는가
- stress 축은 기존 validation 경로 안에서 같은 계약으로 비교돼야 해석이 단순해지고, 이후 full replay로 바꿔도 API/리포트 스키마를 다시 흔들지 않아도 된다
- full replay가 없는 현재 단계에서는 `근사 규칙을 명시하고 방향성만 본다`는 태도가 가장 정확하다

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `4 passed` (`.venv/bin/pytest -q tests/test_strategy_v2_stress_validation.py tests/test_validation_report.py tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `117 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-07 Iteration #56
### 무엇을 발견했는가
- `PBO/DSR` 명세는 validation/runtime에 있었지만, 실제 trial/fold/snapshot artifact를 저장하거나 조회하는 DB 계약이 없어서 다음 계산 단계로 넘어갈 준비도가 부족했음
- 특히 `design payload`의 `available=false`와 `artifact store 존재 여부`가 같은 의미로 섞이면 운영 해석이 틀어질 수 있었음

### 무엇을 수정했는가
- `validation_trial_runs`, `validation_trial_fold_scores`, `validation_pbo_dsr_snapshots` 테이블과 `ValidationArtifactRepository`를 추가
- `StrategyV2PboDsrArtifactStoreService`, `GET /validation/pbo-dsr/artifact-store`, `POST /validation/report`의 `strategy_v2_pbo_dsr_artifact_store` payload를 추가
- `strategy_v2_pbo_dsr_design`가 artifact store 상태를 상위 요약으로 반영하도록 수정
- 회귀 테스트(`tests/test_strategy_v2_pbo_dsr_artifact_store.py`, `tests/test_strategy_v2_pbo_dsr_design.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #56 기준으로 동기화

### 왜 그렇게 판단했는가
- `PBO/DSR` 계산은 후행 단계지만, runtime artifact contract가 먼저 고정되지 않으면 이후 CSCV/PBO/DSR 계산을 붙일 때 API/리포트/운영 해석이 다시 흔들리게 됨
- 현재 단계에서 중요한 것은 “계산 완료”가 아니라 “빈 artifact store도 정상 상태로 해석되는가”를 고정하는 일임

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `6 passed` (`.venv/bin/pytest -q tests/test_strategy_v2_pbo_dsr_artifact_store.py tests/test_strategy_v2_pbo_dsr_design.py tests/test_validation_report.py tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `120 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-07 Iteration #57
### 무엇을 발견했는가
- `daily/session lock`은 이미 구현되어 있었지만, 운영 체크리스트에는 현재 세션이 live preferred window인지 `dead session`인지 보여주는 항목이 없었음
- 그 결과 운영자는 `risk gate`가 OPEN이어도 지금이 런던/뉴욕 세션인지, dead session 경고 상황인지 한 번에 읽을 수 없었음

### 무엇을 수정했는가
- `OperationalChecklistService`에 `session_guidance` 항목을 추가해 `current_session`, `preferred_windows_utc`, `dead_session`, `session_lock_active`를 evidence로 노출
- 활성 London/New York 세션은 `PASS`, dead session과 session lock active는 non-blocking `WARN`으로 고정
- 회귀 테스트(`tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #57 기준으로 동기화

### 왜 그렇게 판단했는가
- 문서가 요구한 것은 `dead session hard block`이 아니라 `운영 체크리스트에서 지금 세션 해석을 바로 보게 하는 것`이었음
- hard block을 새로 넣으면 기존 `risk_gate_open` 계약과 책임이 겹치므로, 이번 단계는 guidance-only로 붙이는 편이 정확함

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `4 passed` (`.venv/bin/pytest -q tests/test_operational_checklist.py tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `121 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #58
### 무엇을 발견했는가
- stress validation은 이미 여러 근사 시나리오를 계산하고 있었지만, 언제 full replay 대체를 진지하게 추진해야 하는지 판단하는 런타임 계약이 없었음
- 특히 `execution_fills` lineage, `latency` 참고 캔들 커버리지, shock 비중이 부족한 상태와 실제로 replay 우선순위가 높은 상태가 한 문장으로 섞이면 운영 판단이 틀어질 수 있었음

### 무엇을 수정했는가
- `StrategyV2StressReplayAssessmentService`를 추가해 `full_replay_ready`, `replacement_recommended`, coverage, degraded/catastrophic scenario evidence, deployment recommendation을 하나의 payload로 고정
- `GET /validation/stress-replay-assessment`, `POST /validation/report`, validation markdown, standalone markdown 리포트에 같은 계약을 연결
- 회귀 테스트(`tests/test_strategy_v2_stress_replay_assessment.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #58 기준으로 동기화

### 왜 그렇게 판단했는가
- 현재 단계에서 필요한 건 full replay 구현 자체보다, “지금 근사를 계속 써도 되는가”와 “언제 replay 대체를 우선순위로 올릴 것인가”를 분리해 보여주는 것임
- 이 판단 축이 먼저 고정돼야 다음 단계인 `PBO / DSR metric 계산 루프`나 stress writer lineage 확장도 같은 validation 언어 위에서 붙일 수 있음

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `6 passed` (`.venv/bin/pytest -q tests/test_strategy_v2_stress_replay_assessment.py tests/test_validation_report.py tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `123 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #59
### 무엇을 발견했는가
- `PBO/DSR`는 design/artifact payload까지는 있었지만, seeded trial/fold artifact가 있어도 실제 metric을 계산해 snapshot으로 남기는 런타임 루프가 없었음
- 그래서 validation report가 준비도는 말할 수 있어도, `PBO < 0.35`, `DSR > 0` gate를 같은 경로에서 해석할 수는 없었음

### 무엇을 수정했는가
- `StrategyV2PboDsrMetricsService`를 추가해 seeded `validation_trial_runs` / `validation_trial_fold_scores`에서 `PBO`, `DSR`, selected trial summary, deployment recommendation을 계산
- 계산 결과를 `validation_pbo_dsr_snapshots`에 upsert하고, `strategy_v2_pbo_dsr_artifact_store`, `strategy_v2_pbo_dsr_design`, `strategy_v2_pbo_dsr_metrics`를 validation/API/운영 체크리스트에 같이 연결
- `GET /validation/pbo-dsr`, validation markdown의 `PBO / DSR Metrics` 섹션, 회귀 테스트(`tests/test_strategy_v2_pbo_dsr_metrics.py`, `tests/test_strategy_v2_pbo_dsr_design.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #59 기준으로 동기화

### 왜 그렇게 판단했는가
- 지금 단계에서 중요한 건 trial/fold writer를 완성하는 것보다, seeded artifact가 들어왔을 때 validation 언어가 실제 수치와 snapshot lineage까지 닫히는 것임
- 이 계산 루프를 먼저 붙여야 다음 단계에서 writer 자동화와 session/dead-session gate 승격을 해도 validation 해석이 다시 흔들리지 않음

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `7 passed` (`.venv/bin/pytest -q tests/test_strategy_v2_pbo_dsr_metrics.py tests/test_strategy_v2_pbo_dsr_design.py tests/test_validation_report.py tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `126 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #60
### 무엇을 발견했는가
- `session_guidance`는 운영 체크리스트에서만 보였고, 실제 scanner/portfolio 후보에는 같은 세션 판단과 penalty가 노출되지 않았음
- 이 상태에서는 dead-session 경고가 운영 문서에는 있으나, 후보 랭킹과 portfolio 후보 검토 화면에는 연결되지 않아 해석이 끊겨 있었음

### 무엇을 수정했는가
- `SessionGuidanceService`를 추가해 checklist, scanner, portfolio overlay가 같은 `current_session / dead_session / session_lock_active / preferred_windows_utc / soft_penalty` 계약을 공유하도록 정리
- `GET /scanner/top`, `GET /portfolio/budget` 후보 row에 `session_guidance`, `session_penalty`를 추가하고, `dead session` / `session lock active`는 hard block이 아닌 ranking-only soft penalty로만 반영
- 회귀 테스트(`tests/test_session_guidance.py`, `tests/test_portfolio_overlay.py`, `tests/test_portfolio_budget_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #60 기준으로 동기화

### 왜 그렇게 판단했는가
- 이번 단계의 목적은 dead session을 막는 것이 아니라, 동일한 세션 해석을 운영 체크리스트와 후보 선별 경로에 동시에 보이게 만드는 것임
- hard block까지 올리면 기존 `risk_gate_open` / `operating_lock` 책임과 충돌하므로, 현재 단계에서는 candidate-level soft penalty가 더 정확함

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `14 passed` (`.venv/bin/pytest -q tests/test_session_guidance.py tests/test_portfolio_overlay.py tests/test_portfolio_budget_report.py tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `129 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #61
### 무엇을 발견했는가
- `strategy_v2_stress_replay_assessment`는 있었지만, full replay 전환에 필요한 입력 lineage가 어느 정도 준비됐는지 따로 보여주는 runtime 계약이 없었음
- 그래서 `replacement_recommended`가 떠도 실제 부족한 것이 `execution fill`, `latency candle`, `full candle path` 중 무엇인지 바로 구분하기 어려웠음

### 무엇을 수정했는가
- `StrategyV2StressReplayLineageService`를 추가해 `closed v2 trades + execution_fills + 5m candles` 기준으로 `runtime_inputs_ready`, `coverage`, `gap_counts`, `fill_path`, `candle_path`, `blocked_by`, `next_steps`를 계산
- `GET /validation/stress-replay-lineage`, validation markdown의 `Stress Replay Lineage` 섹션, `POST /validation/report`의 `strategy_v2_stress_replay_lineage` payload를 추가해 같은 lineage 계약을 API/리포트/엔진에 공통 반영
- 관련 회귀 테스트(`tests/test_strategy_v2_stress_replay_lineage.py`, `tests/test_strategy_v2_stress_replay_assessment.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #61 기준으로 동기화

### 왜 그렇게 판단했는가
- full replay 전환은 assessment만으로는 부족하고, 실제 writer/runtime input이 어느 정도 준비됐는지 별도 lineage 계약이 먼저 고정돼야 다음 단계의 writer 연결과 runner 설계가 흔들리지 않음
- fallback anchor source를 숨기지 않고 드러내야, readiness를 과대평가하지 않고 정확한 후속 작업 우선순위를 잡을 수 있음

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `6 passed` (`.venv/bin/pytest -q tests/test_strategy_v2_stress_replay_lineage.py tests/test_strategy_v2_stress_replay_assessment.py tests/test_validation_report.py tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `131 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #62
### 무엇을 발견했는가
- `validation_trial_runs` / `validation_trial_fold_scores` schema와 metrics reader는 있었지만, `recompute_learning()`이 실제로 trial/fold row를 seed하지 않아 PBO/DSR가 운 좋게 seeded된 경우에만 계산되고 있었음
- 그래서 PBO/DSR는 계산 코드가 있어도 실전 validation 루프와 자동 연결됐다고 보기 어려웠음

### 무엇을 수정했는가
- `StrategyV2PboDsrTrialWriterService`를 추가해 `closed v2 trades`에서 `mode_policy`, `lock_policy`, `stress_policy` runtime proxy trial/fold lineage를 자동 seed
- `recompute_learning()`과 `GET /validation/pbo-dsr`, `GET /validation/pbo-dsr/artifact-store`가 `writer -> metrics -> artifact/design` 순서를 공유하도록 연결
- `GET /validation/pbo-dsr/trial-writer`, validation markdown의 `PBO / DSR Trial Writer` 섹션, 회귀 테스트(`tests/test_strategy_v2_pbo_dsr_trial_writer.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #62 기준으로 동기화

### 왜 그렇게 판단했는가
- 이번 단계의 핵심은 threshold sweep 완성이 아니라, 현재 validation 루프가 artifact store를 스스로 seed하고 그 결과를 같은 API/report 언어로 해석하도록 닫는 것임
- proxy writer라도 자동 seed 경로가 먼저 고정돼야 다음 단계의 true threshold writer와 replay runner를 안정적으로 얹을 수 있음

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `11 passed` (`.venv/bin/pytest -q tests/test_strategy_v2_pbo_dsr_trial_writer.py tests/test_strategy_v2_pbo_dsr_metrics.py tests/test_strategy_v2_pbo_dsr_artifact_store.py tests/test_strategy_v2_pbo_dsr_design.py tests/test_validation_report.py tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `133 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #63
### 무엇을 발견했는가
- `strategy_v2_stress_replay_assessment`와 `strategy_v2_stress_replay_lineage`까지는 있었지만, 실제 full replay prototype job을 어떤 단위로 만들고 worker가 무엇을 입력/출력해야 하는지에 대한 공통 계약이 없었음
- 그래서 다음 단계 writer 연결을 하려면 매번 `scenario별 readiness`, `batch size`, `artifact target`을 임의 해석해야 했음

### 무엇을 수정했는가
- `StrategyV2StressReplayRunnerContractService`를 추가해 `stress_validation + stress_replay_lineage + stress_replay_assessment`를 묶은 `runtime_job_ready`, `scenario_contract`, `runner_contract`, `worker_input_contract`, `worker_output_contract` payload를 정의
- `GET /validation/stress-replay-runner-contract`, validation markdown의 `Stress Replay Runner Contract` 섹션, `POST /validation/report`의 `strategy_v2_stress_replay_runner_contract` payload를 추가해 같은 계약을 API/리포트/엔진에 공통 반영
- batching 관련 설정(`stress_replay_runner_target_trades_per_job`, `stress_replay_runner_min_trades_per_job`, `stress_replay_runner_max_parallel_jobs`)과 회귀 테스트(`tests/test_strategy_v2_stress_replay_runner_contract.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`) 및 living 문서를 Iteration #63 기준으로 동기화

### 왜 그렇게 판단했는가
- 이번 단계의 핵심은 replay worker 구현이 아니라, 다음 단계의 lineage writer와 runner가 같은 IO 언어를 쓰도록 계약을 먼저 고정하는 것임
- runner/worker contract가 없이 바로 writer를 붙이면 scenario별 readiness와 batching 규칙이 코드 경로마다 달라져 validation 해석이 다시 흔들릴 가능성이 높음

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `4 passed` (`.venv/bin/pytest -q tests/test_strategy_v2_stress_replay_runner_contract.py tests/test_validation_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `135 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #64
### 무엇을 발견했는가
- `strategy_v2_stress_replay_runner_contract`로 prototype job 계약은 정해졌지만, scenario별 trade row를 실제 artifact로 materialize하는 writer 경로가 없어 다음 단계 worker 구현이 여전히 수동 해석에 의존하고 있었음
- 그래서 validation에서는 readiness를 볼 수 있어도, future worker가 읽을 `batch input` 자체는 자동으로 남지 않았음

### 무엇을 수정했는가
- `StrategyV2StressReplayLineageService.trade_rows()` public contract를 추가해 per-trade replay lineage row를 추출 가능하게 했음
- `StrategyV2StressReplayLineageWriterService`를 추가해 `stress_replay_lineage + stress_replay_runner_contract` 기준 scenario별 batch artifact(JSON)를 `reports/validation/stress_replay_lineage_batches/...`에 materialize하도록 연결했음
- `GET /validation/stress-replay-lineage-writer`, validation markdown의 `Stress Replay Lineage Writer` 섹션, `POST /validation/report`의 `strategy_v2_stress_replay_lineage_writer` payload, 회귀 테스트(`tests/test_strategy_v2_stress_replay_lineage_writer.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #64 기준으로 동기화했음

### 왜 그렇게 판단했는가
- runner contract 다음 단계의 핵심은 replay를 돌리는 것이 아니라, future worker가 읽을 input artifact를 동일한 계약으로 남기는 것임
- 이 artifact writer가 먼저 고정돼야 이후 `threshold-sweep family` 확장이나 prototype replay worker 연결을 해도 scenario batch 기준이 흔들리지 않음

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `4 passed` (`.venv/bin/pytest -q tests/test_strategy_v2_stress_replay_lineage_writer.py tests/test_validation_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `137 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #65
### 무엇을 발견했는가
- `strategy_v2_pbo_dsr_trial_writer`는 `mode/lock/stress` runtime proxy 축만 seed하고 있어, PBO/DSR 설계 문서에 적은 threshold family가 validation artifact store에 반영되지 않고 있었음
- 그래서 `trial_writer -> metrics -> design/artifact_store` 경로는 닫혀 있어도, threshold family coverage를 API나 markdown에서 직접 해석할 수 없었음

### 무엇을 수정했는가
- `StrategyV2PboDsrTrialWriterService`를 확장해 `scoring_thresholds`, `transition_threshold`, `acceptance_rejection_thresholds`, `sizing_clamps` stored-plan threshold proxy family를 기존 runtime proxy trial 위에 추가 seed
- `threshold_parameter_families_present`, `candidate_trials_by_family`를 `GET /validation/pbo-dsr/trial-writer`와 `POST /validation/report`의 `strategy_v2_pbo_dsr_trial_writer` payload에 추가
- 회귀 테스트(`tests/test_strategy_v2_pbo_dsr_trial_writer.py`, `tests/test_strategy_v2_pbo_dsr_metrics.py`, `tests/test_strategy_v2_pbo_dsr_artifact_store.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #65 기준으로 동기화

### 왜 그렇게 판단했는가
- true parameter rerun runner가 아직 없는 상태에서, 가장 안전한 다음 단계는 `stored plan validity`를 활용해 threshold family coverage를 proxy universe로 먼저 넓히는 것임
- 이렇게 해야 artifact store와 PBO/DSR metric이 더 실제 설계에 가까운 trial universe를 읽으면서도, 아직 구현되지 않은 true sweep runner를 계산된 것처럼 과장하지 않게 됨

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `8 passed` (`.venv/bin/pytest -q tests/test_strategy_v2_pbo_dsr_trial_writer.py tests/test_strategy_v2_pbo_dsr_metrics.py tests/test_strategy_v2_pbo_dsr_artifact_store.py tests/test_validation_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `137 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #66
### 무엇을 발견했는가
- `stress_replay_lineage_writer`까지는 input batch artifact만 있고, 실제 replay worker output이 생겼을 때 이를 `strategy_v2_stress_validation` payload와 같은 언어로 비교하는 경로가 없었음
- 그래서 future worker를 붙여도 `approximation vs replay output` 차이를 validation report/API에서 바로 읽을 수 없었음

### 무엇을 수정했는가
- `StrategyV2StressReplayOutputArtifactsService`를 추가해 latest scenario별 replay worker output artifact를 읽고 `comparison_to_approximation`을 계산하도록 연결
- `GET /validation/stress-replay-output-artifacts` endpoint를 추가하고, `strategy_v2_stress_validation` payload에 `replay_output_artifacts`, `replay_output_comparison`을 붙였음
- `Validation Report`의 `Stressed Cost Comparison` 섹션, 회귀 테스트(`tests/test_strategy_v2_stress_replay_output_artifacts.py`, `tests/test_strategy_v2_stress_validation.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #66 기준으로 동기화

### 왜 그렇게 판단했는가
- 이번 단계의 핵심은 replay worker를 바로 구현하는 것이 아니라, output artifact가 생겼을 때 approximation과 같은 축으로 읽히는 비교 계약을 먼저 고정하는 것임
- 이 계약이 먼저 있어야 다음 단계에서 worker를 실제 실행 경로에 붙여도 validation payload와 운영 해석이 다시 바뀌지 않음

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `7 passed` (`.venv/bin/pytest -q tests/test_strategy_v2_stress_replay_output_artifacts.py tests/test_strategy_v2_stress_validation.py tests/test_validation_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `140 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #67
### 무엇을 발견했는가
- `stress_replay_runner_contract`와 `stress_replay_lineage_writer`까지는 준비됐지만, 실제 lineage batch artifact를 읽어 replay output artifact를 쓰는 실행 경로가 엔진/API/validation runtime에 없었음
- 그래서 `full replay prototype`이 문서상 준비된 것처럼 보여도, 운영자는 실제 output artifact를 생성하는 단일 실행 경로를 쓸 수 없었음

### 무엇을 수정했는가
- `StrategyV2StressReplayPrototypeWorkerService`를 추가해 lineage batch artifact를 읽고 scenario별 replay output artifact와 markdown을 실제로 쓰도록 연결
- `POST /validation/stress-replay-worker/prototype`, `POST /validation/report`의 `strategy_v2_stress_replay_prototype_worker`, `Validation Report`의 `Stress Replay Prototype Worker` 섹션을 추가
- 회귀 테스트(`tests/test_strategy_v2_stress_replay_prototype_worker.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #67 기준으로 동기화

### 왜 그렇게 판단했는가
- 이번 단계의 핵심은 true market replay가 아니라, 이미 고정된 lineage writer/runner contract를 실제 실행 경로로 한 번 닫아 주는 것이다
- 이 실행 경로가 먼저 있어야 다음 단계의 true threshold-sweep runner나 real replay worker를 붙여도 input/output artifact 계약을 다시 흔들지 않는다

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `4 passed` (`.venv/bin/pytest -q tests/test_strategy_v2_stress_replay_prototype_worker.py tests/test_validation_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `142 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #68
### 무엇을 발견했는가
- `strategy_v2_pbo_dsr_trial_writer`가 threshold family coverage를 넓히긴 했지만, runtime proxy lineage와 true threshold-sweep lineage를 같은 selection rule로 취급하면 artifact store와 metrics에서 source audit이 불가능했음
- `validation_trial_runs` ID도 긴 trial key가 많은 구간에서 truncation 충돌 여지가 있어, separated lineage를 붙이는 순간 PK 오염 리스크가 바로 드러났음

### 무엇을 수정했는가
- `StrategyV2PboDsrThresholdRunnerService`를 엔진/API/validation/report에 끝까지 연결하고, `GET /validation/pbo-dsr/threshold-runner`를 추가했음
- `ValidationArtifactRepository.replace_seed_for_selection_rules()`와 `selection_rule_counts()`를 기준으로 runtime proxy lineage와 true threshold lineage가 같은 artifact store 안에서 공존하도록 정리했음
- `trial_run_id` 생성 규칙을 `writer namespace + signed trial key + hash suffix`로 바꿔 PK 충돌을 제거했음
- `strategy_v2_pbo_dsr_artifact_store.selection_rule_counts`, `strategy_v2_pbo_dsr_metrics.selected_trial.writer_source`, `Validation Report`의 `PBO / DSR Threshold Runner` 섹션을 추가해 combined universe source audit을 직접 보이게 했음
- 회귀 테스트(`tests/test_strategy_v2_pbo_dsr_threshold_runner.py`, `tests/test_strategy_v2_pbo_dsr_trial_writer.py`, `tests/test_strategy_v2_pbo_dsr_artifact_store.py`, `tests/test_strategy_v2_pbo_dsr_design.py`, `tests/test_strategy_v2_pbo_dsr_metrics.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #68 기준으로 동기화했음

### 왜 그렇게 판단했는가
- 이번 단계의 핵심은 “threshold family가 있다”가 아니라, runtime proxy와 true threshold lineage가 실제 저장소/API/report에서 서로 구분되고 동시에 해석되는 것이다
- 이 분리가 안 되면 PBO/DSR selected trial이 어떤 lineage에서 나온 결과인지 설명할 수 없고, 다음 단계 deployment gate 판단이 왜곡된다

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `13 passed` (`.venv/bin/pytest -q tests/test_strategy_v2_pbo_dsr_trial_writer.py tests/test_strategy_v2_pbo_dsr_threshold_runner.py tests/test_strategy_v2_pbo_dsr_artifact_store.py tests/test_strategy_v2_pbo_dsr_design.py tests/test_strategy_v2_pbo_dsr_metrics.py tests/test_validation_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `144 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #69
### 무엇을 발견했는가
- `strategy_v2_stress_validation`은 replay worker output artifact를 payload에 붙여 보여주기만 하고, 실제 `deployment_recommendation`은 여전히 approximation 시나리오만으로 계산하고 있었음
- 그래서 replay output이 approximation보다 더 나쁜 경우에도 `worst_scenario`, `scenario_statuses`, 후속 `strategy_v2_stress_replay_assessment`가 그 증거를 gate에 반영하지 못했음

### 무엇을 수정했는가
- `StrategyV2StressValidationService`에 replay-backed gate 재평가를 추가해, replay output summary가 있는 scenario는 `deployment_recommendation.scenario_statuses[*].source=replay_output`로 승격되도록 수정
- `deployment_recommendation`에 `replay_gate_applied`, `replay_gate_reason`, `replay_scenarios_considered`, `scenario_sources`, `worst_scenario_source`를 추가
- `Validation Report`와 summary payload가 `worst_scenario_source`, `replay_gate_applied`, `replay_gate_reason`를 같이 노출하도록 반영
- 회귀 테스트(`tests/test_strategy_v2_stress_validation.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`, `tests/test_strategy_engine_ops.py`)와 living 문서를 Iteration #69 기준으로 동기화

### 왜 그렇게 판단했는가
- prototype replay worker를 붙인 뒤에도 deployment gate가 approximation만 본다면 replay artifact를 저장하는 의미가 약해진다
- 현재 단계에서 필요한 건 true market replay 완성이 아니라, `approximation + replay-backed override`를 같은 stress validation 계약 안에서 안정적으로 해석하게 만드는 것이다

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `8 passed` (`.venv/bin/pytest -q tests/test_strategy_v2_stress_validation.py tests/test_validation_report.py tests/test_api_smoke.py tests/test_strategy_engine_ops.py -q`)
- 전체 테스트 실행 결과: `146 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- py_compile 확인 완료: `app/services/strategy_v2_stress_validation.py`, `app/services/validation_report.py`, `tests/test_strategy_v2_stress_validation.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #70
### 무엇을 발견했는가
- 기존 `stress_replay_runner_contract.runtime_job_ready`는 prototype batch/worker 계약 준비 상태만 의미했는데, 문서와 운영 해석에서는 종종 true market replay runner 교체 준비와 섞여 읽힐 수 있었음
- `strategy_v2_stress_replay_assessment`도 full replay 필요성은 말해 주지만, stronger lineage threshold와 critical scenario replay-output coverage를 함께 본 별도 replacement gate는 없었음

### 무엇을 수정했는가
- `StrategyV2StressReplayAssessmentService`에 `true_runner_readiness`를 추가해 stronger execution/latency/path threshold, minimum compared scenarios, critical scenario replay-output coverage를 함께 평가하도록 확장
- `StrategyV2StressReplayRunnerContractService`가 `true_runner_readiness`를 그대로 소비하고, `runner_contract_defined_ready_for_true_market_runner` 상태를 별도 노출하도록 수정
- `strategy_engine._build_stress_replay_runtime_stack()`와 `stress_replay_assessment_report()`가 replay output artifacts까지 포함한 상태로 assessment를 생성하도록 정렬
- `Validation Report`, API schema, 회귀 테스트(`tests/test_strategy_v2_stress_replay_assessment.py`, `tests/test_strategy_v2_stress_replay_runner_contract.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`, `tests/test_strategy_engine_ops.py`)와 living 문서를 Iteration #70 기준으로 동기화

### 왜 그렇게 판단했는가
- prototype 실행 준비와 true runner 교체 준비를 같은 불리언으로 두면 운영 해석이 과장된다
- true market replay runner 교체는 더 강한 lineage 품질과 critical scenario replay coverage를 동시에 만족해야만 의미가 있으므로, 별도 readiness gate가 필요하다

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `7 passed` (`.venv/bin/pytest -q tests/test_strategy_v2_stress_replay_assessment.py tests/test_strategy_v2_stress_replay_runner_contract.py tests/test_validation_report.py tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `147 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- py_compile 확인 완료: `app/services/strategy_v2_stress_replay_assessment.py`, `app/services/strategy_v2_stress_replay_runner_contract.py`, `app/services/strategy_engine.py`, `app/services/validation_report.py`, `app/core/config.py`, `app/schemas/api.py`
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #71
### 무엇을 발견했는가
- `strategy_v2_pbo_dsr_metrics`는 `selection_rule_counts`와 `selected_trial.writer_source`를 이미 노출하고 있었지만, deployment recommendation은 이 lineage 차이를 실제 gate에 반영하지 않았음
- 추가로 `meets_protocol_gate` 계산이 `PBO value=0.0`을 falsy로 처리해 `pbo_status=PASS, dsr_status=PASS`인데도 `fail_validation_gate`로 내려가는 버그가 있었음

### 무엇을 수정했는가
- `StrategyV2PboDsrMetricsService`에 `lineage_audit` payload를 추가해 `runtime proxy` vs `true threshold` dual-lineage source audit을 단일 계약으로 고정
- dual-lineage가 공존하는데 selected trial이 runtime proxy에서 오면 `deployment_recommendation`을 `warn_lineage_audit` 또는 `warn_overfit_and_lineage_audit`로 내리도록 반영
- `Validation Report`, API schema, 회귀 테스트(`tests/test_strategy_v2_pbo_dsr_metrics.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #71 기준으로 동기화
- `meets_protocol_gate` 계산에서 `0.0` falsy 처리 버그를 수정해 minimum gate 판단이 실제 PBO/DSR 상태와 일치하도록 고정

### 왜 그렇게 판단했는가
- true threshold lineage가 이미 존재하는데 selected trial이 여전히 runtime proxy에서 왔다면, 수치가 통과해도 배포 해석은 더 보수적으로 내려야 함
- lineage audit이 gate에 반영되지 않으면 proxy lineage와 true threshold lineage가 공존하는 이유를 운영자가 deployment 단계에서 놓치게 됨
- `0.0` falsy 버그를 먼저 바로잡지 않으면 lineage audit 테스트와 실제 gate 해석이 모두 왜곡됨

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `6 passed` (`.venv/bin/pytest -q tests/test_strategy_v2_pbo_dsr_metrics.py tests/test_validation_report.py tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `149 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- py_compile 확인 완료: `app/services/strategy_v2_pbo_dsr_metrics.py`, `app/services/validation_report.py`, `app/schemas/api.py`
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #72
### 무엇을 발견했는가
- replay output artifact가 deployment gate를 override하긴 했지만, approximation과 얼마나 벌어지면 별도 정책 경고/실패로 볼지에 대한 고정된 기준이 없었음
- 그래서 replay-backed scenario가 자체 수치상 PASS여도 approximation과 심하게 다르면 운영자가 그 괴리를 별도 위험으로 읽을 수 없었음

### 무엇을 수정했는가
- `Settings`에 `stress_replay_divergence_warn/fail_ev_delta`, `stress_replay_divergence_warn/fail_max_drawdown_delta`를 추가하고 changelog 추적 대상에 포함
- `StrategyV2StressValidationService`에 replay-backed scenario별 `divergence_status`, `divergence_reason`, `divergence_axes`, `divergence_thresholds` 계산을 추가
- divergence가 threshold를 넘으면 scenario 자체가 PASS여도 `WARN/FAIL`로 승격하고, `deployment_recommendation`에 `divergence_gate_applied`, `divergence_problem_scenarios`, `divergence_fail_scenarios`, `divergence_warn_scenarios`, `worst_divergence_scenario`를 반영
- `Validation Report`, 회귀 테스트(`tests/test_strategy_v2_stress_validation.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #72 기준으로 동기화

### 왜 그렇게 판단했는가
- replay output을 gate에 반영하는 것과 approximation 대비 괴리를 정책적으로 해석하는 것은 다른 문제다
- approximation과 replay 결과가 계속 크게 벌어지면, replay-backed scenario 자체가 PASS여도 현재 근사 모델을 실전 배포 판단에 그대로 쓰는 것은 위험하다
- divergence threshold를 별도 정책축으로 고정해야 이후 true market replay runner lineage와 threshold lineage를 같은 배포 판정으로 묶을 수 있다

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `6 passed` (`.venv/bin/pytest -q tests/test_strategy_v2_stress_validation.py tests/test_validation_report.py tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `150 passed, 1 skipped` (`.venv/bin/pytest -q -rs`)
- py_compile 확인 완료: `app/services/strategy_v2_stress_validation.py`, `app/services/validation_report.py`, `app/core/config.py`, `app/services/parameter_changelog.py`
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #73
### 무엇을 발견했는가
- `true_runner_readiness`와 `strategy_v2_pbo_dsr_metrics.lineage_audit`가 각각 따로 노출돼 있어서, 실제 true market replay runner 승격 가능 여부를 운영자가 한 payload에서 바로 판단하기 어려웠음
- 특히 `true_runner_ready=true`여도 selected trial이 runtime proxy에서 왔으면 승격을 막아야 하는데, 기존 `strategy_v2_stress_replay_assessment.deployment_recommendation`에는 그 결합 gate가 없었음

### 무엇을 수정했는가
- `StrategyV2StressReplayAssessmentService`가 `pbo_dsr_metrics`를 같이 받아 `deployment_recommendation.true_runner_promotion_*`를 계산하도록 확장
- `true_runner_promotion_ready/action/reason`, `threshold_lineage_audit_status/reason`, `selected_trial_writer_source/selection_rule`를 같은 deployment contract로 묶음
- `StrategyEngine._build_stress_replay_runtime_stack()`이 assessment에 `pbo_dsr_metrics`를 같이 전달하도록 정리
- `Validation Report`, 회귀 테스트(`tests/test_strategy_v2_stress_replay_assessment.py`, `tests/test_strategy_engine_ops.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #73 기준으로 동기화

### 왜 그렇게 판단했는가
- true runner replacement readiness와 threshold lineage provenance는 운영 의미가 다르지만, 최종 배포 action에서는 함께 해석돼야 한다
- base stress decision을 그대로 두고 actual promotion action을 별도 필드로 분리해야, `full replay가 필요함`과 `지금 true market runner로 승격 가능한가`를 동시에 명확히 볼 수 있다
- 이 결합 gate가 없으면 prototype-only 상태와 true runner promotion 차단 이유가 deployment 단계에서 흐려진다

### 최신 검증 스냅샷
- 타깃 테스트 실행 결과: `9 passed` (`./.venv/bin/pytest -q tests/test_strategy_v2_stress_replay_assessment.py tests/test_strategy_engine_ops.py tests/test_validation_report.py tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `151 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #74
### 무엇을 발견했는가
- `selection_universe_size`는 있었지만, 현재 DSR가 쓰는 combined artifact universe와 true threshold lineage가 대표하는 full parameter-sweep universe가 분리 기록되지 않았음
- 그래서 다음 단계의 Sharpe bias adjustment를 바꾸기 전에, 어떤 우주 크기를 지금 쓰고 있는지와 어떤 우주 크기를 앞으로 써야 하는지를 payload에서 바로 볼 수 없었음

### 무엇을 수정했는가
- `StrategyV2PboDsrMetricsService`에 `selection_universe_summary`를 추가해 combined/runtime-proxy/true-threshold/full-parameter-sweep universe를 분리 기록
- snapshot payload와 `StrategyV2PboDsrArtifactStoreService`에도 같은 `selection_universe_summary`를 반영
- selected trial metadata에 `selection_universe_basis`, `lineage_selection_universe_size`, true-threshold lineage용 `full_parameter_sweep_selection_universe_size`를 기록
- `Validation Report`, 회귀 테스트(`tests/test_strategy_v2_pbo_dsr_artifact_store.py`, `tests/test_strategy_v2_pbo_dsr_metrics.py`, `tests/test_strategy_v2_pbo_dsr_trial_writer.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #74 기준으로 동기화

### 왜 그렇게 판단했는가
- 다음 단계는 DSR bias adjustment 기준을 바꾸는 일인데, 그 전에 universe count 자체가 split recording으로 고정돼 있어야 해석이 흔들리지 않는다
- 이번 단계는 계산식을 바꾸는 것이 아니라 lineage/metrics/report가 같은 숫자를 보도록 만드는 단계다
- `combined_artifact_universe`와 `full_parameter_sweep_universe`를 한 필드에 섞어두면 이후 gate 변경 때 회귀 위험이 커진다

### 최신 검증 스냅샷
- PBO/DSR 타깃 회귀 실행 완료 (`./.venv/bin/pytest -q tests/test_strategy_v2_pbo_dsr_artifact_store.py tests/test_strategy_v2_pbo_dsr_metrics.py tests/test_strategy_v2_pbo_dsr_trial_writer.py tests/test_strategy_v2_pbo_dsr_threshold_runner.py tests/test_validation_report.py tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `151 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #75
### 무엇을 발견했는가
- `selection_universe_summary`는 이미 split recording을 하고 있었지만, DSR bias adjustment는 여전히 `combined_artifact_universe`를 기준으로 계산하고 있었음
- 그래서 true threshold lineage가 존재해도 `best-trial Sharpe`의 deflation 강도가 실제 threshold-sweep universe보다 더 큰 combined artifact universe를 참조하고 있었고, active basis와 legacy basis를 payload에서 직접 비교할 수도 없었음

### 무엇을 수정했는가
- `StrategyV2PboDsrMetricsService`가 `full_parameter_sweep_selection_universe_size`를 우선 사용해 DSR bias adjustment를 계산하도록 변경
- `dsr.selection_universe_basis`, `legacy_combined_selection_universe_size`, `legacy_combined_benchmark_sharpe`, `benchmark_sharpe_delta_vs_legacy_combined`, `bias_adjustment_rechecked`를 추가
- snapshot / `selection_universe_summary` / markdown report / validation summary가 같은 active basis를 쓰도록 정렬
- 회귀 테스트(`tests/test_strategy_v2_pbo_dsr_metrics.py`, `tests/test_strategy_v2_pbo_dsr_trial_writer.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #75 기준으로 동기화

### 왜 그렇게 판단했는가
- split recording만 있고 active bias adjustment가 old basis에 머물면 다음 deployment gate 해석이 반쯤만 업데이트된 상태가 된다
- 이번 단계의 목적은 DSR 계산이 실제 threshold lineage와 같은 universe language를 쓰게 만드는 것이고, 동시에 legacy combined benchmark를 남겨 회귀를 바로 비교할 수 있게 하는 것이다
- true threshold lineage가 없는 경우에는 fallback을 유지해야 기존 artifact-only 심볼에서 계산 공백이 생기지 않는다

### 최신 검증 스냅샷
- PBO/DSR 타깃 회귀 실행 결과: `8 passed` (`./.venv/bin/pytest -q tests/test_strategy_v2_pbo_dsr_metrics.py tests/test_strategy_v2_pbo_dsr_trial_writer.py tests/test_validation_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `151 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #76
### 무엇을 발견했는가
- `true_runner_promotion_*`와 `selected_trial source audit`는 이미 연결돼 있었지만, 실제 replay worker output provenance는 별도 payload에 흩어져 있어서 deployment summary에서 직접 비교되지 않았음
- 그래서 replay output이 충분히 쌓여도 selected trial이 runtime proxy인지 true threshold인지와, 그 replay output lineage가 어떤 입력 배치를 통해 만들어졌는지를 한 번에 읽기 어려웠음

### 무엇을 수정했는가
- `StrategyV2StressReplayPrototypeWorkerService`가 worker output artifact에 `input_lineage_summary`를 기록하도록 확장
- `StrategyV2StressReplayOutputArtifactsService`에 root `lineage_summary`를 추가해 `worker_modes`, `compared_scenarios`, `input_batch_count`, `input_trade_rows`를 집계
- `StrategyV2StressReplayAssessmentService`에 `replay_output_lineage_alignment_*`를 추가해 replay output lineage와 selected-trial source audit를 같은 deployment contract로 결합
- selected trial이 runtime proxy인데 replay output lineage가 실제로 존재하면 promotion reason이 `replay_output_lineage_alignment:*`로 직접 고정되도록 변경
- `Validation Report`, API smoke, replay worker/output/assessment 회귀 테스트와 living 문서를 Iteration #76 기준으로 동기화

### 왜 그렇게 판단했는가
- 다음 배포 승인 단계에서는 단순히 `selected_trial_from_runtime_proxy=true`만 보는 것보다, 실제 replay output provenance가 존재하는 상황에서의 mismatch를 더 직접 보여줘야 운영 해석이 정확하다
- replay output lineage가 summary에 없으면 deployment review가 다시 여러 endpoint를 수동으로 합쳐 읽어야 한다
- 이 단계는 true market replay runner 완성이 아니라, replay evidence와 threshold lineage provenance를 같은 승인 언어로 묶는 단계다

### 최신 검증 스냅샷
- stress replay 타깃 회귀 실행 결과: `11 passed` (`./.venv/bin/pytest -q tests/test_strategy_v2_stress_replay_prototype_worker.py tests/test_strategy_v2_stress_replay_output_artifacts.py tests/test_strategy_v2_stress_replay_assessment.py tests/test_validation_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `151 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #77
### 무엇을 발견했는가
- `selected_trial lineage`와 `replay-derived worst scenario`는 각각 payload에 있었지만, 승인 템플릿에서는 따로 흩어져 보여서 최종 배포 검토 시 수동 교차 확인이 필요했음
- 특히 true-threshold winner인지 runtime proxy winner인지와, replay-backed worst scenario가 무엇이고 어떤 상태인지가 같은 summary에 없어서 approval review 흐름이 끊겨 있었음

### 무엇을 수정했는가
- `StrategyV2StressReplayAssessmentService`에 `deployment_recommendation.approval_cross_display`를 추가해 `threshold_lineage_winner_*`와 `replay_derived_worst_scenario_*`를 한 payload로 묶음
- `ValidationReportService`에 `deployment_approval_summary`와 `## Deployment Approval Template` 섹션을 추가해 같은 정보를 validation markdown과 API summary에서 직접 읽게 만듦
- 회귀 테스트(`tests/test_strategy_v2_stress_replay_assessment.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #77 기준으로 동기화

### 왜 그렇게 판단했는가
- 다음 배포 승인 단계의 핵심은 lineage winner와 replay-backed downside evidence를 한 번에 읽는 것이지, 여러 요약을 따로 비교하는 것이 아니다
- 이번 단계는 경고 문구를 더 세게 만드는 것이 아니라, approval template에 필요한 두 축을 같은 언어로 나란히 고정하는 단계다
- 이 교차 표시가 먼저 있어야 다음 단계의 proxy-warning 고정이나 top-summary 문구 강화도 안정적으로 붙는다

### 최신 검증 스냅샷
- stress approval 타깃 회귀 실행 결과: `6 passed` (`./.venv/bin/pytest -q tests/test_strategy_v2_stress_replay_assessment.py tests/test_validation_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `151 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #84
### 무엇을 발견했는가
- approval template의 `playbook_go_no_go/code/action/message`는 validation report 안에는 있었지만, `validation_alert` payload 경로에는 아직 복사되지 않아 alert 저장 payload와 outbox payload에서 같은 운영 문구를 바로 읽을 수 없었음
- 그래서 alert 기반 운영 경로는 one-line summary는 공유해도 playbook action은 다시 validation report를 열어 확인해야 했음

### 무엇을 수정했는가
- `StrategyEngine._maybe_emit_validation_alert`가 `approval_playbook_go_no_go/code/action/message`를 cooldown payload, emitted payload, 저장 payload, retry payload, outbox event payload에 함께 싣도록 수정함
- 회귀 테스트(`tests/test_validation_alerts.py`, `tests/test_api_smoke.py`)를 보강해 `validation_report.deployment_approval_summary.playbook_* == validation_alert.approval_playbook_*` 계약을 고정함
- living 문서를 Iteration #84 기준으로 동기화하고 다음 단일 포커스를 `portfolio budget/report` 배포 언어 반영으로 갱신함

### 왜 그렇게 판단했는가
- validation alert는 운영자가 validation report를 열기 전 먼저 보는 경로이므로, go/no-go playbook 문구도 같은 payload에 있어야 한다
- one-line summary만 보내고 playbook mapping을 따로 두면 운영자가 다시 해석해야 하므로, 이번 단계에서 report와 alert payload의 승인 언어를 동일하게 맞추는 편이 맞다
- 이번 단계는 새 승인 로직을 추가한 것이 아니라, 이미 계산된 approval template playbook mapping을 alert 경로까지 확장한 것이다

### 최신 검증 스냅샷
- validation alert payload 타깃 회귀 실행 결과: `4 passed` (`./.venv/bin/pytest -q tests/test_validation_alerts.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `154 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #85
### 무엇을 발견했는가
- scanner와 operations checklist는 이미 `deployment_go_no_go/code/message`를 top-level로 노출했지만, `GET /portfolio/budget`와 portfolio markdown summary는 아직 `risk_state/risk_reason`만 보여줘 운영 언어가 분리돼 있었음
- 그래서 포트폴리오 화면/리포트를 먼저 보면 같은 상태를 다시 해석해야 했음

### 무엇을 수정했는가
- `PortfolioBudgetReportService`가 scanner와 같은 runtime deployment language helper를 재사용해 `deployment_go_no_go/code/message`를 top-level payload와 markdown summary에 추가하도록 수정함
- API 응답 모델(`PortfolioBudgetReportOut`)과 회귀 테스트(`tests/test_portfolio_budget_report.py`, `tests/test_api_smoke.py`)를 현재 계약에 맞게 갱신함
- living 문서를 Iteration #85 기준으로 동기화하고 다음 단일 포커스를 `validation alert payload의 deployment language를 alert metrics/ops checklist evidence에도 직접 반영`으로 갱신함

### 왜 그렇게 판단했는가
- 포트폴리오 리포트는 후보를 집행하기 전 먼저 보는 상위 요약이므로, scanner/ops와 다른 언어를 쓰면 운영자가 다시 해석해야 한다
- 이번 단계의 목적은 새 게이트 추가가 아니라, 이미 있는 runtime deployment language를 포트폴리오 요약까지 확장해 같은 운영 언어로 정렬하는 것이다

### 최신 검증 스냅샷
- portfolio deployment language 타깃 회귀 실행 결과: `3 passed` (`./.venv/bin/pytest -q tests/test_portfolio_budget_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `154 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #86
### 무엇을 발견했는가
- `validation_alert`에는 approval summary와 playbook mapping이 들어가 있었지만, scanner/portfolio/ops와 같은 `deployment_go_no_go/code/message` 언어는 아직 없었고, `alerts/metrics`와 `operations/checklist` evidence에서도 직접 읽히지 않았음
- 그래서 운영자는 alert 경로와 metrics/ops evidence 경로 사이에서 다시 의미를 해석해야 했음

### 무엇을 수정했는가
- `StrategyEngine._maybe_emit_validation_alert`가 `deployment_go_no_go/code/message`를 cooldown payload, emitted payload, 저장 payload, retry payload, outbox event payload에 함께 싣도록 수정함
- `AlertMetricsService`에 `latest_validation_alert` summary를 추가해 최근 validation alert의 deployment language와 approval one-line summary를 top-level evidence로 노출함
- `OperationalChecklistService`가 `validation_alert_delivery.evidence`와 `alert_channel_slo.evidence.latest_validation_alert`에 deployment language를 직접 노출하도록 수정함
- 회귀 테스트(`tests/test_validation_alerts.py`, `tests/test_alert_metrics.py`, `tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #86 기준으로 동기화함

### 왜 그렇게 판단했는가
- deployment language는 운영자가 경로마다 다시 해석하면 안 되는 공통 언어이므로, alert payload와 metrics/ops evidence 모두 같은 필드를 직접 보여줘야 한다
- 이번 단계는 새 게이트를 추가한 것이 아니라, 이미 계산된 배포 언어를 alert 기반 운영 경로 전체로 확장한 것이다

### 최신 검증 스냅샷
- alert deployment evidence 타깃 회귀 실행 결과: `9 passed` (`./.venv/bin/pytest -q tests/test_validation_alerts.py tests/test_alert_metrics.py tests/test_operational_checklist.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `155 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #87
### 무엇을 발견했는가
- `alerts/metrics.latest_validation_alert`는 deployment language와 one-line summary는 보여줬지만, playbook mapping은 아직 직접 노출하지 않아 alert metrics 경로에서 `NO_GO`의 운영 행동 문구를 바로 읽을 수 없었음
- 그래서 `alert_channel_slo.evidence.latest_validation_alert`도 playbook action 없이 deployment code까지만 보여주는 상태였음

### 무엇을 수정했는가
- `AlertMetricsService._latest_validation_alert_summary`에 `approval_playbook_go_no_go/code/action/message`를 추가하고, alert metrics markdown에도 같은 필드를 출력하도록 수정함
- `OperationalChecklistService`는 기존처럼 `latest_validation_alert` summary를 그대로 쓰되, 그 summary가 이제 playbook mapping까지 포함하도록 간접 확장됨
- 회귀 테스트(`tests/test_alert_metrics.py`, `tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #87 기준으로 동기화함

### 왜 그렇게 판단했는가
- alert metrics는 운영자가 최근 validation alert의 품질과 의미를 빠르게 보는 경로이므로, deployment code만 있고 playbook action이 없으면 다시 validation report를 열어야 한다
- 이번 단계는 새 판단을 만든 것이 아니라, 이미 alert payload에 있는 playbook mapping을 alert metrics summary까지 끌어올린 것이다

### 최신 검증 스냅샷
- alert metrics playbook 타깃 회귀 실행 결과: `6 passed` (`./.venv/bin/pytest -q tests/test_alert_metrics.py tests/test_operational_checklist.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `155 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #88
### 무엇을 발견했는가
- `/portfolio/budget`는 이미 top-level `deployment_go_no_go/code/message`를 노출하고 있었지만, `operations/checklist`의 `portfolio_headroom.evidence`는 여전히 `current_exposure`와 `blocked_reason_counts`만 보여줘 checklist 경로에서 같은 배포 언어를 바로 읽을 수 없었음

### 무엇을 수정했는가
- `OperationalChecklistService._portfolio_item`의 source fields와 evidence에 `deployment_go_no_go/code/message`를 추가함
- 회귀 테스트(`tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)를 보강해 checklist portfolio evidence가 `/portfolio/budget` 배포 언어를 직접 포함하는지 고정함
- living 문서를 Iteration #88 기준으로 동기화하고 다음 단일 포커스를 notification formatter summary 검토로 갱신함

### 왜 그렇게 판단했는가
- checklist는 운영자가 여러 경로를 합쳐 보는 최종 대시보드 성격이라, `/portfolio/budget`의 배포 언어를 다시 찾아가면 의미가 약해진다
- 이번 단계는 새 판단을 만든 것이 아니라, 이미 계산된 portfolio deployment language를 checklist evidence까지 끌어온 것이다

### 최신 검증 스냅샷
- portfolio evidence 타깃 회귀 실행 결과: `6 passed` (`./.venv/bin/pytest -q tests/test_operational_checklist.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `156 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #89
### 무엇을 발견했는가
- validation alert 채널 메시지는 `approval=` one-line summary는 보여줬지만, `GO / NO_GO / MANUAL_REVIEW` 배포 언어는 메시지 본문에서 바로 읽을 수 없었음
- 운영자는 알림만 보고 판단할 때 다시 payload나 report를 열어 deployment status를 확인해야 했음

### 무엇을 수정했는가
- `NotificationDispatcher._format_message`가 validation alert 메시지에 `deployment=<go_no_go>/<code>` 또는 `deployment=<go_no_go>`를 직접 포함하도록 수정함
- 회귀 테스트(`tests/test_notification_dispatcher.py`, `tests/test_validation_alerts.py`)를 보강해 formatter와 실제 외부 전송 메시지 모두 이 계약을 따르는지 고정함
- living 문서를 Iteration #89 기준으로 동기화하고 다음 단일 포커스를 `validation_alert_delivery evidence`의 playbook mapping 검토로 갱신함

### 왜 그렇게 판단했는가
- alert 메시지는 운영자가 가장 먼저 보는 경로라서, one-line approval summary와 별도로 배포 언어도 즉시 보여줘야 한다
- 이번 단계는 새 배포 판단을 만든 것이 아니라, 이미 payload에 있는 deployment language를 채널 메시지까지 확장한 것이다

### 최신 검증 스냅샷
- notification deployment 타깃 회귀 실행 결과: `10 passed` (`./.venv/bin/pytest -q tests/test_notification_dispatcher.py tests/test_validation_alerts.py`)
- 전체 테스트 실행 결과: `156 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #81
### 무엇을 발견했는가
- approval template은 `warning_code`를 노출하고 있었지만, 운영자가 바로 읽을 수 있는 `GO / NO_GO / MANUAL_REVIEW` 문구로는 아직 변환되지 않았음
- 그래서 승인 템플릿과 `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md` 사이를 사람이 다시 해석해야 했고, `proxy warning`이 실제로 `NO_GO`인지 문서화된 계약이 부족했음

### 무엇을 수정했는가
- `ValidationReportService`에 `playbook_go_no_go/code/action/message` 매핑 helper를 추가함
- `deployment_approval_summary`와 markdown `Deployment Approval Template`에 같은 playbook 필드를 출력하도록 연결함
- `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md`에 warning code별 `GO / NO_GO / MANUAL_REVIEW` 운영 행동 표를 추가함
- 회귀 테스트(`tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #81 기준으로 동기화함

### 왜 그렇게 판단했는가
- 다음 단계는 approval template top-level 문구를 scanner/ops checklist 배포 판단과 같은 언어로 맞추는 작업이므로, 그 전에 warning code가 먼저 운영 문구로 고정돼 있어야 한다
- status/code만 노출하면 운영자는 다시 해석해야 하고, 그 순간 수동 실수가 들어간다
- 이번 단계는 새 게이트를 만드는 것이 아니라, 기존 경고 계약을 운영 playbook 언어로 번역해 승인 템플릿에서 바로 읽게 만드는 단계다

### 최신 검증 스냅샷
- approval playbook mapping 타깃 회귀 실행 결과: `3 passed` (`./.venv/bin/pytest -q tests/test_validation_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `152 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #82
### 무엇을 발견했는가
- approval template은 이미 `GO / NO_GO / MANUAL_REVIEW`로 번역할 수 있었지만, `topline_message`는 여전히 별도 표현을 쓰고 있었고 `operations/checklist`, `scanner`는 같은 배포 언어를 노출하지 않았음
- 그래서 validation 승인 문구와 운영 화면/후보 리스트의 live 판단이 서로 다른 말로 보일 수 있었음

### 무엇을 수정했는가
- `ValidationReportService`의 `deployment_approval_summary.topline_message`를 `GO / NO_GO / MANUAL_REVIEW` prefix 언어로 정렬함
- `OperationalChecklistService`에 `deployment_go_no_go/code/message`를 추가해 validation approval summary와 operational blocking/warn 상태를 같은 배포 언어로 합성함
- `ScannerService` row에 `deployment_go_no_go/code/message`를 추가해 `risk_gate/operating_lock` 상태를 같은 언어로 노출함
- 회귀 테스트(`tests/test_validation_report.py`, `tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #82 기준으로 동기화함

### 왜 그렇게 판단했는가
- 다음 단계에서 validation alert payload에도 approval summary를 실어 보내려면, validation/ops/scanner가 먼저 같은 배포 언어를 써야 한다
- 운영자가 화면마다 다른 prefix를 읽으면 같은 상태를 다르게 해석하게 된다
- 이번 단계는 새 판단 축을 추가한 것이 아니라, 기존 판단을 하나의 운영 언어로 통일한 단계다

### 최신 검증 스냅샷
- deployment language alignment 타깃 회귀 실행 결과: `6 passed` (`./.venv/bin/pytest -q tests/test_validation_report.py tests/test_operational_checklist.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `152 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #83
### 무엇을 발견했는가
- approval template one-line summary는 validation report 안에만 있었고, `validation_alert` payload와 실제 채널 메시지에는 같은 요약이 실리지 않았음
- 추가로 alert row ID가 초 단위 timestamp 기반이라 같은 초에 두 번 test alert를 만들면 `UNIQUE` 충돌이 날 수 있었음

### 무엇을 수정했는가
- `StrategyEngine._maybe_emit_validation_alert`에 `approval_topline_summary_line`를 추가해 validation alert payload, cooldown payload, retry payload, event payload가 같은 one-line summary를 공유하도록 변경함
- `NotificationDispatcher._format_message`가 `approval=<topline_summary_line>`를 메시지에 포함하도록 확장함
- alert ID 생성에 `uuid` 기반 helper를 도입해 validation/test/webhook/manual alert의 충돌 가능성을 제거함
- 회귀 테스트(`tests/test_validation_alerts.py`, `tests/test_notification_dispatcher.py`, `tests/test_strategy_engine_ops.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #83 기준으로 동기화함

### 왜 그렇게 판단했는가
- 다음 단계에서 playbook mapping까지 alert payload에 실으려면, 먼저 one-line summary가 alert 저장/재시도/실제 메시지까지 같은 계약으로 흘러야 한다
- report만 summary를 알고 alert는 모르면 운영자는 다시 링크를 열어야 하고, 알림의 실전 가치가 떨어진다
- alert ID 충돌은 타깃 회귀에서 실제로 드러난 flaky bug라서 이번 단계에서 같이 제거하는 편이 맞다

### 최신 검증 스냅샷
- validation alert summary 타깃 회귀 실행 결과: `15 passed` (`./.venv/bin/pytest -q tests/test_validation_alerts.py tests/test_notification_dispatcher.py tests/test_strategy_engine_ops.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `154 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #79
### 무엇을 발견했는가
- approval template에 warning 필드는 있었지만, `replay_output_lineage_alignment_*` 경고가 최상단 승인 문구에 직접 연결되지 않아 운영자가 먼저 세부 필드를 읽어야 했음
- 그래서 승인 템플릿의 첫 문장이 아직 결정적이지 않았고, alignment warning이 실제로는 뒤쪽 상세 필드에만 머물러 있었음

### 무엇을 수정했는가
- `ValidationReportService`가 `deployment_approval_summary.topline_status/code/message`를 생성하도록 확장함
- `replay_output_lineage_alignment_status/reason`과 `approval_warning_*`를 합성해 approval template 최상단 문구를 직접 생성하도록 변경함
- markdown `Deployment Approval Template` 상단에 `topline_*`를 출력하도록 추가함
- 회귀 테스트(`tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #79 기준으로 동기화함

### 왜 그렇게 판단했는가
- 다음 단계는 여러 승인 축을 한 줄로 압축하는 작업이므로, 그 전에 top-level 승인 문구가 이미 alignment warning을 직접 반영하고 있어야 한다
- 지금 단계의 목적은 새 gate를 만드는 것이 아니라, 기존 alignment warning을 승인 템플릿의 첫 문장으로 승격하는 것이다
- 이 정렬이 없으면 운영자는 여전히 세부 필드를 뒤져야 하고, approval template의 top-level 의미가 약하다

### 최신 검증 스냅샷
- approval topline 타깃 회귀 실행 결과: `2 passed` (`./.venv/bin/pytest -q tests/test_validation_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `151 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #80
### 무엇을 발견했는가
- `topline_status/code/message`는 생겼지만, threshold lineage winner / replay-derived worst scenario / true-runner promotion action이 최상단 승인 문구에서 항상 한 줄로 정리되지는 않았음
- 그래서 운영자가 여전히 세 축을 빠르게 비교하려면 개별 필드를 같이 읽어야 했음

### 무엇을 수정했는가
- `ValidationReportService`에 `deployment_approval_summary.topline_summary_line`을 추가함
- `winner / worst / promotion` 세 축을 항상 포함하는 one-line summary를 만들고, `topline_message`도 같은 축을 포함하도록 정렬함
- markdown `Deployment Approval Template`에 `topline_summary_line`을 출력하도록 추가함
- 회귀 테스트(`tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #80 기준으로 동기화함

### 왜 그렇게 판단했는가
- 다음 단계는 warning code를 운영 playbook 문구와 매핑하는 작업이므로, 그 전에 approval template가 이미 세 축을 한 줄로 고정해서 보여줘야 한다
- 승인 템플릿의 첫 문장만 읽고도 핵심 결론을 알 수 있어야 운영 속도가 나온다
- 이번 단계는 새 판단 축을 추가한 것이 아니라, 기존 판단 축을 최상단 문구에 더 압축해서 노출한 것이다

### 최신 검증 스냅샷
- approval one-line summary 타깃 회귀 실행 결과: `2 passed` (`./.venv/bin/pytest -q tests/test_validation_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `151 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #78
### 무엇을 발견했는가
- approval template에 `threshold lineage winner`와 `replay-derived worst scenario`는 같이 보이기 시작했지만, runtime proxy winner 케이스의 경고 문구가 아직 상태값 해석에 의존하고 있었음
- 그래서 운영자는 `REVIEW`와 `runtime_proxy_winner_with_replay_worst_scenario`를 다시 해석해야 했고, 승인 금지 메시지가 템플릿에 직접 고정돼 있지 않았음

### 무엇을 수정했는가
- `StrategyV2StressReplayAssessmentService`에 `approval_cross_display.approval_warning_locked/code/message`를 추가함
- `runtime proxy winner + replay_output worst scenario` 조합이면 경고 문구를 approval template에 직접 고정하도록 변경함
- `ValidationReportService`의 `deployment_approval_summary`와 markdown `Deployment Approval Template`에 같은 경고 필드를 노출함
- 회귀 테스트(`tests/test_strategy_v2_stress_replay_assessment.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #78 기준으로 동기화함

### 왜 그렇게 판단했는가
- 다음 단계는 top-level 승인 문구 연결이므로, 그 전에 approval template 내부 경고가 먼저 결정적이고 일관된 문장으로 고정돼 있어야 한다
- `status/reason`만으로는 운영자가 다시 해석해야 하므로, runtime proxy selected-trial 위험은 별도 warning contract로 승격하는 편이 맞다
- 이번 단계는 gate를 바꾸는 것이 아니라, 기존 gate 해석을 approval template에서 더 직접적으로 보이게 만드는 단계다

### 최신 검증 스냅샷
- stress approval 타깃 회귀 실행 결과: `6 passed` (`./.venv/bin/pytest -q tests/test_strategy_v2_stress_replay_assessment.py tests/test_validation_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `151 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #90
### 무엇을 발견했는가
- `validation_alert_delivery.evidence`는 이미 `deployment_go_no_go/code/message`를 직접 노출하고 있었지만, 같은 위치에서 `approval_playbook_*`는 `validation_alert` 중첩 payload를 다시 열어야만 확인할 수 있었음
- 그래서 `alert_channel_slo.evidence.latest_validation_alert`와 달리, `validation_alert_delivery` 경로만 운영 행동 문구를 top-level에서 바로 읽지 못하는 계약 불일치가 남아 있었음

### 무엇을 수정했는가
- `OperationalChecklistService._validation_alert_evidence`에 `approval_playbook_go_no_go/code/action/message`를 top-level evidence 필드로 추가함
- 회귀 테스트(`tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)를 보강해 `validation_alert_delivery.evidence.approval_playbook_*` 계약을 고정함
- living 문서를 Iteration #90 기준으로 동기화하고 다음 단일 포커스를 `portfolio budget/report summary`의 playbook-style 운영 문구 검토로 갱신함

### 왜 그렇게 판단했는가
- `operations/checklist`는 여러 API를 합쳐 보는 최종 운영 경로라서, 동일한 validation alert 의미가 evidence 위치마다 다른 깊이로 노출되면 다시 사람이 해석해야 함
- 이번 단계는 새로운 승인 판단을 추가한 것이 아니라, 이미 계산된 playbook mapping을 `validation_alert_delivery` evidence까지 같은 수준으로 끌어올려 운영 언어를 정렬한 것임
- 다음 단계의 portfolio 운영 문구 검토도 같은 원칙, 즉 `top-level에서 즉시 읽히는 운영 언어`를 유지해야 안전하게 이어갈 수 있음

### 최신 검증 스냅샷
- validation-alert delivery evidence 타깃 회귀 실행 결과: `6 passed` (`./.venv/bin/pytest -q tests/test_operational_checklist.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `156 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #91
### 무엇을 발견했는가
- `/portfolio/budget`는 이미 `deployment_go_no_go/code/message`를 top-level로 노출하고 있었지만, 운영자가 바로 실행 행동을 읽을 수 있는 `playbook_*` 문구는 없었음
- 그래서 validation approval summary 쪽은 `playbook_action/message`까지 직접 보이는데, portfolio summary만 여전히 deployment code를 사람이 해석해야 하는 비대칭이 남아 있었음

### 무엇을 수정했는가
- `PortfolioBudgetReportService`에 runtime deployment code 기반 `playbook_go_no_go/code/action/message` 매핑을 추가함
- `GET /portfolio/budget` top-level payload와 portfolio markdown summary에 같은 playbook 필드를 노출함
- API 스키마와 회귀 테스트(`tests/test_portfolio_budget_report.py`, `tests/test_api_smoke.py`)를 갱신하고 living 문서를 Iteration #91 기준으로 동기화함

### 왜 그렇게 판단했는가
- 이 단계의 목적은 새 게이트를 만드는 것이 아니라, 이미 있는 portfolio deployment 판단을 운영 행동 문구로 즉시 읽히게 만드는 것임
- portfolio summary는 scanner 다음에 바로 보는 상위 요약이므로, deployment language만 있고 action이 없으면 다시 사람이 코드 의미를 해석해야 함
- validation approval playbook과는 source-of-truth가 다르므로, portfolio 쪽은 `deployment_code` 기반 별도 playbook으로 고정하는 편이 더 정확함

### 최신 검증 스냅샷
- portfolio playbook 타깃 회귀 실행 결과: `3 passed` (`./.venv/bin/pytest -q tests/test_portfolio_budget_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `156 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #92
### 무엇을 발견했는가
- review-type backlog가 세 갈래로 흩어져 있었음: validation alert 채널 메시지는 `playbook_action`이 없었고, `POST /alerts/test`는 manual drill에 쓴 playbook/deployment 필드를 top-level로 돌려주지 않았고, `operations/checklist.portfolio_headroom.evidence`는 portfolio playbook 문구를 직접 노출하지 않았음
- 그래서 같은 운영 문구를 채널 메시지, manual alert drill, checklist portfolio evidence에서 다시 해석해야 하는 계약 분산이 남아 있었음

### 무엇을 수정했는가
- `NotificationDispatcher._format_message`에 `playbook_action=<approval_playbook_action>` 출력을 추가함
- `StrategyEngine.send_test_alert`와 `AlertTestOut`에 `deployment_*`, `approval_playbook_*` top-level passthrough를 추가함
- `OperationalChecklistService._portfolio_item`에 `playbook_go_no_go/code/action/message` evidence/source 필드를 추가함
- 회귀 테스트(`tests/test_notification_dispatcher.py`, `tests/test_validation_alerts.py`, `tests/test_strategy_engine_ops.py`, `tests/test_operational_checklist.py`, `tests/test_portfolio_budget_report.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #92 기준으로 동기화함

### 왜 그렇게 판단했는가
- 사용자가 지적한 대로 review-type 항목은 따로따로 닫기보다 같은 운영 언어 계층에서 한 번에 정리하는 편이 더 맞음
- 이번 배치의 목적은 새 게이트를 만드는 것이 아니라, 이미 계산된 deployment/playbook 문구를 `채널 메시지 -> manual drill -> checklist evidence`까지 같은 수준으로 노출해 재해석 비용을 없애는 것이었음
- review-type backlog를 여기서 끊어두면 다음 단계부터는 다시 비검토 backlog로 넘어가도 계약이 흔들리지 않음

### 최신 검증 스냅샷
- review-type batch 타깃 회귀 실행 결과: `23 passed` (`./.venv/bin/pytest -q tests/test_notification_dispatcher.py tests/test_validation_alerts.py tests/test_strategy_engine_ops.py tests/test_operational_checklist.py tests/test_portfolio_budget_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `157 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #93
### 무엇을 발견했는가
- `operations/checklist`는 top-level `deployment_go_no_go/code/message`는 있었지만, validation/report/portfolio와 달리 top-level `playbook_*` 운영 액션 문구는 없었음
- 그래서 checklist 최상단 요약만 보면 승인 상태는 알 수 있어도, 운영자가 즉시 취해야 할 액션은 다시 하위 evidence나 validation report를 열어야 했음

### 무엇을 수정했는가
- `OperationalChecklistService._deployment_language`가 이제 `playbook_go_no_go/code/action/message`도 함께 생성하도록 확장함
- `POST /operations/checklist` payload와 markdown summary에 같은 playbook 필드를 추가함
- `OperationalChecklistOut` 스키마와 회귀 테스트(`tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)를 갱신하고 living 문서를 Iteration #93 기준으로 동기화함

### 왜 그렇게 판단했는가
- 지금 단계의 목적은 새 배포 게이트를 추가하는 것이 아니라, 이미 계산된 checklist 배포 판단을 validation/report/portfolio와 같은 수준의 운영 액션 문구로 즉시 읽히게 만드는 것임
- top-level summary contract가 경로마다 다른 깊이로 노출되면 운영자가 다시 해석해야 하므로, checklist도 같은 top-level playbook을 가져야 정합함
- 이 정리가 끝나야 다음 비검토 후속 작업으로 넘어가도 summary contract가 흔들리지 않음

### 최신 검증 스냅샷
- operations checklist playbook 타깃 회귀 실행 결과: `6 passed` (`./.venv/bin/pytest -q tests/test_operational_checklist.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `157 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-08 Iteration #94
### 무엇을 발견했는가
- `POST /alerts/test`는 이미 manual drill용 `deployment_*`, `approval_playbook_*`를 top-level로 반환하고 있었지만, `POST /alerts/subscribe`는 같은 payload를 저장만 하고 응답에서는 `alert_id/status`만 돌려줘 manual subscribe 경로의 contract가 끊겨 있었음
- 그래서 subscribe 경로만 운영 문구를 확인하려면 저장된 payload를 다시 열어야 했고, `alerts/test`와 `alerts/subscribe` 사이의 manual 경로 일관성이 부족했음

### 무엇을 수정했는가
- `AlertSubscribeOut`에 `deployment_*`, `approval_playbook_*` 필드를 추가함
- `POST /alerts/subscribe`가 저장된 payload에서 같은 필드를 top-level로 그대로 반환하도록 변경함
- API smoke와 living 문서를 Iteration #94 기준으로 동기화함

### 왜 그렇게 판단했는가
- 이번 단계의 목적은 새 판단을 만드는 것이 아니라, manual alert 경로 전체가 같은 deployment/playbook contract를 쓰도록 맞추는 것임
- `alerts/test`와 `alerts/subscribe`가 같은 수준의 운영 문구를 반환해야 수동 검증 경로에서 다시 payload를 파고들지 않아도 됨
- 이 정리가 끝나야 다음 단계에서 top-level contract 전체를 최종 정리할 수 있음

### 최신 검증 스냅샷
- alerts/subscribe smoke 회귀 실행 결과: `1 passed` (`./.venv/bin/pytest -q tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `157 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-09 Iteration #95
### 무엇을 발견했는가
- `POST /validation/report`는 approval/deployment/playbook 판단을 이미 계산하고 있었지만, top-level 응답에는 그 요약이 없어 `operations/checklist`와 다른 소비 경로가 nested payload를 다시 파고들어야 했음
- 그래서 validation/report/operations가 같은 배포 언어를 쓴다고 문서화돼 있어도, 실제 API contract는 `validation_report.deployment_approval_summary` 중심으로만 묶여 있었고 top-level 정렬이 덜 끝난 상태였음

### 무엇을 수정했는가
- `POST /validation/report` top-level에 `deployment_*`, `approval_topline_*`, `playbook_*` passthrough를 추가함
- `OperationalChecklistService`가 validation deployment/playbook 해석 시 top-level contract를 우선 소비하도록 정리하고, `validation_report` evidence에도 같은 top-level fields를 직접 노출함
- API smoke, operational checklist 회귀, living 문서를 Iteration #95 기준으로 동기화함

### 왜 그렇게 판단했는가
- 이번 단계의 목적은 새 판단을 만드는 것이 아니라, 이미 계산된 validation approval summary를 모든 운영 경로가 같은 깊이와 같은 이름으로 읽게 만드는 것임
- top-level contract가 없으면 `validation/report -> operations/checklist -> alert/manual path` 흐름에서 같은 의미를 서로 다른 중첩 깊이로 읽게 되어 계약 정합성이 약해짐
- nested summary는 source-of-truth로 남겨두되, 외부 API는 top-level passthrough를 주는 편이 운영/클라이언트 소비 안정성이 높음

### 최신 검증 스냅샷
- validation/ops 타깃 회귀 실행 결과: `7 passed` (`./.venv/bin/pytest -q tests/test_api_smoke.py tests/test_operational_checklist.py`)
- 전체 테스트 실행 결과: `158 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-09 Iteration #96
### 무엇을 발견했는가
- 핵심 엔진 기능 backlog는 사실상 닫혔는데, 계획서/로드맵/체크리스트에는 남은 항목이 아직 같은 레벨의 구현 과제처럼 남아 있었음
- 실제 남은 항목은 rollout blocker가 아니라 contract dedup/refactor 성격이라, 이 상태로 두면 다음 우선순위 해석이 과장될 수 있었음

### 무엇을 수정했는가
- 비검토 후속 backlog를 `배포 전 필수 0건 / 배포 후 리팩터 2건 / optional hold`로 재분류함
- `CHECKLIST`, `PLAN`, `UPGRADE_ROADMAP_VNEXT`, 운영/맥락 문서에 같은 분류를 반영하고 다음 단일 포커스를 `alert 경로 전반의 contract 중복 축소 여부 검토`로 고정함

### 왜 그렇게 판단했는가
- 남은 일을 feature backlog처럼 유지하면 rollout 판단이 불필요하게 보수적으로 흐른다
- 지금 필요한 건 새 기능 추가가 아니라, 이미 닫힌 contract 계층을 어떤 순서로 정리할지 명확히 고정하는 것이다

### 최신 검증 스냅샷
- docs-only backlog triage 단계라 코드 테스트 재실행은 생략함
- 직전 코드 기준선은 그대로 `158 passed, 1 skipped`

## 2026-03-09 Iteration #97
### 무엇을 발견했는가
- alert/test/subscribe/metrics/checklist/message formatter와 validation top-level consumer가 같은 deployment/playbook 의미를 쓰고 있었지만, fallback 규칙과 키 재매핑이 여러 군데에 흩어져 있었음
- 이 상태로 두면 rollout-blocking backlog는 닫혀 있어도, 후속 refactor 때 alert contract와 validation nested/top-level passthrough contract가 다시 어긋날 가능성이 있었음

### 무엇을 수정했는가
- `app/services/deployment_contracts.py`에 `approval_summary_passthrough`, `validation_report_contract`, `validation_alert_contract`, `alert_contract_defaults`를 고정하고, alert/validation/report/metrics/checklist/message formatter consumer를 같은 helper로 정리함
- `tests/test_deployment_contracts.py`를 추가해 plain `playbook_*`, nested summary fallback, manual-review default contract를 unit test로 잠금
- living 문서를 Iteration #97 기준으로 동기화하고, active rollout backlog / active post-rollout refactor backlog를 모두 `0`으로 정리함

### 왜 그렇게 판단했는가
- 지금 남은 일은 기능 추가가 아니라 contract drift를 줄이는 정리 작업이었고, 이 종류의 문제는 공통 helper와 단위 테스트가 가장 직접적인 해결책임
- validation summary는 source-of-truth로 남기되, alert/report consumer가 같은 fallback 규칙을 쓰게 해야 이후 live 운영 중 contract depth 차이로 인한 해석 오류를 막을 수 있음

### 최신 검증 스냅샷
- helper/alert/ops 타깃 회귀 실행 결과: `27 passed` (`./.venv/bin/pytest -q tests/test_deployment_contracts.py tests/test_api_smoke.py tests/test_operational_checklist.py tests/test_notification_dispatcher.py tests/test_alert_metrics.py tests/test_validation_alerts.py tests/test_strategy_engine_ops.py`)
- 전체 테스트 실행 결과: `162 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-09 Iteration #98
### 무엇을 발견했는가
- `POST /internal/binance/sync-universe`가 기존 최신 candle이 있는 상태에서 겹치는 과거 구간을 다시 받으면 `reverse timestamp detected`로 전체 심볼이 실패할 수 있었음
- 실제 사용 흐름상 demo/bootstrap 이후 실데이터 sync를 붙이는 경우가 흔해서, 이 동작은 운영 사용성을 과하게 해쳤음

### 무엇을 수정했는가
- `MarketDataService.backfill_from_binance()`가 fetched kline batch를 시간순으로 정렬한 뒤, 기존 최신 candle보다 오래된 overlap row는 자동 skip하도록 수정함
- 회귀 테스트 `tests/test_market_data_quality.py`에 overlap batch skip / all-older batch no-op 케이스를 추가함
- README/운영 매뉴얼/체크리스트 기준선을 현재 동작과 테스트 수치(`164 passed, 1 skipped`)에 맞춰 동기화함

### 왜 그렇게 판단했는가
- backfill은 재실행 가능(idempotent)해야 한다. 기존 데이터가 있다고 해서 historical overlap 때문에 전체 sync가 실패하면 운영 경로가 불안정해진다
- 진짜로 막아야 하는 것은 역순 실시간 스트림이지, 이미 저장된 최신 tail과 겹치는 역사 데이터가 아니다

### 최신 검증 스냅샷
- 타깃 회귀 실행 결과: `9 passed` (`./.venv/bin/pytest -q tests/test_market_data_quality.py tests/test_strategy_engine_ops.py`)
- 전체 테스트 실행 결과: `164 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)

## 2026-03-09 Iteration #99
### 무엇을 발견했는가
- 후보별 `예상 승률/예상 EV`는 내부 계산되고 있었지만, `plans/scanner/portfolio` top-level에는 직접 노출되지 않아 사용자가 숫자를 한 번에 읽기 어려웠음
- `thesis_cluster_cap_zero_risk` 같은 raw block reason은 사람이 바로 해석하기 어려웠음

### 무엇을 수정했는가
- `app/services/candidate_expectations.py`를 추가해 expectation contract와 block reason 문장 매핑을 공통화함
- `GET /plans/top`, `GET /scanner/top`, `GET /portfolio/budget`에 `expected_win_prob`, `expected_ev_r`, `expected_tp1/2/3_prob`, `expected_ev_at_recommended_size_r`, `expected_summary`, `block_reason_message`를 연결함
- 회귀 테스트(`tests/test_candidate_expectations.py`, `tests/test_plan_generator.py`, `tests/test_portfolio_overlay.py`, `tests/test_api_smoke.py`)와 living 문서를 Iteration #99 기준으로 동기화함

### 왜 그렇게 판단했는가
- 사용자는 `ev`, `rr_base`, `recommended_risk_r` raw 숫자만으로는 후보를 빠르게 해석하기 어렵다
- expectation contract와 blocker 문장을 같은 helper로 고정해야 `plans/scanner/portfolio`가 같은 언어를 유지할 수 있다

### 최신 검증 스냅샷
- 타깃 회귀 실행 결과: `14 passed` (`./.venv/bin/pytest -q tests/test_candidate_expectations.py tests/test_plan_generator.py tests/test_portfolio_overlay.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `166 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)

## 2026-03-09 Iteration #100
### 무엇을 발견했는가
- validation alert는 이미 자동화돼 있었지만, 실제 실시간 운용에 필요한 `near/touch/confirm/entry/tp/sl/partial_exit/closed` lifecycle alert는 subscribe contract와 fanout 경로가 닫혀 있지 않았음
- `alerts` 테이블이 subscription row와 emitted alert row를 같이 쓰는 구조라, cooldown lookup이 subscription row를 잘못 읽거나 같은 transaction 내 emitted row를 못 보고 중복 발송할 위험이 있었음

### 무엇을 수정했는가
- `POST /alerts/subscribe` 타입을 `near|touch|confirm|entry|tp|sl|partial_exit|closed`로 확장하고, subscription marker payload를 저장하도록 변경함
- `StrategyEngine.refresh_symbol`에 pre-entry signal alert 평가(`near/touch/confirm`)를 추가하고, `StrategyEngine.tv_webhook`, `StrategyEngine.ingest_execution_fill`이 matching subscription으로 lifecycle alert를 자동 fanout하도록 연결함
- `AlertRepository`에 matching subscription lookup / recent emitted cooldown lookup을 추가하고, emitted-row cooldown이 같은 transaction에서도 동작하도록 emit 직전 flush를 고정함
- 회귀 테스트(`tests/test_signal_alerts.py`, `tests/test_execution_fill_api.py`, `tests/test_api_smoke.py`, `tests/test_notification_dispatcher.py`)와 living 문서를 Iteration #100 기준으로 동기화함

### 왜 그렇게 판단했는가
- 현재 코드베이스의 가장 큰 실사용 병목은 분석 결과를 사용자가 계속 수동으로 polling해야 한다는 점이었다
- validation alert만 자동이고 signal/position lifecycle이 수동이면 반자동 운용 도구로서 연결이 끊긴다
- subscription row와 emitted row를 같은 저장소에서 관리할 때 cooldown/lookup 규칙을 먼저 고정하지 않으면, 채널 fanout을 붙인 뒤 duplicate alert가 운영 문제로 바로 드러난다

### 최신 검증 스냅샷
- signal alert 타깃 회귀 실행 결과: `16 passed` (`./.venv/bin/pytest -q tests/test_signal_alerts.py tests/test_execution_fill_api.py tests/test_api_smoke.py tests/test_notification_dispatcher.py tests/test_alert_metrics.py`)
- 전체 테스트 실행 결과: `170 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)

## 2026-03-09 Iteration #101
### 무엇을 발견했는가
- `expected_win_prob`가 표본 부족 시 거의 동일한 prior에 고정되어, 서로 다른 후보도 `46.1%`처럼 평평하게 보였음
- 이 상태에서는 `EV`와 `recommended_risk_r`가 달라도 사용자가 후보 차이를 직관적으로 읽기 어려웠음

### 무엇을 수정했는가
- `PlanGenerator`의 승률 fallback에 `strategy_family/grade`, `reaction_classification`, `entry_model`, `confluence`, `regime`, `friction`, `near_lp` 기반 보정항을 추가함
- `expected_tp1_prob`, `expected_tp2_prob`, `expected_tp3_prob`도 같은 보정 신호를 따라 미세 조정하도록 바꿨음
- `validity`에 `expected_win_prob_base`, `expected_win_prob_adjustment`, `expected_win_prob_components`를 저장하고, living 문서를 Iteration #101 기준으로 동기화함

### 왜 그렇게 판단했는가
- 표본 부족 구간에서 prior를 그대로 보여주면 모델이 안전해 보일 수는 있지만, 실사용자는 후보 간 차이를 읽지 못한다
- 지금 필요한 것은 완전히 새로운 분류기가 아니라, 기존 fallback이 `family/regime/reaction/confluence`를 반영해 약하게라도 순서를 만들도록 하는 것이다
- 보정 강도를 `reliability`에 연동하면 학습 표본이 충분한 구간에서는 기존 learned probability를 덜 훼손하고, 표본 부족 구간에서만 차별화를 강화할 수 있다

### 최신 검증 스냅샷
- expectation 타깃 회귀 실행 결과: `5 passed` (`./.venv/bin/pytest -q tests/test_plan_generator.py tests/test_candidate_expectations.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `171 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)

## 2026-03-09 Iteration #102
### 무엇을 발견했는가
- 현재 엔진은 반자동 fill ingest까지는 닫혀 있었지만, Binance signed order submit/query/cancel 경로가 없어 완전자동매매 1차로 넘어갈 최소 어댑터가 비어 있었음
- 로컬 `.env`에 Discord webhook이 들어간 뒤 일부 alert 회귀 테스트가 환경 의존적으로 깨질 수 있었음

### 무엇을 수정했는가
- `app/integrations/binance_futures.py`에 signed REST trade helper와 `submit_order/query_order/cancel_order`를 추가함
- `app/services/strategy_engine.py`에 normalized Binance order payload와 `plan_id` 기반 default `client_order_id` 생성을 추가함
- `POST/GET/DELETE /internal/binance/order`와 관련 API 스키마를 추가하고, 기본 submit은 `test order`, live submit/cancel은 `BINANCE_TRADE_LIVE_ENABLED=true` + `live=true` 이중 게이트로 잠금
- 회귀 테스트(`tests/test_binance_client.py`, `tests/test_binance_trade_api.py`)를 추가하고, 기존 alert 관련 테스트는 Discord env가 있더라도 환경 독립적으로 동작하도록 보강함
- living 문서를 Iteration #102 기준으로 동기화하고 다음 단일 포커스를 `Binance user-stream / 포지션 동기화(완전자동매매 2차)`로 갱신함

### 왜 그렇게 판단했는가
- 현재 단계에서 필요한 것은 완전한 자동매매 엔진 전체가 아니라, 실주문 경로를 안전하게 열 수 있는 최소 signed adapter다
- test order 기본값과 live mutation 이중 게이트가 없으면 로컬 실수 한 번이 바로 실거래로 이어질 수 있다
- 테스트는 로컬 채널 설정 유무와 무관하게 같은 결과를 내야 하므로, webhook 설정에 의존하는 회귀를 그대로 두는 것은 맞지 않았다

### 최신 검증 스냅샷
- Binance trade 타깃 회귀 실행 결과: `9 passed` (`./.venv/bin/pytest -q tests/test_binance_client.py tests/test_binance_trade_api.py tests/test_notification_dispatcher.py tests/test_validation_alerts.py`)
- 전체 테스트 실행 결과: `177 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 파라미터 changelog 수동 트리거 결과: `no_changes` (`./.venv/bin/python scripts/generate_parameter_changelog.py --trigger manual`)

## 2026-03-09 Iteration #103
### 무엇을 발견했는가
- 전략 지표는 이미 엔진 내부에 있었지만, 사용자는 `plans/scanner/validation` 여러 경로를 직접 조합해야 해서 현재 시장상태를 한 번에 읽기 어려웠음
- 차트/프론트엔드에서 바로 쓸 수 있는 구조화된 indicator payload도 별도 계약이 없었음

### 무엇을 수정했는가
- `app/services/strategy_indicators.py`를 추가해 `ContextSnapshot + active zones + top plans`를 기반으로 두 가지 뷰를 생성하도록 함
- `GET /indicators/summary`를 추가해 `headline`, `readable_lines`, `bias_label`, `momentum_label`, `risk_label`, `context`, `top_plan`, `top_zones`를 반환하도록 함
- `GET /indicators/chart`를 추가해 `price_panel`, `indicator_panel`, `zones`, `plans`, `annotations`를 반환하도록 함
- 새 endpoint 계약을 `tests/test_api_smoke.py`에 고정하고, living 문서를 Iteration #103 기준으로 동기화함

### 왜 그렇게 판단했는가
- 이 단계에서 필요한 것은 새 신호를 더 만드는 것이 아니라, 이미 계산된 전략 지표를 사람이 읽는 요약과 차트 친화적 payload로 정리하는 것이다
- 기존 엔진 계산을 재사용해야 전략 해석과 실제 집행 logic 사이에 추가 드리프트가 생기지 않는다
- summary view와 chart view를 분리하면 사람이 보는 운영 화면과 프론트/TradingView 브리지 소비 경로를 같은 source-of-truth로 묶을 수 있다

### 최신 검증 스냅샷
- API smoke 실행 결과: `1 passed` (`./.venv/bin/pytest -q tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `183 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)

## 2026-03-09 Iteration #110
### 무엇을 발견했는가
- 서버 source-of-truth는 여전히 `15m zone memory + 4h validity` 성격이 강해서, TradingView mirror를 짧게 줄여도 실제 플랜은 스캘핑 의도 대비 오래된 zone과 긴 window를 유지할 수 있었음
- session guidance는 overlay/checklist에는 있었지만, plan score / probability 단계에는 직접 들어가지 않았음

### 무엇을 수정했는가
- `scalp_zone_hard_max_age_hours=24`, `scalp_plan_validity_minutes=90`, session bias 관련 파라미터를 추가함
- `PlanGenerator`가 `24h` 초과 zone을 hard skip하고, `created_ts` 기반 age penalty / recent boost를 freshness에 반영하도록 바꿈
- `PlanGenerator`의 `valid_until`을 entry model / session 상태에 따라 `30~120m` 범위로 단축하고, validity에 `zone_age_hours`, `session_guidance_state`, `plan_validity_minutes`를 기록하도록 바꿈
- preferred session은 setup score / expected probability를 소폭 boost하고, dead session / session lock은 소폭 penalty를 주도록 plan scoring에 반영함
- `ZoneEngine`도 `24h` 초과 stale zone을 `expired` 처리하도록 맞춤
- 회귀 테스트(`tests/test_plan_generator.py`, `tests/test_zone_engine.py`)를 추가/보강함

### 왜 그렇게 판단했는가
- Pine mirror만 최근 zone으로 줄여도 서버 계획이 오래된 zone을 계속 만들면 사용감은 계속 어긋난다
- 스캘핑 의도에 맞추려면 시각화보다 먼저 서버 plan lifecycle 자체가 더 짧고 최근성에 민감해야 한다

### 최신 검증 스냅샷
- 타깃 회귀 실행 결과: `7 passed` (`./.venv/bin/pytest -q tests/test_plan_generator.py tests/test_zone_engine.py`)
- 전체 테스트 실행 결과: `187 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)

## 2026-03-09 Iteration #109
### 무엇을 발견했는가
- TradingView native mirror가 정보는 충분했지만, 스캘핑 차트에서 우선순위가 한눈에 들어오지 않아 실제 사용 시 읽기 부담이 컸음

### 무엇을 수정했는가
- Pine mirror에 `Dashboard mode` 입력을 추가하고 `Compact`/`Detailed` 두 모드를 분리함
- 기본 compact dashboard를 `State -> Bias -> Setup -> Entry -> Edge -> Score -> Zone` 순서로 재배치함
- best setup label도 3줄 핵심 정보(`direction/grade/model`, `entry-stop-tp1`, `p(win)/EV`)만 남기도록 단순화함
- 가이드와 README에 compact 모드 권장값과 읽는 순서를 추가함

### 왜 그렇게 판단했는가
- 스캘핑용 차트는 정보량보다 우선순위가 중요하다
- 서버 source-of-truth는 유지하되, TV mirror는 `지금 상태 / 지금 방향 / 지금 엔트리 가치`가 먼저 보여야 실제로 쓸 수 있다

### 최신 검증 스냅샷
- API smoke 실행 결과: `1 passed` (`./.venv/bin/pytest -q tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `183 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)

## 2026-03-09 Iteration #108
### 무엇을 발견했는가
- TradingView 실제 컴파일에서 `plotshape(text=activeGrade)`가 `series string`으로 평가돼 native mirror 스크립트가 다시 컴파일 실패했음

### 무엇을 수정했는가
- `scripts/tradingview/trading_engine_v1_mirror.pine`의 `plotshape` text를 동적 grade 문자열 대신 const 문자열 라벨(`L`, `S`)로 교체함
- `tests/test_api_smoke.py`에 `text=activeGrade` 비포함 계약을 추가함

### 왜 그렇게 판단했는가
- Pine의 `plotshape(text=...)`는 const string만 허용하므로, 등급 문자열을 그대로 붙이는 구조는 구조적으로 다시 깨질 수밖에 없다
- grade 정보는 별도 패널/라벨로 유지하고, shape text는 compile-safe marker로 단순화하는 편이 맞다

### 최신 검증 스냅샷
- API smoke 실행 결과: `1 passed` (`./.venv/bin/pytest -q tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `183 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)

## 2026-03-09 Iteration #107
### 무엇을 발견했는가
- TradingView 실제 컴파일에서 `math.tanh`, `ta.sum` 참조 오류가 발생해 native mirror 스크립트를 그대로 붙여넣을 수 없었음

### 무엇을 수정했는가
- `math.tanh`를 Pine-safe `squash()` 근사 함수로 교체함
- `ta.sum`을 고정 길이 bar aggregation으로 교체함
- `str.startswith` 의존도도 제거해 bias 판정을 명시적 equality 비교로 바꿈
- `tests/test_api_smoke.py`에 `math.tanh`, `ta.sum` 비포함 계약을 추가함

### 왜 그렇게 판단했는가
- Pine mirror는 TradingView 컴파일러 호환성이 우선이며, 서버 코드처럼 런타임 fallback이 없으므로 unsupported builtin을 남기면 사용성이 바로 깨진다
- 이 단계에서는 수학적 완전 동일성보다 compile-safe approximation이 더 중요하다

### 최신 검증 스냅샷
- API smoke 실행 결과: `1 passed` (`./.venv/bin/pytest -q tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `183 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)

## 2026-03-09 Iteration #106
### 무엇을 발견했는가
- TradingView native mirror를 추가한 뒤에도 차트 실사용 관점에서 confirmed-bar gating, alertcondition, dashboard 위치 조절 같은 compile/display 품질 요소가 아직 부족했음

### 무엇을 수정했는가
- `scripts/tradingview/trading_engine_v1_mirror.pine`에 confirmed-bar signal gating, dashboard position input, risk background toggle, marker toggle, native TradingView alert conditions(`Long/Short/Blocked`)를 추가함
- `tests/test_api_smoke.py`에 `GET /indicators/pine-script`의 alertcondition/입력 계약을 고정함
- `README.md`, `docs/TRADINGVIEW_PINE_MIRROR_GUIDE.md`, `docs/PLAN.md`, `docs/CHECKLIST.md`를 현재 mirror tuning 기준으로 동기화함

### 왜 그렇게 판단했는가
- Pine mirror는 서버와 달리 런타임 회귀 테스트가 제한적이므로, compile/display 리스크를 줄이는 방향으로 문법 보수성과 사용성부터 높이는 것이 맞음
- chart-side mirror는 false confidence를 줄여야 하므로, 미확정 바 신호 억제와 명시적 alertcondition 제공이 우선이다

### 최신 검증 스냅샷
- API smoke 실행 결과: `1 passed` (`./.venv/bin/pytest -q tests/test_api_smoke.py -q`)
- 전체 테스트 실행 결과: `183 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)
- 전체 테스트 실행 결과: `177 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)

## 2026-03-09 Iteration #104
### 무엇을 발견했는가
- Pine-style indicator payload와 Binance user-stream / position sync 2차 코드는 이미 반영돼 있었지만, living 문서와 운영 가이드가 아직 `Iteration #103` 기준에 머물러 있었음
- README와 운영 매뉴얼에는 여전히 Binance 주문 어댑터가 REST 1차까지만 구현된 것처럼 남아 있었고, `/indicators/pine`와 `websockets` 전제조건도 빠져 있었음

### 무엇을 수정했는가
- `docs/CHECKLIST.md`, `docs/PLAN.md`, `docs/CONTEXT_NOTE.md`, `docs/STRATEGY_OPERATING_MANUAL.md`, `README.md`를 `Iteration #104` 기준으로 동기화함
- 체크리스트에 `GET /indicators/pine`와 `Binance user-stream / 포지션 동기화 2차` 완료 항목을 추가하고, active backlog를 `없음`으로 정리함
- 운영/README 문서에 새 endpoint(`listen-key`, `user-stream/process`, `user-stream/event`, `positions/sync`, `positions`)와 `websockets` optional dependency, futures 이벤트 기준(`ORDER_TRADE_UPDATE`, `ACCOUNT_UPDATE`)을 명시함

### 왜 그렇게 판단했는가
- 이 단계에서 중요한 건 새 기능을 더 붙이는 것이 아니라, 이미 구현된 계약을 문서와 운영 경로에서 같은 기준으로 설명하는 것이다
- user-stream 2차가 구현된 상태에서 문서가 1차 상태를 가리키면, 운영자가 실제 기능보다 더 보수적으로 판단하거나 잘못된 전제조건으로 접근하게 된다

### 최신 검증 스냅샷
- 직전 전체 테스트 기준 유지: `183 passed, 1 skipped`
- optional dependency 참고: live Binance user-stream processing은 `pip install -e '.[integration]'` 또는 동등한 `websockets` 설치가 필요

## 2026-03-09 Iteration #105
### 무엇을 발견했는가
- `GET /indicators/pine`는 payload까지만 제공해서, TradingView 사용자는 여전히 bridge를 직접 만들거나 서버 JSON을 해석해야 했음
- 사용 의도는 스캘핑인데, TradingView 쪽에는 최근 zone만 보는 native mirror가 없어 차트 사용성이 약했음

### 무엇을 수정했는가
- `scripts/tradingview/trading_engine_v1_mirror.pine`를 추가해 HTF regime, transition/risk state, 최근 LP/FVG zone, best-setup guide를 Pine v6로 근사 구현함
- `GET /indicators/pine-script`를 추가해 로컬 API에서 바로 Pine 스크립트를 받아 TradingView에 붙일 수 있게 함
- `docs/TRADINGVIEW_PINE_MIRROR_GUIDE.md`, `README.md`, `docs/CHECKLIST.md`, `docs/PLAN.md`를 현재 계약으로 동기화함

### 왜 그렇게 판단했는가
- Pine은 서버 JSON을 직접 읽지 못하므로, 실사용성을 높이려면 native mirror script 자체를 제공하는 편이 맞음
- mirror는 source-of-truth를 대체하면 안 되므로, 서버의 `plans/scanner/validation`은 유지하고 TradingView는 최근 zone 중심 시각화/보조 판단에 집중시키는 구성이 가장 안전함

### 최신 검증 스냅샷
- API smoke 실행 결과: `1 passed` (`./.venv/bin/pytest -q tests/test_api_smoke.py -q`)

## 2026-03-09 Iteration #111
### 무엇을 발견했는가
- `strategy_v2_validation`에는 mode 비교만 있어서 family/session별 성과를 바로 읽을 수 없었고, `5m zone / 1m execution` 스캘프 실험도 엔진/리포트/API 기준으로 비교하는 단일 계약이 없었다.
- `sync` 경로는 이미 `limit_1m`를 받기 시작했지만, validation/report와 smoke 테스트는 아직 그 분기를 기준으로 잠겨 있지 않았다.

### 무엇을 수정했는가
- `StrategyV2ValidationService`에 `family_metrics/family_summary`, `session_metrics/session_summary`를 추가하고 markdown report에도 `Family Breakdown`, `Session Breakdown`를 붙였다.
- `StrategyV2ScalpExperimentService`를 엔진/리포트/API에 연결해서 `GET /validation/scalp-experiment`와 `POST /validation/report.strategy_v2_scalp_experiment`를 같은 compare-only 계약으로 노출했다.
- `sync_symbol_from_binance`, `sync_universe_from_binance`가 `limit_1m`를 함께 받는 현재 계약에 맞춰 API smoke와 ops 회귀를 정렬했다.
- 문서와 체크리스트를 `Iteration #111` 기준으로 갱신했다.

### 왜 그렇게 판단했는가
- 지금 단계에서 중요한 건 전략을 더 복잡하게 만드는 것이 아니라, family/session별 우열과 `15m/5m vs 5m/1m` 비교를 같은 validation 언어로 읽게 만드는 것이다.
- 스캘프 실험은 아직 compare-only branch여야 하므로, live source-of-truth를 흔들지 않으면서 report/API에서만 분리 비교하는 구조가 맞다.

### 최신 검증 스냅샷
- 타깃 회귀 실행 결과: `12 passed` (`./.venv/bin/pytest -q tests/test_strategy_engine_ops.py tests/test_strategy_v2_validation.py tests/test_strategy_v2_scalp_experiment.py tests/test_validation_report.py tests/test_api_smoke.py`)
- 전체 테스트 실행 결과: `189 passed, 1 skipped` (`./.venv/bin/pytest -q -rs`)

## 2026-03-09 Iteration #124
### 무엇을 발견했는가
- `GET /execution/operator-ui`는 운영 surface는 충분했지만 영어 중심이고, 상단에서 `현재 상태 / 진입 / 확률 / 기대값 / 차단 이유`를 바로 읽기 어려웠다.
- 화면이 `operator-dashboard / checklist / validation`만 읽어서, 사용자가 실제로 궁금해하는 `plans/top`, `scanner/top`의 대표 플랜/후보 정보가 직접 보이지 않았다.

### 무엇을 수정했는가
- `app/services/execution_operator_ui.py`를 한국어 중심 레이아웃으로 재구성했다.
- 브라우저에서 `GET /plans/top`과 `GET /scanner/top`를 추가로 읽어 `한눈에 보는 현재 상태`, `대표 플랜`, `스캐너 대표 후보`, `현재 진입 가이드`를 상단에 렌더링하도록 바꿨다.
- `README.md`, `docs/CHECKLIST.md`를 현재 operator UI 계약에 맞게 동기화했다.

### 왜 그렇게 판단했는가
- 이 화면의 목적은 raw payload 노출이 아니라 운영자가 `지금 어떤 상태인지`, `어디서 들어가는지`, `왜 허용/차단됐는지`를 짧은 시선 이동 안에서 읽게 만드는 것이다.
- 기존 판단 로직은 충분하므로, 이번 단계는 새 truth를 만들지 않고 기존 `dashboard + plans + scanner`를 읽기 쉬운 운영 surface로 재배치하는 편이 맞다.

### 최신 검증 스냅샷
- API smoke 실행 결과: `1 passed` (`./.venv/bin/pytest -q tests/test_api_smoke.py -q`)
- 추가 정적 검증: `./.venv/bin/python -m py_compile app/services/execution_operator_ui.py`

## 2026-03-09 Iteration #128
### 무엇을 발견했는가
- operator UI의 `days=7`는 최근 리포트 범위처럼 보였지만, 실제로는 `recent_intents`와 `recent_reconciliation_events`에는 적용되지 않았고 활성 주문/포지션/락과 같은 always-on 상태와도 같은 입력처럼 보였다.

### 무엇을 수정했는가
- `OrderIntentRepository.list_recent`와 `ExecutionReconciliationEventRepository.list_recent`에 `days` cutoff를 추가했다.
- `ExecutionOperatorDashboardService`와 응답 schema에 `report_window_days`를 노출했다.
- operator UI에 `기간 필터 적용`/`기간 필터 제외` 배지를 추가하고, 활성 주문·포지션·락은 최근 일수와 무관하게 항상 보인다는 설명을 붙였다.

### 왜 그렇게 판단했는가
- 최근 리포트 목록과 활성 운영 상태는 성격이 다르다. 둘을 같은 기간 필터처럼 보이게 두면 운영자가 오래된 활성 상태를 버그로 오해하게 된다.
- 반대로 `recent_*` 목록은 이름 그대로 실제 기간 컷오프를 적용해야 UI 문구와 데이터가 일치한다.

### 최신 검증 스냅샷
- 정적 검증: `./.venv/bin/python -m py_compile app/services/execution_operator_ui.py app/services/execution_operator_dashboard.py app/db/repositories.py app/services/strategy_engine.py app/schemas/execution.py`
- 테스트 실행 결과: `2 passed` (`./.venv/bin/pytest -q tests/test_execution_operator_dashboard.py tests/test_api_smoke.py -q`)

## 2026-03-09 Iteration #127
### 무엇을 발견했는가
- operator UI를 카드형 + 사이드바 구조로 바꿨지만, 좌측 버튼이 실제 섹션 이동을 하지 않았고 넓은 표도 카드 경계를 넘길 수 있었다.
- `days` 입력은 활성 주문/포지션 전체 필터처럼 읽히기 쉬워 운영자가 최근 리포트 범위와 활성 상태 범위를 혼동할 수 있었다.

### 무엇을 수정했는가
- `app/services/execution_operator_ui.py`에 섹션 네비게이션과 active highlight를 추가했다.
- 모든 표를 `table-wrap` 안으로 감싸 카드 내부 가로 스크롤로 제한했다.
- `최근 일수` 라벨을 `리포트 기준 최근 일수`로 바꾸고 README 설명도 같은 의미로 맞췄다.

### 왜 그렇게 판단했는가
- 이 화면은 요약에서 상세로 내려가는 운영 흐름이 중요하므로, 좌측 버튼이 실제 섹션 이동과 현재 위치 표시를 해야 한다.
- 활성 주문/포지션은 기간과 무관하게 항상 보여야 하지만, 그 사실을 UI 문구로 명확히 하지 않으면 운영자가 필터 의미를 잘못 해석한다.

### 최신 검증 스냅샷
- API smoke 실행 결과: `1 passed` (`./.venv/bin/pytest -q tests/test_api_smoke.py -q`)
- 추가 정적 검증: `./.venv/bin/python -m py_compile app/services/execution_operator_ui.py`

## 2026-03-09 Iteration #125
### 무엇을 발견했는가
- 한국어 operator UI로 바꾼 뒤에도 `대표 플랜`과 `현재 진입 가이드`는 여전히 단순 key/value 나열 비중이 높아서, 실제로 먼저 봐야 하는 `승률 / 기대값 / 권장 리스크 / TP 확률`이 눈에 덜 들어왔다.

### 무엇을 수정했는가
- `app/services/execution_operator_ui.py`의 `대표 플랜`과 `현재 진입 가이드` 영역을 desk-style summary로 다시 구성했다.
- `Est. win`, `Est. EV`, `권장 리스크`, `손익비`, `TP1/TP2/TP3 도달 확률`을 큰 숫자 타일로 올리고, `entry / stop / tp`는 chip 형태로 분리했다.

### 왜 그렇게 판단했는가
- 이 화면의 주 사용 시나리오는 운영자가 몇 초 안에 `지금 해도 되는지`, `어디서 들어가는지`, `기대치가 어떤지`를 읽는 것이다.
- 따라서 세부 원시 필드보다 큰 숫자와 확률 타일을 먼저 보여주는 쪽이 실제 사용성에 더 맞다.

### 최신 검증 스냅샷
- API smoke 실행 결과: `1 passed` (`./.venv/bin/pytest -q tests/test_api_smoke.py -q`)
- 추가 정적 검증: `./.venv/bin/python -m py_compile app/services/execution_operator_ui.py`

## 2026-03-09 Iteration #129
### 무엇을 발견했는가
- `signal quality ↑ / trade frequency ↓` 문제를 계속 감으로 해석하고 있었고, runtime candidate가 `blocked -> intent -> open order/open position` 단계에서 얼마나 줄어드는지 한 화면에서 읽을 수 없었다.
- 특히 `confluence/meta/portfolio/mode` 중 어디가 실제 병목인지 판단하려면, 먼저 runtime funnel 숫자가 필요했다.

### 무엇을 수정했는가
- `/execution/operator-dashboard`에 additive `signal_funnel` payload를 추가했다.
- `runtime_candidates`, `accepted_candidates`, `blocked_candidates`, `blocked_reason_counts`, `recent_intents`, `submit_decision_counts`, `open_orders`, `open_positions`를 같은 runtime surface에서 읽게 했다.
- unit test와 API smoke를 보강하고, living docs/checklist를 `signal funnel instrumentation` 기준으로 동기화했다.

### 왜 그렇게 판단했는가
- 지금 단계에서 바로 필터를 풀거나 전략 산식을 바꾸면, `frequency`와 `edge` trade-off를 감으로 다루게 된다.
- 먼저 어디서 신호가 줄어드는지 계측해야, 이후 `hard block`과 `soft score`를 구분해서 보수적으로 개선할 수 있다.

### 최신 검증 스냅샷
- 타깃 회귀: `./.venv/bin/pytest -q tests/test_execution_operator_dashboard.py tests/test_api_smoke.py -q`

## 2026-05-10 Iteration #135
### 무엇을 발견했는가
- `session_impulse_retest` runtime audit row는 이미 있었지만, WS stream이 활성화되어 sync/manual route를 의도적으로 억제하는 경로는 audit row가 빠질 수 있었다.
- `run_session_impulse_retest_runtime_audit_report.py`는 raw JSON 출력만 제공해 운영 heartbeat나 고정 `latest.md/latest.json` 경로에서 바로 읽기 어려웠다.

### 무엇을 수정했는가
- WS stream active suppression 경로도 `phase=auto_route`, `status=ws_stream_active_route_suppressed`로 DB audit row를 남기게 했다.
- `run_session_impulse_retest_runtime_audit_report.py`를 운영 리포트화해 summary, `overall_status`, timestamp report, `latest.md/latest.json`을 생성하게 했다.
- ops heartbeat와 launchd generator에 `session_impulse_retest_runtime_audit` job을 추가했다.
- README, operating runbook, near-100 hardening plan에 새 audit 리포트 경로와 해석 기준을 반영했다.

### 왜 그렇게 판단했는가
- 주문이 안 들어간 원인을 확정하려면 intent/submission 이후뿐 아니라 runtime refresh/auto_route 직전에서 끊긴 케이스도 DB에 남아야 한다.
- WS가 라우팅 주체라서 중복 라우팅을 억제한 것은 정상 동작이지만, 기록이 없으면 “버그로 안 들어간 것”과 구분하기 어렵다.

### 최신 검증 스냅샷
- 정적 검증:
  - `./.venv/bin/python -m py_compile app/services/strategy_engine.py scripts/run_session_impulse_retest_runtime_audit_report.py scripts/run_micro_live_ops_heartbeat.py scripts/install_micro_live_ops_launchd.py`
- 테스트 실행 결과:
  - `./.venv/bin/pytest -q tests/test_session_impulse_retest_execution_path.py tests/test_micro_live_operational_guards.py -q`
  - 통과
- 운영 리포트 재생성:
  - `./.venv/bin/python scripts/run_session_impulse_retest_runtime_audit_report.py --hours 3 --limit 50 --no-fail-exit`
  - 결과: `PASS`, audit_count `50`, hard route failure `0`
  - `./.venv/bin/python scripts/run_micro_live_ops_heartbeat.py --no-fail-exit`
  - 결과: `WATCH`, hard failure `0`, warning `2` (`no_order_watchdog=ALERT`, `replay_validation_bridge=WATCH`)

## 2026-05-10 Iteration #134
### 무엇을 발견했는가
- 운영 가드는 많이 갖춰졌지만, “완성도 100%에 가까움”의 기준이 한 문서로 고정돼 있지 않았다.
- 일부 운영 리포트는 timestamp 파일만 남겨 수동 확인/heartbeat 이후 operator read path가 흔들릴 수 있었다.
- reconciliation watchdog은 알림 전송 실패도 cooldown state로 기록할 수 있어, 실패한 알림이 다음 알림을 막는 silent gap이 될 수 있었다.

### 무엇을 수정했는가
- `docs/MICRO_LIVE_NEAR_100_HARDENING_PLAN.md`를 추가해 near-100의 의미, 단계, NO-GO 원칙, 현재 우선순위를 고정했다.
- runtime guard, boot check, reconciliation watchdog, synthetic canary가 `latest.md/latest.json` alias를 atomic write로 남기게 했다.
- Binance rule drift snapshot의 timestamp/latest JSON 쓰기를 atomic write로 바꿨다.
- reconciliation watchdog cooldown state는 notification delivery가 확인된 경우에만 기록하도록 바꿨다.

### 왜 그렇게 판단했는가
- 지금 완성도를 올리는 핵심은 필터를 무작정 푸는 것이 아니라, 장애와 주문 미제출 상태가 silent success로 숨지 않게 만드는 것이다.
- 운영자는 raw log보다 먼저 고정 경로 report와 heartbeat를 봐야 하므로 latest alias가 모든 주요 guard에 필요하다.

### 최신 검증 스냅샷
- 정적 검증:
  - `./.venv/bin/python -m py_compile scripts/operation_report_io.py scripts/run_micro_live_runtime_guard.py scripts/run_micro_live_boot_check.py scripts/run_live_reconciliation_watchdog.py scripts/run_micro_live_synthetic_canary.py scripts/run_binance_rule_drift_snapshot.py`
- 테스트 실행 결과:
  - `./.venv/bin/pytest -q tests/test_micro_live_operational_guards.py -q`
  - `44 passed`

## 2026-03-09 Iteration #130
### 무엇을 발견했는가
- backend `signal_funnel`은 이미 있었지만, 운영자가 여전히 raw dashboard JSON을 열어야 `Family / Regime / Session` 통과율과 후보 감소 병목을 읽을 수 있었다.
- README와 living docs도 아직 `signal funnel instrumentation` 기준에 머물러 있어서, operator UI까지 surfaced 된 현재 상태를 충분히 설명하지 못했다.

### 무엇을 수정했는가
- `/execution/operator-ui`가 `dashboard.signal_funnel`을 직접 노출한다는 사실을 체크리스트, 계획서, README에 반영했다.
- `신호 퍼널` 섹션과 `Family / Regime / Session 통과율`을 operator UI surface의 핵심 계약으로 문서에 고정했다.
- living docs 기준선을 `Iteration #130 (signal funnel surfaced in operator UI)`로 올렸다.

### 왜 그렇게 판단했는가
- `signal funnel`은 backend telemetry로만 남기면 효과가 작고, 운영자가 한 화면에서 병목을 읽을 수 있어야 다음 gate 조정이 논리적으로 가능하다.
- 이번 단계는 새 판단을 만드는 작업이 아니라, 이미 구현된 operator surface를 source-of-truth 문서에 맞춰 정렬하는 작업이다.

### 최신 검증 스냅샷
- 코드 계약 변경 없음
- 직전 회귀 기준 유지:
  - `./.venv/bin/python -m py_compile app/services/execution_operator_ui.py app/services/execution_operator_dashboard.py app/schemas/execution.py`
  - `./.venv/bin/pytest -q tests/test_execution_operator_dashboard.py tests/test_api_smoke.py -q`

## 2026-03-09 Iteration #131
### 무엇을 발견했는가
- `signal funnel` 숫자만으로는 frequency 문제가 `절대 유지해야 하는 safety/structural gate` 때문인지, `quality softening 후보` 때문인지 바로 읽기 어려웠다.
- 운영 화면에는 blocked reason top-N은 보였지만, hard block과 softening 후보를 분리해 읽는 공통 분류가 없었다.

### 무엇을 수정했는가
- `/execution/operator-dashboard.signal_funnel`에 `blocked_gate_group_counts`, `blocked_gate_groups`, `current_entry_gate_group`, `current_entry_gate_reason`를 추가했다.
- blocked reason을 `safety / structural / rollout / quality / unknown`으로 매핑하는 공통 분류를 `app/services/execution_operator_dashboard.py`에 고정했다.
- `/execution/operator-ui`에 `게이트 유형별 차단` 섹션과 `현재 신규 진입 차단 유형` 요약 카드를 추가했다.
- living docs와 README를 `signal funnel gate-group visibility` 기준으로 동기화했다.

### 왜 그렇게 판단했는가
- 지금 단계의 목표는 필터를 바로 푸는 것이 아니라, 어떤 차단이 `절대 유지할 hard gate`이고 어떤 차단이 `quality gate softening 후보`인지 운영자가 즉시 구분하게 만드는 것이다.
- 이 분류가 먼저 고정돼야 이후 `hard block vs soft score` 재분류를 감이 아니라 계측 기준으로 진행할 수 있다.

### 최신 검증 스냅샷
- 정적 검증:
  - `./.venv/bin/python -m py_compile app/services/execution_operator_dashboard.py app/services/execution_operator_ui.py`
- 테스트 실행 결과:
  - `./.venv/bin/pytest -q tests/test_execution_operator_dashboard.py tests/test_api_smoke.py -q`

## 2026-03-09 Iteration #132
### 무엇을 발견했는가
- gate-group 분류만으로는 여전히 운영자가 `지금 절대 풀면 안 되는 hard gate`와 `완화 검토 후보 quality gate`를 한 번에 읽기 어려웠다.
- 숫자는 있었지만, 실제 의사결정 문장으로는 `무엇을 유지하고 무엇을 softening 후보로 볼지`가 한 화면에 드러나지 않았다.

### 무엇을 수정했는가
- `/execution/operator-dashboard.signal_funnel`에 `hard_block_summary`, `softening_candidate_summary`, `rollout_block_summary`를 추가했다.
- `/execution/operator-ui`에 `유지해야 하는 hard gate`, `완화 검토 후보`, `운영 정책 차단` 카드와 상세 표를 추가했다.
- README, PLAN, 상세 체크리스트를 같은 계약 기준으로 동기화했다.

### 왜 그렇게 판단했는가
- 지금 단계의 목적은 필터를 푸는 것이 아니라, softening 논의를 감이 아니라 운영 surface 위에서 바로 읽게 만드는 것이다.
- hard gate와 quality gate를 수치로만 남겨두면 다음 단계 재분류가 다시 사람 머리속에서만 일어나게 된다.

### 최신 검증 스냅샷
- 정적 검증:
  - `./.venv/bin/python -m py_compile app/services/execution_operator_dashboard.py app/services/execution_operator_ui.py`
- 테스트 실행 결과:
  - `./.venv/bin/pytest -q tests/test_execution_operator_dashboard.py tests/test_api_smoke.py -q`

## 2026-03-09 Iteration #133
### 무엇을 발견했는가
- hard gate와 quality gate를 나누는 것만으로는 여전히 `무엇을 먼저 softening 검토할지`와 `어느 family/regime/session에서 병목이 심한지`를 운영자가 바로 판단하기 어려웠다.
- blocked reason count만 보면 quality gate 후보의 우선순위와 실제 pass-rate 병목 축이 분리돼 보여, 다음 조정 순서를 감으로 정할 위험이 있었다.

### 무엇을 수정했는가
- `/execution/operator-dashboard.signal_funnel`에 `quality_softening_priorities`, `family_bottlenecks`, `regime_bottlenecks`, `session_bottlenecks`를 추가했다.
- `/execution/operator-ui`에 `완화 우선순위`, `Family 병목 상위`, `Regime 병목 상위`, `Session 병목 상위` 섹션을 추가했다.
- living docs와 README를 같은 operator surface 기준으로 동기화했다.

### 왜 그렇게 판단했는가
- 지금 단계의 목표는 필터를 푸는 것이 아니라, 어떤 quality gate를 먼저 완화 검토할지와 어떤 축에서 빈도가 죽는지를 운영 surface에서 바로 읽게 만드는 것이다.
- 이 우선순위가 먼저 계측돼야 다음 단계의 softening이 감이 아니라 데이터 기준으로 진행된다.

### 최신 검증 스냅샷
- 정적 검증:
  - `./.venv/bin/python -m py_compile app/services/execution_operator_dashboard.py app/services/execution_operator_ui.py`
- 테스트 실행 결과:
  - `./.venv/bin/pytest -q tests/test_execution_operator_dashboard.py tests/test_api_smoke.py -q`

## 2026-05-10 Iteration #134
### 무엇을 발견했는가
- 일부 운영 리포트 스크립트가 `generated_at`을 파일명으로 바꿀 때 각자 `datetime.fromisoformat(...replace("Z", "+00:00"))`를 직접 호출하고 있었다.
- 현재 생성 payload는 대부분 UTC `Z`라 즉시 장애 가능성은 낮지만, 레거시 JSON이나 테스트 주입 값이 naive timestamp/datetime이면 스크립트마다 UTC 정규화가 달라질 수 있었다.

### 무엇을 수정했는가
- `scripts/operation_report_io.py`에 `parse_report_generated_at` 공통 파서를 추가해 `Z`, naive string, naive `datetime`을 모두 UTC aware timestamp로 정규화하게 했다.
- live replay parity, replay validation bridge, stage monitor, failure drill, session impulse retest audit, synthetic canary, reconciliation watchdog, ops heartbeat, runtime guard, no-order watchdog, boot check의 직접 파싱을 공통 파서로 교체했다.
- ops heartbeat/no-order watchdog의 로컬 atomic writer를 공통 atomic writer에 위임하게 하고, launchd plist/copy atomic writer cleanup도 `OSError`를 삼켜 cleanup 실패가 원래 성공한 replace를 덮지 않게 했다.
- 스크립트 엔트리포인트 테스트에 공통 파서의 `Z`/naive string/naive datetime 회귀 케이스를 추가했다.

### 왜 그렇게 판단했는가
- 운영 리포트 파일명 생성은 작은 문제처럼 보여도 launchd/Discord/watchdog 체인에서는 한 스크립트 예외가 곧 “상태 확인 불가”로 이어진다.
- 공통 파서로 모으면 같은 형태의 타임스탬프 버그가 새 스크립트에 반복될 가능성을 줄일 수 있다.

### 최신 검증 스냅샷
- 정적 검증:
  - `./.venv/bin/python -m py_compile scripts/operation_report_io.py scripts/run_live_replay_parity_audit.py scripts/run_replay_validation_bridge.py scripts/stage_monitor_tick.py scripts/run_micro_live_failure_drill.py scripts/run_session_impulse_retest_runtime_audit_report.py scripts/run_micro_live_synthetic_canary.py scripts/run_live_reconciliation_watchdog.py scripts/run_micro_live_ops_heartbeat.py scripts/run_micro_live_runtime_guard.py scripts/run_micro_live_no_order_watchdog.py scripts/run_micro_live_boot_check.py`
  - `git diff --check -- scripts/operation_report_io.py scripts/run_live_replay_parity_audit.py scripts/run_replay_validation_bridge.py scripts/stage_monitor_tick.py scripts/run_micro_live_failure_drill.py scripts/run_session_impulse_retest_runtime_audit_report.py scripts/run_micro_live_synthetic_canary.py scripts/run_live_reconciliation_watchdog.py scripts/run_micro_live_ops_heartbeat.py scripts/run_micro_live_runtime_guard.py scripts/run_micro_live_no_order_watchdog.py scripts/run_micro_live_boot_check.py tests/test_script_entrypoints.py`
- 테스트 실행 결과:
  - `./.venv/bin/pytest -q tests/test_script_entrypoints.py -q`
  - `./.venv/bin/pytest -q tests/test_micro_live_operational_guards.py::test_binance_rule_drift_snapshot_main_writes_latest_json_atomically tests/test_live_order_lifecycle.py -q`
  - `./.venv/bin/pytest -q tests/test_micro_live_operational_guards.py::test_launchd_generator_replaces_plists_atomically tests/test_micro_live_operational_guards.py::test_launchd_installer_copies_plists_atomically tests/test_micro_live_operational_guards.py::test_report_atomic_writers_use_unique_tmp_cleanup -q`
  - `./.venv/bin/pytest -q tests/test_micro_live_operational_guards.py -q`
  - `./.venv/bin/pytest -q` (`968 passed, 1 skipped`)

## 2026-05-13 Iteration #135
### 무엇을 발견했는가
- 확인 시점 기준 최근 3일 MICRO_LIVE intent는 850건 이상 생성됐지만 `SUBMIT_READY`는 0건, live order submission도 0건이었다. 주문 경로 장애가 아니라 승인 게이트에서 전부 막힌 상태다.
- 주요 차단 사유는 `adjusted_score_non_positive`, `thesis_active_cap_reached`, `no_runtime_candidate`, `validation_do_not_deploy`, `rollout_session_not_allowed`였다.
- 백테스트/리플레이 빈도와 live 주문 빈도를 비교할 때 같은 계약을 보고 있지 않았다. `AUTO_TRADING_MICRO_LIVE_ALLOWED_SESSIONS`는 비어 있지만 실제 승인 정책은 family rollout의 `london,new_york` 세션을 적용한다.
- `micro_live_contract` split review는 세션 필터를 적용해 요약할 수 있었지만, parity audit가 읽는 active-contract replay cache는 필터 전 원본 rows를 기준으로 삼을 수 있었다.

### 무엇을 수정했는가
- `scripts/run_live_replay_parity_audit.py`가 active-contract replay baseline을 계산할 때 entry model, direction, family rollout session을 함께 반영하도록 보강했다.
- `scripts/run_historical_walk_forward_split_review.py --preset micro_live_contract`는 `.env`의 MICRO_LIVE 세션 allowlist가 비어 있으면 family rollout policy의 세션을 기본 계약 필터로 사용하게 했다.
- 라이브 승인 조건, validation gate, 주문 제출 로직은 완화하지 않았다. 이번 수정은 “왜 주문이 안 나갔는지”와 “백테스트 빈도와 무엇이 다른지”를 같은 기준으로 보이게 하는 진단/문서화 수정이다.

### 왜 그렇게 판단했는가
- 지금 문제는 scanner가 죽은 것이 아니라 `chart/replay candidate -> live approval -> order submission` 사이의 기준선 불일치다.
- 검증을 끄는 방식으로 첫 주문을 만들면 self-deception 방어가 무너진다. 대신 backtest 기준선, rollout 세션, live 승인 게이트가 같은 계약을 말하도록 맞추는 것이 먼저다.

### 최신 검증 스냅샷
- 정적 검증:
  - `./.venv/bin/python -m py_compile scripts/run_live_replay_parity_audit.py scripts/run_historical_walk_forward_split_review.py`
- 운영 리포트 확인:
  - `scripts/run_live_replay_parity_audit.py --all-live-symbols --days 3 --no-fail-exit --no-write-report`
  - `scripts/run_historical_walk_forward_split_review.py --preset micro_live_contract --entry-models LIMIT --allowed-sessions london,new_york --no-write-report`

## 2026-05-13 Iteration #136
### 무엇을 발견했는가
- `sweep_reversal`은 최근 intent의 대부분을 차지하지만, replay evidence bridge 대상이 아니어서 live validation sample `0/30` 상태에서는 `validation_do_not_deploy`를 벗어날 수 없었다.
- `CONFIRM`은 walk-forward에서 손실/stop 비중이 높아 live 계약에 남겨두면 백테스트 빈도는 늘지만 품질 기준이 흐려진다.
- 세션/entry model을 live 계약과 맞춰 다시 본 결과, replay bridge audit에서 `BTCUSDC + sweep_reversal + LIMIT + london/new_york`만 bridge review 기준을 통과했고 나머지 심볼은 표본 부족, stop-loss 비중, drawdown, lower-bound EV 문제로 제외됐다.

### 무엇을 수정했는가
- `sweep_reversal`도 replay validation bridge에 연결했다. 단, `LIMIT` entry model, live rollout session, direction contract, fresh historical walk-forward cache, 최소 표본/EV/win-rate/EV lower bound/stop-loss share/drawdown floor를 모두 통과해야만 runtime validation sample missing을 보완한다.
- `StrategyEngine`이 replay bridge에 `entry_model`을 전달하게 해서 `CONFIRM` 후보가 sweep replay bridge로 승인되는 경로를 막았다.
- `scripts/run_replay_validation_bridge.py`도 parity audit와 같은 세션 필터를 쓰도록 수정했다.
- `.env`와 runtime `.env`의 MICRO_LIVE 계약을 `LIMIT` 및 `london,new_york` 세션으로 정렬했다.

### 왜 그렇게 판단했는가
- 검증 게이트를 끄면 주문은 나가겠지만, 우리가 유지하려던 self-deception 방어가 사라진다.
- 대신 `sweep_reversal`의 backtest evidence를 live approval 안으로 가져오되, 현재 증거가 가장 강한 BTC/LIMIT/session-aligned 계약에만 통로를 열었다.
- 다른 심볼은 이번 기준에서 자동 개방하지 않는 것이 맞다. 특히 stop-loss share가 높은 심볼은 빈도보다 실행 품질 리스크가 더 크다.

### 최신 검증 스냅샷
- 정적 검증:
  - `./.venv/bin/python -m py_compile app/core/config.py app/services/replay_validation_bridge.py app/services/strategy_engine.py scripts/run_replay_validation_bridge.py scripts/run_live_replay_parity_audit.py scripts/run_historical_walk_forward_split_review.py`
- 테스트 실행 결과:
  - `./.venv/bin/pytest -q tests/test_replay_validation_bridge.py tests/test_session_impulse_retest_execution_path.py::test_auto_route_symbol_keeps_validation_gate_for_sweep_reversal tests/test_session_impulse_retest_execution_path.py::test_auto_route_symbol_uses_walk_forward_bridge_for_sweep_reversal_limit tests/test_script_entrypoints.py -q`
  - `./.venv/bin/pytest -q tests/test_micro_live_operational_guards.py::test_replay_validation_bridge_marks_strong_replay_evidence_as_manual_review_only tests/test_micro_live_operational_guards.py::test_replay_validation_bridge_blocks_weak_replay_evidence tests/test_micro_live_operational_guards.py::test_replay_validation_bridge_warns_when_material_slice_is_weak tests/test_micro_live_operational_guards.py::test_live_replay_parity_portfolio_aggregates_live_symbols -q`
- 운영 리포트 확인:
  - `scripts/run_replay_validation_bridge.py --all-live-symbols --no-fail-exit --no-write-report` -> `WATCH`, `BTCUSDC`만 `ELIGIBLE_FOR_MANUAL_BRIDGE_REVIEW`, 나머지 10개는 `NOT_ELIGIBLE`

## 2026-05-14 Iteration #137
### 무엇을 발견했는가
- Iteration #136의 `BTCUSDC` 단독 bridge 통과 판단은 과하게 낙관적이었다.
- 원인은 `btc_sweep_reversal_limit_fast_failure`가 초기 stop touch 이후 `structure_failure`를 거의 0R 근처로 기록하는 백테스트 처리였다. 이 덕분에 BTC/LIMIT/london+new_york 표본은 raw 기준으로 `stop_loss_share=0%`, `max_drawdown=0.0705R`, `profit_factor`가 비정상적으로 크게 보였다.
- 같은 표본에서 `structure_failure`를 보수적으로 `-1R`로 스트레스 처리하면 BTC는 여전히 EV는 양수지만 `max_drawdown=12.3R`가 되어 runtime bridge cap `4.5R`를 넘는다.
- 감사 스크립트 기본 floor도 runtime bridge보다 느슨했다. 이 때문에 운영 리포트는 `ELIGIBLE_FOR_MANUAL_BRIDGE_REVIEW`를 보여줄 수 있었지만, 실제 runtime bridge는 더 엄격한 drawdown cap에서 막히는 불일치가 있었다.

### 무엇을 수정했는가
- `sweep_reversal` replay bridge는 `structure_failure`가 live에서 거의 무손실로 재현된다는 증거가 쌓이기 전까지 `auto_trading_replay_validation_bridge_sweep_reversal_structure_failure_stress_r=-1.0`으로 평가한다.
- `scripts/run_replay_validation_bridge.py`도 같은 `structure_failure` 스트레스 계산을 적용하고, 기본 bridge floor를 runtime sweep bridge 기준에 맞췄다: sample `120`, EV `0.20R`, win-rate `48%`, stop-loss share `45%`, max drawdown `4.5R`.
- metrics에 `structure_failure_share`, `structure_failure_count`, `structure_failure_stress_r`를 남겨 fast-failure 착시 여부를 리포트에서 바로 볼 수 있게 했다.

### 왜 그렇게 판단했는가
- 라이브 체결 로그가 fast-failure를 실제로 거의 0R로 탈출시킨다는 증거를 아직 제공하지 않는다.
- 검증 브리지는 주문을 열어주는 마지막 방어선이므로, 백테스트 내부의 optimistic exit assumption을 그대로 승인 truth로 쓰면 안 된다.
- 따라서 지금은 “주문이 나가게 만들기”보다 “backtest와 live approval이 같은 위험 가정으로 말하게 만들기”가 맞다.

### 최신 검증 스냅샷
- 정적 검증:
  - `./.venv/bin/python -m py_compile app/core/config.py app/services/replay_validation_bridge.py scripts/run_replay_validation_bridge.py`
- 테스트 실행 결과:
  - `./.venv/bin/python -m pytest tests/test_replay_validation_bridge.py tests/test_micro_live_operational_guards.py::test_replay_validation_bridge_audit_stresses_sweep_structure_failure tests/test_micro_live_operational_guards.py::test_replay_validation_bridge_marks_strong_replay_evidence_as_manual_review_only tests/test_micro_live_operational_guards.py::test_replay_validation_bridge_blocks_weak_replay_evidence tests/test_session_impulse_retest_execution_path.py::test_auto_route_symbol_uses_walk_forward_bridge_for_sweep_reversal_limit -q`
  - `./.venv/bin/python -m pytest tests/test_micro_live_operational_guards.py::test_replay_validation_bridge_audit_stresses_sweep_structure_failure tests/test_micro_live_operational_guards.py::test_replay_validation_bridge_main_writes_latest_aliases -q`
- 운영 리포트 확인:
  - `./.venv/bin/python scripts/run_replay_validation_bridge.py --all-live-symbols --no-fail-exit` -> `ALERT`, `NOT_ELIGIBLE=11`, `no_symbol_clears_replay_validation_bridge_floor`
  - BTC snapshot: sample `1475`, EV `0.3741R`, win `58.10%`, structure_failure_share `64.95%`, maxDD `12.3R`, blocker `drawdown_above_bridge_cap`

## 2026-05-14 Iteration #138
### 무엇을 발견했는가
- 사용자가 기준으로 삼은 기존 11개 코인 PASS 백테스트는 `sweep_reversal`이 아니라 `session_impulse_retest + CONFIRM` 계약이었다.
- 최근 수정 과정에서 live 계약이 `LIMIT` 및 `sweep_reversal` 검증 브리지 쪽으로 기울어, 기존 최고 전략 계약과 live 주문 경로가 서로 다른 전략을 보고 있었다.
- `session_impulse_retest` 백테스트를 다시 확인하면 11개 MICRO_LIVE 심볼은 모두 replay validation bridge를 통과한다. 예: BTC `134 trades / EV 0.5847R / win 66.42%`, SOL `679 / EV 0.6768R / win 65.68%`, NEAR `296 / EV 0.7444R / win 67.23%`.
- `session_impulse_retest` readiness 로직은 live가 이미 켜진 상태에서도 `ready_for_partial=false`만 보고 `session_impulse_retest_rollout_not_ready`를 낼 수 있었다. 실제로는 blockers가 없으면 live running 상태를 막으면 안 된다.

### 무엇을 수정했는가
- `.env` 및 runtime `.env`의 live 계약을 `session_impulse_retest` 단독, `CONFIRM` entry model, `dead_session,london,new_york` 세션 버킷으로 정렬했다.
- runtime DB의 `family_rollout_policy`에서 `session_impulse_retest`는 MICRO_LIVE로 유지하고 `dead_session,london,new_york`를 허용했다.
- runtime DB의 `sweep_reversal`은 PAPER로 내려 live 주문 경로에서 분리했다. sweep은 별도 검증 전까지 research/shadow 취급한다.
- `ExecutionApprovalService`는 `session_impulse_retest` readiness에서 실제 blockers가 있을 때만 shadow로 막도록 수정했다. `ready_for_partial=false` 자체는 live running 상태의 차단 사유가 아니다.
- `RolloutPolicyBootstrap`의 `session_impulse_retest` 기본 세션도 `dead_session,london,new_york`로 맞췄다.

### 왜 그렇게 판단했는가
- 기준은 “백테스트 성과표”가 아니라 그 성과를 만든 최고 전략 계약이다.
- 따라서 live를 임의로 느슨하게 만드는 것이 아니라, live와 검증을 `session_impulse_retest + CONFIRM` 계약으로 다시 일치시키는 것이 맞다.
- `sweep_reversal`은 다른 계약이므로 같은 주문 경로에 섞으면 원인 분석이 흐려진다.

### 최신 검증 스냅샷
- 정적 검증:
  - `./.venv/bin/python -m py_compile app/services/execution_approval.py app/services/family_rollout.py app/core/config.py app/services/replay_validation_bridge.py app/services/strategy_engine.py`
- 테스트 실행 결과:
  - `./.venv/bin/python -m pytest tests/test_session_impulse_retest_execution_path.py::test_session_impulse_retest_live_readiness_without_blockers_can_approve tests/test_session_impulse_retest_execution_path.py::test_session_impulse_retest_secondary_symbol_stays_shadow_even_if_allowlisted tests/test_session_impulse_retest_execution_path.py::test_session_impulse_retest_sol_micro_live_can_approve_and_submit tests/test_replay_validation_bridge.py::test_replay_validation_bridge_promotes_missing_runtime_sample -q`
- 런타임 확인:
  - `/health/ready` -> ready
  - runtime settings: `AUTO_TRADING_ALLOWED_FAMILIES=session_impulse_retest`, `AUTO_TRADING_MICRO_LIVE_ALLOWED_ENTRY_MODELS=CONFIRM`, `AUTO_TRADING_MICRO_LIVE_ALLOWED_SESSIONS=dead_session,london,new_york`
  - runtime rollout DB: `session_impulse_retest=MICRO_LIVE`, `sweep_reversal=PAPER`
  - `session_impulse_retest` replay bridge: 11개 live 심볼 모두 `deploy-small-capital`
  - `run_micro_live_preflight.py --symbol BTCUSDC --no-write-report`: 계약/health/safety/reconciliation/live alignment은 PASS, 남은 항목은 checklist `MANUAL_REVIEW` 1건

## 2026-05-14 Iteration #139
### 무엇을 발견했는가
- 현재 계약 기준은 `session_impulse_retest + CONFIRM + 11개 live 심볼 + dead_session/london/new_york`다.
- 이 계약의 장기 proxy backtest는 `1095 days / 4399 trades / EV 0.6401R / win 65.67% / 4.02 trades/day`다.
- 같은 계약을 최근 런타임 DB 캔들로 다시 재생하면 최근 72시간에는 기대 후보가 10개 있었다. 하지만 최근 12시간에는 0개, 최근 24시간에는 ADA 1개뿐이었고 그 1개는 런타임 재시작 이전 이벤트였다.
- 최근 72시간의 `session_impulse_retest` intent는 전부 실제 주문 제출 전에 막혔다. 원인은 두 가지였다:
  - `rollout_session_not_allowed`: `dead_session`이 live rollout 세션에 없어서 01:00~01:30 UTC 후보가 차단됐다.
  - `session_impulse_retest_rollout_not_ready`: live-enabled 상태인데도 `ready_for_partial=false`를 shadow-only처럼 해석해 런던/뉴욕 후보가 차단됐다.
- 재시작 이후 WS worker는 정상이며 auto-route도 계속 호출되고 있다. 다만 재시작 이후에는 아직 새 `session_impulse_retest` 후보가 생성되지 않아 `auto_route_submit_calls=0` 상태다.

### 무엇을 수정했는가
- `dead_session`을 MICRO_LIVE 계약과 family rollout policy 양쪽에 명시했다.
- `session_impulse_retest` readiness는 실제 blocker가 있을 때만 live 제출을 막도록 수정했다.
- `sweep_reversal`은 PAPER로 내려 현재 주문 경로에서 분리했다.

### 왜 그렇게 판단했는가
- “조건이 됐는데도 주문이 안 들어갔는지”는 최근 72시간 기준으로 보면 맞다. 후보는 있었고, live 계약/승격 해석이 백테스트 계약과 달라 주문 제출 전에 막혔다.
- “지금도 같은 문제가 남아 있는지”는 별도 판단이다. 현재 설정에서는 위 두 차단 원인이 제거됐고, 이후 새 후보가 아직 없어서 주문 제출이 발생하지 않은 상태다.
- 따라서 다음 검증 지점은 새 `session_impulse_retest` 후보가 생성되는 순간 `APPROVED_AUTO -> SUBMIT`으로 이어지는지 확인하는 것이다.

### 최신 검증 스냅샷
- 운영 상태:
  - `/health/ready` -> ready
  - WS heartbeat: `auto_route_calls > 0`, `auto_route_errors=0`, `auto_route_submit_calls=0`
- 최근 계약 재생:
  - `6h=0`, `12h=0`, `24h=1`, `72h=10`
  - 최근 72시간 기대 후보: ADA 2, AVAX 1, BTC 1, LINK 3, NEAR 1, SOL 1, XRP 1
- 최근 72시간 차단 요약:
  - `rollout_session_not_allowed`: AVAX, ADA, XRP, LINK, ADA
  - `session_impulse_retest_rollout_not_ready`: LINK, NEAR, BTC, LINK, SOL

## 2026-05-14 Iteration #140
### 무엇을 발견했는가
- 현재 최고 전략 계약 그대로 최근 72시간을 재생하면 기대 주문은 10건이다.
- 결과는 6승 4패, 총 `+4.491165R`, 평균 `+0.449117R`, 승률 `60.0%`다.
- `.env`의 현재 live sizing은 `AUTO_TRADING_LIVE_ACCOUNT_EQUITY_USDT=200`, `AUTO_TRADING_LIVE_RISK_PER_TRADE_PCT=0.01`이므로 단순 환산 수익률은 `+4.491165%`, 복리 순차 환산은 `+4.486477%`다. 금액으로는 약 `+8.98 USDT`다.
- 차단 원인별 기회 손익:
  - `rollout_session_not_allowed`: 5건, `+2.975022R`, 약 `+2.97%`
  - `session_impulse_retest_rollout_not_ready`: 5건, `+1.516143R`, 약 `+1.47%~1.52%`

### 무엇을 수정했는가
- `scripts/run_session_impulse_retest_opportunity_report.py`를 추가했다.
  - 최근 N시간의 `session_impulse_retest` 기대 후보를 현재 runtime DB 캔들로 재생한다.
  - 각 후보가 실제 runtime에서 plan/intention/submission까지 갔는지 추적한다.
  - 차단 사유별 건수와 차단 사유별 missed R/PnL을 요약한다.
  - 설정된 live risk pct와 account equity로 단순/복리 수익률 및 USDT PnL을 같이 계산한다.
- `scripts/check_runtime_stack.sh`에는 기본 자동 실행이 아니라 `RUN_SIR_OPPORTUNITY_REPORT=1`일 때만 72시간 opportunity summary가 붙도록 했다.

### 왜 그렇게 판단했는가
- 기존 miss detector는 “후보가 runtime에서 누락됐는지”는 잘 보여주지만, 사용자가 바로 알고 싶은 “그래서 몇 건이었고, 그 기회 손익은 얼마였는지”를 한 번에 보여주지 못했다.
- 이번 리포트는 백테스트 조건, runtime observation, 주문 intent, submission, 차단 사유, missed R을 한 truth source로 묶는다.

### 최신 검증 스냅샷
- 정적 검증:
  - `./.venv/bin/python -m py_compile scripts/run_session_impulse_retest_opportunity_report.py`
  - `bash -n scripts/check_runtime_stack.sh`
  - `git diff --check -- scripts/run_session_impulse_retest_opportunity_report.py scripts/check_runtime_stack.sh docs/SELF_CHECK_LOG.md`
- 운영 리포트 확인:
  - `RUNTIME_WORKER_HEARTBEAT_DIR="$HOME/Library/Application Support/trading/heartbeats" DATABASE_URL="sqlite:///$HOME/Library/Application Support/trading/data/trading.db" "$HOME/Library/Application Support/trading/runtime_venv/bin/python" scripts/run_session_impulse_retest_opportunity_report.py --lookback-hours 72 --write-report --summary-only`
  - report: `reports/validation/micro_main_opportunity_reports/session_impulse_retest_opportunity_report_20260513T171236Z.json`

## 2026-05-14 Iteration #141
### 무엇을 발견했는가
- 마지막 구조 점검에서 runtime guard, reconciliation watchdog, synthetic canary는 모두 PASS/OK였다.
- 다만 no-order watchdog는 최근 3일 전체 MICRO_LIVE intent를 기준으로 삼아, 이미 live 경로에서 분리한 과거 `sweep_reversal` 차단 기록까지 현재 주문 없음 경고에 섞고 있었다.
- 추가 확인에서 runtime guard도 lifecycle summary 자체는 최근 3일 전체 live intent를 읽을 수 있어, PASS 상태여도 과거 `sweep_reversal` 차단 intent가 현재 live funnel처럼 보일 수 있었다.
- 이 상태는 실제 차단 원인 분석을 망치지는 않지만, 현재 계약이 정상인데도 과거 계약 노이즈로 WARN을 계속 낼 수 있다.

### 무엇을 수정했는가
- `LiveOrderLifecycleReporter.generate()`에 `start_at`과 `strategy_families` 필터를 추가했다.
- `run_micro_live_no_order_watchdog.py`는 현재 WS runtime `started_at` 이후, 현재 MICRO_LIVE family allowlist 기준으로만 no-order 경고를 평가한다.
- `run_micro_live_runtime_guard.py`도 같은 기준으로 lifecycle/live intent funnel을 좁혔다.
- 새 opportunity report 스크립트도 CLI entrypoint 테스트와 핵심 수익률 계산 테스트에 묶었다.

### 왜 그렇게 판단했는가
- 현재 주문 경로의 truth source는 `session_impulse_retest + CONFIRM`이다.
- 과거 `sweep_reversal` MICRO_LIVE 실험 기록은 보존해야 하지만, 현재 no-order 알림의 판단 근거로 쓰면 운영자가 잘못된 문제를 쫓게 된다.
- 따라서 historical lifecycle report는 그대로 두되, no-order watchdog과 runtime guard의 운영 판단만 current-runtime/current-contract 관점으로 좁히는 것이 맞다.

### 최신 검증 스냅샷
- 정적 검증:
  - `./.venv/bin/python -m py_compile app/services/live_order_lifecycle.py scripts/run_micro_live_no_order_watchdog.py scripts/run_micro_live_runtime_guard.py scripts/run_micro_live_boot_check.py scripts/run_session_impulse_retest_opportunity_report.py`
  - `./.venv/bin/python -m py_compile scripts/run_micro_live_runtime_guard.py app/services/live_order_lifecycle.py scripts/run_micro_live_no_order_watchdog.py`
  - `git diff --check -- app/services/live_order_lifecycle.py scripts/run_micro_live_no_order_watchdog.py tests/test_live_order_lifecycle.py tests/test_script_entrypoints.py docs/SELF_CHECK_LOG.md`
- 테스트 실행 결과:
  - `./.venv/bin/pytest -q tests/test_live_order_lifecycle.py tests/test_micro_live_operational_guards.py::test_no_order_watchdog_alerts_when_live_intents_have_no_submission tests/test_micro_live_operational_guards.py::test_no_order_watchdog_main_writes_latest_aliases tests/test_script_entrypoints.py::test_runtime_scripts_support_direct_help_from_other_cwd tests/test_script_entrypoints.py::test_session_impulse_retest_opportunity_report_performance_uses_configured_risk -q`
  - `./.venv/bin/pytest -q tests/test_micro_live_runtime_guard.py tests/test_live_order_lifecycle.py tests/test_micro_live_operational_guards.py::test_runtime_guard_main_writes_latest_aliases tests/test_micro_live_operational_guards.py::test_no_order_watchdog_main_writes_latest_aliases -q`
- 운영 확인:
  - `run_micro_live_runtime_guard.py --days 3 --limit 200 --no-fail-exit --no-write-report` -> `overall_status=PASS`, `operational_status=PASS`, current runtime/current family 기준 live intent `0`
  - `run_live_reconciliation_watchdog.py --days 3 --no-fail-exit --no-write-report` -> `OK`, `no_reconciliation_gap_detected`
  - `run_micro_live_synthetic_canary.py --no-network --no-fail-exit --no-write-report` -> `PASS`
  - `run_micro_live_no_order_watchdog.py --days 3 --no-fail-exit --no-write-report` -> `OK`, current runtime/current family 기준 live intent `0`

## 2026-05-14 Iteration #142
### 무엇을 발견했는가
- `run_replay_validation_bridge.py` 운영 리포트가 현재 `session_impulse_retest` live approval이 쓰는 USDT proxy bridge를 보지 않고, `sweep_reversal` historical walk-forward cache만 보고 있었다.
- 그래서 실제 런타임 bridge는 11개 심볼 모두 usable인데도 운영 리포트는 현재 SIR 계약을 `sample_size=0`, `ALERT`로 표시할 수 있었다.
- macro blackout 계약 파일도 오래됐고, live에서 분리한 `sweep_reversal/LIMIT`까지 포함한 Q2 중심 계약으로 남아 있었다.

### 무엇을 수정했는가
- `run_replay_validation_bridge.py`는 현재 MICRO_LIVE family가 `session_impulse_retest`이면 `UsdtProxyReplayValidationBridge.evaluate()`를 직접 사용해 런타임 approval과 같은 evidence를 보고한다.
- `sweep_reversal`은 기존 historical walk-forward cache 평가 경로를 유지해, future research/shadow 분석과 SIR live bridge가 섞이지 않게 했다.
- macro blackout 계약을 현재 11개 live 심볼, `session_impulse_retest`, `CONFIRM` 기준으로 갱신했다. FOMC는 공식 Fed calendar에서 갱신했고, BLS CPI/NFP는 403으로 막혀 기존 계약 9개 window를 fallback으로 유지했다.
- stale 운영 latest 리포트를 갱신해 ops heartbeat가 현재 상태판을 읽도록 했다.

### 왜 그렇게 판단했는가
- 현재 주문 승인 truth는 `session_impulse_retest + CONFIRM + USDT proxy replay bridge`다.
- 운영 리포트가 다른 cache를 truth로 삼으면 주문은 정상이어도 운영자는 “검증이 0표본이라 막혔다”고 오해할 수 있다.
- blackout도 실제 live 계약과 같은 family/entry model만 막아야 한다. 이미 PAPER로 내린 `sweep_reversal`까지 live blackout truth에 남겨두면 상태 설명이 다시 흐려진다.

### 최신 검증 스냅샷
- 정적 검증:
  - `./.venv/bin/python -m py_compile scripts/run_replay_validation_bridge.py`
  - `git diff --check -- scripts/run_replay_validation_bridge.py tests/test_micro_live_operational_guards.py`
- 테스트 실행 결과:
  - `./.venv/bin/pytest -q tests/test_micro_live_operational_guards.py::test_replay_validation_bridge_build_payload_uses_runtime_bridge_for_session_impulse tests/test_micro_live_operational_guards.py::test_replay_validation_bridge_warns_when_material_slice_is_weak tests/test_micro_live_operational_guards.py::test_replay_validation_bridge_main_writes_latest_aliases tests/test_replay_validation_bridge.py::test_replay_validation_bridge_promotes_missing_runtime_sample -q`
- 운영 확인:
  - `run_replay_validation_bridge.py --all-live-symbols --no-fail-exit` -> `PASS`, `ELIGIBLE_FOR_RUNTIME_VALIDATION_BRIDGE=11`
  - `build_micro_live_event_blackouts.py --output reports/validation/contracts/micro_live_event_blackouts_major_us_macro_q2_2026_v1.json --fallback-input ...` -> `PASS_WITH_WARNINGS`, `windows=22`, `families=session_impulse_retest`, `entry_models=CONFIRM`
  - `run_micro_live_ops_heartbeat.py --no-fail-exit --no-write-report` -> `PASS`
  - `/health/ready` -> `ready`, db/binance/event_backend/worker/market data checks all true

## 2026-05-14 Iteration #143
### 무엇을 발견했는가
- 워크스페이스 기준 운영 리포트는 PASS였지만, 실제 launchd/runtime worker가 사용하는 `runtime_src` 기준으로는 일부 변경이 아직 배포되지 않았다.
- 차이가 있던 파일은 `app/services/live_order_lifecycle.py`, `run_micro_live_no_order_watchdog.py`, `run_micro_live_runtime_guard.py`, `run_replay_validation_bridge.py`, `run_session_impulse_retest_opportunity_report.py`, `check_runtime_stack.sh`, macro blackout 계약 파일이었다.
- 이 때문에 runtime_src에서 ops heartbeat를 돌리면 운영 리포트 latest가 없거나 오래된 파일을 읽어 FAIL/WATCH가 나왔다. 워크스페이스에서만 PASS를 본 것은 운영 truth를 완전히 확인한 것이 아니었다.

### 무엇을 수정했는가
- 위 파일들을 `runtime_src`에 동기화했다.
- `runtime_src` 기준으로 runtime guard, no-order watchdog, reconciliation watchdog, synthetic canary, boot check, replay validation bridge, SIR runtime audit, failure drill, Binance rule drift 리포트를 다시 생성했다.
- macro blackout 계약도 runtime reports symlink 대상에 반영했다.

### 왜 그렇게 판단했는가
- 실제 자동매매 프로세스는 `/Users/yumin/Library/Application Support/trading/runtime_src`에서 실행된다.
- 따라서 최종 운영 판정은 repo working tree가 아니라 runtime_src + runtime reports 기준으로 확인해야 한다.
- `micro_live_event_blackouts()`는 승인 시 파일을 다시 읽으므로 blackout 계약 동기화는 런타임 재시작 없이 다음 승인 평가부터 반영된다.

### 최신 검증 스냅샷
- runtime sync:
  - `app/services/live_order_lifecycle.py`, `run_micro_live_no_order_watchdog.py`, `run_micro_live_runtime_guard.py`, `run_replay_validation_bridge.py`, `run_session_impulse_retest_opportunity_report.py`, `check_runtime_stack.sh`, macro blackout 계약 파일 -> workspace/runtime_src `synced`
- runtime 정적 검증:
  - `runtime_venv/bin/python -m py_compile app/services/live_order_lifecycle.py scripts/run_micro_live_no_order_watchdog.py scripts/run_micro_live_runtime_guard.py scripts/run_replay_validation_bridge.py scripts/run_session_impulse_retest_opportunity_report.py`
- runtime 운영 확인:
  - `run_micro_live_ops_heartbeat.py --no-fail-exit --no-write-report` from `runtime_src` -> `PASS`
  - `run_micro_live_runtime_guard.py --days 3 --limit 200 --no-fail-exit` from `runtime_src` -> `PASS/PASS`, current runtime/current family 기준 live intent `0`
  - `run_micro_live_no_order_watchdog.py --days 3 --limit 200 --no-fail-exit` from `runtime_src` -> `OK`, `no_recent_live_intents`
  - `run_replay_validation_bridge.py --all-live-symbols --no-fail-exit` from `runtime_src` -> `PASS`, `ELIGIBLE_FOR_RUNTIME_VALIDATION_BRIDGE=11`
  - `/health/ready` -> `ready`

## 2026-05-14 Iteration #144
### 무엇을 발견했는가
- `check_runtime_stack.sh`와 API `/execution/operator-dashboard`의 live candidate promotion readiness가 최근 24시간 전체 intent를 섞어 보여줄 수 있었다.
- 실제 현재 runtime 이후 SIR intent는 0건인데, dashboard global readiness에는 재시작 전 `session_impulse_retest` 차단 2건이나 과거 sweep 계열 intent가 headline/top reasons에 남을 수 있었다.
- live route diagnosis도 live allowlist 밖 shadow SIR signal을 `WATCH`로 먼저 보여줘, 현재 live 11개 심볼에 fresh candidate가 없다는 정상 상태와 구분이 흐렸다.

### 무엇을 수정했는가
- `live_candidate_promotion_readiness_runtime`은 DB intent/submission 집계에서 `session_impulse_retest`만 보도록 좁혔다.
- `run_live_candidate_promotion_readiness.py`에 `--since-ws-start`와 `--heartbeat-dir`를 추가했다.
- `check_runtime_stack.sh`는 execution summary와 promotion readiness를 현재 WS runtime 시작 이후/current family 기준으로 표시한다.
- live allowlist 밖 SIR shadow signal은 hard warning이 아니라 `WAIT/no_fresh_live_signal`의 부가 정보로 표시하게 했다.
- `StrategyEngine.execution_operator_dashboard()`도 readiness window를 현재 WS runtime `started_at` 이후로 맞췄고, runtime stack을 재시작해 API 프로세스까지 새 코드를 로드했다.

### 왜 그렇게 판단했는가
- 현재 주문 경로 판단은 “현재 runtime 이후의 `session_impulse_retest + CONFIRM`”이어야 한다.
- 24시간 전체 intent를 그대로 보여주면 이미 live 경로에서 분리한 실험 기록이 현재 차단처럼 보인다.
- shadow-only symbol signal은 확장 후보 관측값이지 현재 11개 live 심볼 주문 실패가 아니다.

### 최신 검증 스냅샷
- 정적/테스트:
  - `./.venv/bin/python -m py_compile app/services/strategy_engine.py app/services/live_candidate_promotion_readiness_runtime.py scripts/run_live_candidate_promotion_readiness.py`
  - `bash -n scripts/check_runtime_stack.sh`
  - `./.venv/bin/pytest -q tests/test_live_candidate_promotion_readiness.py tests/test_api_smoke.py::test_health_and_bootstrap_flow tests/test_script_entrypoints.py::test_runtime_scripts_support_direct_help_from_other_cwd -q`
- runtime 재시작:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=0 ./scripts/restart_runtime_stack_tmp.sh` -> `/health/ready` ready
- runtime 운영 확인:
  - WS `started_at=2026-05-13T18:07:56.386490+00:00`, `auto_route_errors=0`
  - dashboard selected/global readiness 모두 `filter_strategy_families=['session_impulse_retest']`, `window_start=2026-05-13T18:07:56.386490Z`, `top_intent_reasons={}`
  - runtime guard -> `PASS/PASS`, current runtime/current family 기준 live intent `0`
  - no-order watchdog -> `OK`, `no_recent_live_intents`
  - miss detector 6h -> expected `0`, miss `0`
  - ops heartbeat -> `PASS`
  - `check_runtime_stack.sh` -> execution summary current runtime/current family 기준 intents `none`, live route diagnosis `WAIT/no_fresh_live_signal`

## 2026-05-14 Iteration #145
### 무엇을 발견했는가
- micro-live 운영 감시 스크립트와 리포트는 정리되어 있었지만, 사용자 LaunchAgents에는 `com.trading.micro-live.*` 스케줄 작업이 설치되어 있지 않았다.
- 이 상태에서는 수동으로 리포트를 생성한 직후에는 ops heartbeat가 PASS가 될 수 있지만, 시간이 지나면 최신 운영 리포트가 갱신되지 않아 stale 상태가 된다.
- 이는 주문 경로 차단 원인은 아니지만, 운영자가 “실제 감시가 계속 돌고 있다”고 오해할 수 있는 배포 공백이었다.

### 무엇을 수정했는가
- `runtime_src` 기준으로 `install_micro_live_ops_launchd.py --install --unload --load`를 실행해 micro-live 운영 감시 LaunchAgents 11개를 설치하고 로드했다.
- 설치 작업은 runtime python, runtime working directory, runtime `.env`를 사용하도록 구성했다.
- 설치/로드된 작업:
  - `com.trading.micro-live.runtime-guard`
  - `com.trading.micro-live.no-order-watchdog`
  - `com.trading.micro-live.reconciliation-watchdog`
  - `com.trading.micro-live.synthetic-canary`
  - `com.trading.micro-live.boot-check`
  - `com.trading.micro-live.ops-heartbeat`
  - `com.trading.micro-live.binance-rule-drift`
  - `com.trading.micro-live.replay-validation-bridge`
  - `com.trading.micro-live.session-impulse-retest-runtime-audit`
  - `com.trading.micro-live.failure-drill`
  - `com.trading.micro-live.macro-calendar-blackouts`

### 왜 그렇게 판단했는가
- 현재 자동매매 운영 truth는 runtime worker뿐 아니라 runtime guard, no-order watchdog, replay bridge, reconciliation watchdog 같은 주기 감시 리포트까지 포함한다.
- 수동 실행 PASS만으로는 “앞으로도 계속 감시된다”는 보장이 없으므로, launchd 스케줄 로드 여부까지 최종 운영 조건에 포함해야 한다.
- 작업 설치는 전략 조건이나 주문 승인 로직을 바꾸지 않고, 운영 감시가 지속적으로 갱신되게 만드는 배포 보완이다.

### 최신 검증 스냅샷
- launchd 설치:
  - `install_micro_live_ops_launchd.py --install --unload --load` -> `overall_status=PASS`, `job_count=11`, 모든 load returncode `0`
- launchd 로드 확인:
  - `launchctl list | rg 'com\.trading\.micro-live'` -> 11개 작업 로드 확인
  - `~/Library/LaunchAgents/com.trading.micro-live.runtime-guard.plist` -> `WorkingDirectory=/Users/yumin/Library/Application Support/trading/runtime_src`, runtime `.env` source, runtime venv python 사용
  - `~/Library/LaunchAgents/com.trading.micro-live.no-order-watchdog.plist` -> 같은 runtime source/env/python 구성 확인
- runtime 운영 확인:
  - `run_micro_live_ops_heartbeat.py --no-fail-exit --no-write-report` from `runtime_src` -> `PASS`
  - `run_micro_live_runtime_guard.py --days 3 --limit 200 --no-fail-exit --no-write-report` from `runtime_src` -> `PASS/PASS`, `runtime_started_at=2026-05-13T18:07:56.386490+00:00`, `family_filter=['session_impulse_retest']`, live intent `0`

## 2026-05-14 Iteration #146
### 무엇을 발견했는가
- Iteration #145에서 launchd 작업은 설치됐지만, plist가 `RunAtLoad=false`라 재로드 직후 첫 실행 전 stale 공백이 생길 수 있었다.
- `RunAtLoad=true`로 바꿔 재로드 검증을 하자 모든 작업이 exit code `127`로 실패했다.
- 원인은 launchd 명령이 runtime `.env`를 쉘에서 `source`한 것이다. `.env`에는 `LONG|SHORT` direction contract와 공백이 포함된 파일 경로가 있어 쉘 source 방식으로는 안전하게 파싱되지 않는다.

### 무엇을 수정했는가
- `install_micro_live_ops_launchd.py`의 generated plist를 `RunAtLoad=true`로 바꿨다.
- launchd `ProgramArguments`에서는 더 이상 `.env`를 shell source하지 않는다.
- Python 설정은 `app.core.config.Settings`가 `ROOT_DIR/.env`를 직접 읽는 구조이므로, launchd는 절대경로 python/script와 `WorkingDirectory`만 제공하게 했다.
- 기존 127 실패 로그는 launchd logs archive로 옮긴 뒤, 수정된 plist 11개를 runtime_src 기준으로 재설치/로드했다.

### 왜 그렇게 판단했는가
- 운영 감시는 재부팅/재로드 직후에도 즉시 한 번 돌아야 한다. 그렇지 않으면 stale 리포트 공백이 생긴다.
- `.env`를 쉘 문법으로 강제 해석하면 전략 direction contract와 runtime path가 깨질 수 있다.
- 앱 자체의 pydantic settings loader가 `.env`를 읽는 것이 단일 truth source이므로, launchd shell wrapper는 제거하는 편이 맞다.

### 최신 검증 스냅샷
- 테스트:
  - `./.venv/bin/python -m py_compile scripts/install_micro_live_ops_launchd.py`
  - `./.venv/bin/pytest -q tests/test_micro_live_operational_guards.py::test_launchd_generator_replaces_plists_atomically tests/test_micro_live_operational_guards.py::test_launchd_generator_does_not_shell_source_env_file tests/test_micro_live_operational_guards.py::test_launchd_generator_uses_env_file_macro_blackout_contract -q`
- launchd 재설치/로드:
  - `install_micro_live_ops_launchd.py --install --unload --load` from `runtime_src` -> `overall_status=PASS`, `job_count=11`, 모든 load returncode `0`
  - installed plist 11개 모두 `RunAtLoad=true`
  - `launchctl list | rg 'com\.trading\.micro-live'` -> 11개 작업 모두 last exit code `0`
  - 새 `reports/operations/launchd/logs/*.err.log` -> empty
- runtime 운영 확인:
  - RunAtLoad 직후 runtime guard, no-order watchdog, reconciliation watchdog, synthetic canary, boot check, Binance rule drift, replay validation bridge, SIR runtime audit, failure drill, ops heartbeat 리포트가 모두 갱신됨
  - `run_micro_live_ops_heartbeat.py --no-fail-exit --no-write-report` from `runtime_src` -> `PASS`, warning/failure/hard failure `0`

## 2026-05-14 Iteration #147
### 무엇을 발견했는가
- RunAtLoad 검증 중 macro blackout 자동 갱신이 현재 출력 파일을 fallback input으로 다시 읽는 것을 확인했다.
- 이때 FOMC는 공식 Fed source에서 이미 수집됐는데도 fallback 카운트에는 과거 FOMC fallback row까지 섞일 수 있었다.
- 실제 blackout window 자체는 dedupe되어 유지됐지만, `fallback_window_count`와 source attribution이 불필요하게 흔들릴 수 있었다.

### 무엇을 수정했는가
- `build_micro_live_event_blackouts.py`의 fallback recovery가 공식 source에서 누락된 코드만 가져오도록 좁혔다.
- 테스트 fallback fixture에 FOMC row를 추가해, FOMC가 공식 source에서 잡힌 경우 fallback count에 포함되지 않게 고정했다.
- workspace와 runtime_src의 macro blackout 계약을 새 빌더 기준으로 다시 생성/동기화했다.

### 왜 그렇게 판단했는가
- blackout 계약은 주문 차단 truth source이므로, 실제 차단 window뿐 아니라 운영자가 읽는 fallback attribution도 안정적이어야 한다.
- BLS fetch가 403으로 막히는 현재 조건에서는 CPI/NFP만 fallback으로 보완해야 하며, 공식 Fed source에서 확인한 FOMC까지 fallback으로 세면 운영 리포트가 과장된다.

### 최신 검증 스냅샷
- 테스트:
  - `./.venv/bin/python -m py_compile scripts/build_micro_live_event_blackouts.py scripts/install_micro_live_ops_launchd.py`
  - `./.venv/bin/pytest -q tests/test_micro_live_operational_guards.py::test_event_blackout_builder_uses_fallback_when_bls_sources_block tests/test_micro_live_operational_guards.py::test_event_blackout_fallback_respects_configured_pre_window tests/test_micro_live_operational_guards.py::test_launchd_generator_does_not_shell_source_env_file -q`
- contract regeneration:
  - `build_micro_live_event_blackouts.py --years 2026,2027 --output reports/validation/contracts/micro_live_event_blackouts_major_us_macro_q2_2026_v1.json` -> `PASS_WITH_WARNINGS`, BLS 403 warnings only
  - window count `22`, fallback count `6`, coverage remains current `session_impulse_retest + CONFIRM + 11 live symbols`
  - workspace/runtime_src contract file -> `synced`

## 2026-05-14 Iteration #148
### 무엇을 발견했는가
- `/execution/operator-dashboard`를 직접 호출하면 8초 timeout 동안 응답이 없을 수 있었다.
- 운영 UI는 이미 `fast=true`를 붙여 호출하지만, 서버의 `execution_operator_dashboard(..., fast=True)` 경로가 alpha research, promotion governance, lifecycle queue 같은 무거운 분석 계층을 거의 그대로 계산하고 있었다.
- 이 문제는 주문 제출 경로를 막지는 않지만, 운영자가 대시보드에서 현재 live 상태를 확인할 때 화면이 늦거나 멈춘 것처럼 보일 수 있다.

### 무엇을 수정했는가
- `fast=True` dashboard 경로는 안전 상태, portfolio snapshot, recent intent/reconciliation, execution friction, active contract, live candidate promotion readiness만 생성하고 즉시 반환하게 했다.
- 무거운 alpha/research/promotion 계층은 full dashboard 경로에 남겨두고 fast 경로에서는 건너뛴다.
- fast 경로에서도 current WS runtime `started_at` 기준 readiness와 `session_impulse_retest` universe policy는 유지되도록 공통 attach helper를 추가했다.
- runtime_src에 반영하고 runtime stack을 재시작했다.

### 왜 그렇게 판단했는가
- 운영 UI의 1차 목적은 “지금 live 주문 경로가 막혔는지, fresh candidate가 있는지”를 빠르게 보는 것이다.
- full research dashboard는 별도 분석용으로 유지하되, UI poll/상태판 경로는 몇 초 안에 응답해야 운영 판단을 방해하지 않는다.
- fast 경로를 줄여도 주문 승인/제출 로직은 건드리지 않는다.

### 최신 검증 스냅샷
- 테스트:
  - `./.venv/bin/python -m py_compile app/services/strategy_engine.py scripts/build_micro_live_event_blackouts.py scripts/install_micro_live_ops_launchd.py`
  - `./.venv/bin/pytest -q tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_fast_skips_heavy_research_layers tests/test_api_smoke.py::test_health_and_bootstrap_flow -q`
- runtime 배포:
  - `app/services/strategy_engine.py` workspace/runtime_src -> `synced`
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=0 ./scripts/restart_runtime_stack_tmp.sh` -> `/health/ready` ready
- API 확인:
  - `/execution/operator-dashboard?...&fast=true` -> HTTP `200`, `2.30s`, readiness 포함
  - selected BTC readiness -> `WAIT/no_promotable_live_candidate`
  - global readiness -> live target fresh candidate 없음, 일부 shadow-only candidate는 watch-only
- current runtime 운영 확인:
  - WS `runtime_started_at=2026-05-13T18:26:52.453243+00:00`
  - runtime guard -> `PASS/PASS`, current runtime/current family live intent `0`
  - no-order watchdog -> `OK`, `no_recent_live_intents`
  - replay validation bridge -> `PASS`, `ELIGIBLE_FOR_RUNTIME_VALIDATION_BRIDGE=11`
  - miss detector 6h -> expected `0`, observed `0`, miss `0`

## 2026-05-14 Iteration #149
### 무엇을 발견했는가
- runtime stack과 launchd 운영 작업은 `runtime_src/.env`를 사용하고 있었고, 여기에는 운영 DB와 worker heartbeat 경로가 들어 있었다.
- 반면 workspace `.env`에는 `DATABASE_URL`과 `RUNTIME_WORKER_HEARTBEAT_DIR`가 빠져 있어, workspace에서 수동 점검 스크립트를 직접 실행하면 기본 DB/기본 heartbeat 경로를 볼 수 있었다.
- 이 차이는 실제 주문 실행을 막지는 않지만, 수동 점검 결과에서 `runtime_started_at=null` 또는 과거 intent가 섞여 보이게 만들어 운영 판단을 헷갈리게 할 수 있다.

### 무엇을 수정했는가
- workspace `.env`에 운영 DB 경로와 운영 heartbeat 경로를 추가해, 수동 점검도 runtime stack과 같은 truth source를 보게 맞췄다.
- runtime guard, no-order watchdog, miss detector를 workspace에서 다시 실행해 current WS runtime 기준으로 정상 집계되는지 확인했다.

### 왜 그렇게 판단했는가
- 현재 주문 미발생 원인을 볼 때 가장 중요한 기준은 “최근 24시간 전체”가 아니라 “현재 살아 있는 WS runtime 시작 이후”다.
- 수동 점검과 launchd 점검이 서로 다른 DB/heartbeat를 보면, 이미 해결된 과거 shadow-only/blocked intent가 현재 문제처럼 보일 수 있다.
- 따라서 수동 점검 경로도 운영 runtime과 같은 DB 및 heartbeat를 보게 맞추는 것이 오해를 줄이는 데 필요했다.

### 최신 검증 스냅샷
- workspace settings 확인:
  - `database_path=/Users/yumin/Library/Application Support/trading/data/trading.db`
  - `heartbeat_dir=/Users/yumin/Library/Application Support/trading/heartbeats`
  - `ws_started_at=2026-05-13T18:26:52.453243+00:00`
- runtime guard from workspace:
  - `overall_status=PASS`, `operational_status=PASS`
  - `runtime_started_at=2026-05-13T18:26:52.453243+00:00`
  - current runtime/current family live intent `0`, submit-ready `0`, live submission `0`
- no-order watchdog from workspace:
  - `status=OK`, `reason=no_recent_live_intents`
  - current runtime live intent `0`, requested live order `0`
- miss detector from workspace:
  - `effective_window_start=2026-05-13T18:26:52.453243+00:00`
  - expected `1`, skipped before runtime start `1`, runtime observed `0`, miss `0`

## 2026-05-14 Iteration #150
### 무엇을 발견했는가
- no-order watchdog은 실제로 current runtime live intent가 `0`인 정상 대기 상태에서도 `actions=validation gate와 rollout session gate를 먼저 확인`이라고 표시했다.
- 이 문장은 주문 차단 사유가 없는 상황에서도 검증/세션 gate가 문제인 것처럼 읽힐 수 있었다.
- 주문 실행 경로 자체에는 영향이 없지만, 운영자가 “왜 주문이 안 들어갔는지”를 해석할 때 불필요한 오해를 만들 수 있다.

### 무엇을 수정했는가
- no-order watchdog에서 blocked diagnostics가 없고 live intent도 없으면 다음 행동을 `fresh live 후보 대기; 현재 차단 사유 없음`으로 표시하게 했다.
- submit-ready gap, rejected/error, blocked intent는 각각 별도 next action 문구를 쓰도록 분리했다.
- workspace와 runtime_src의 `run_micro_live_no_order_watchdog.py`를 동기화했다.

### 왜 그렇게 판단했는가
- 현재 상태는 “주문이 gate에 막힘”이 아니라 “현재 runtime 기준 live 후보가 아직 없음”이다.
- 운영 리포트 문구는 실제 상태를 그대로 말해야 하며, fallback 문구가 과거 문제 원인을 암시하면 안 된다.
- 주문 승인/제출 로직은 건드리지 않고, 관측/문서화 계층의 해석 문구만 보정했다.

### 최신 검증 스냅샷
- 테스트:
  - `./.venv/bin/python -m py_compile scripts/run_micro_live_no_order_watchdog.py`
  - `./.venv/bin/pytest -q tests/test_micro_live_operational_guards.py::test_no_order_watchdog_no_recent_intents_message_waits_for_candidate tests/test_micro_live_operational_guards.py::test_no_order_watchdog_alerts_when_live_intents_have_no_submission tests/test_micro_live_operational_guards.py::test_no_order_watchdog_notification_message_is_concise -q`
- runtime_src 확인:
  - runtime `run_micro_live_no_order_watchdog.py` py_compile PASS
  - workspace/runtime_src no-order watchdog script -> `synced`
  - runtime no-order watchdog -> `status=OK`, `reason=no_recent_live_intents`, `actions=fresh live 후보 대기; 현재 차단 사유 없음`

## 2026-05-14 Iteration #151
### 무엇을 발견했는가
- `check_runtime_stack.sh`의 제목은 `current runtime/current family`였지만, 그 아래에 24h reference audit count가 먼저 출력됐다.
- 이 때문에 과거 `intent_blocked` audit count가 현재 runtime blocker처럼 보일 수 있었다.
- 또한 workspace git object storage에 stray garbage object가 있어 `git count-objects` stderr 경고가 운영 스택 경고처럼 보일 수 있었다.

### 무엇을 수정했는가
- execution summary에서 current WS start 이후 audit를 먼저 `session_impulse_retest_audits_since_ws_start_current`로 출력하게 했다.
- 24h audit count는 `session_impulse_retest_audits_24h_reference_not_current_blockers`로 명시해 현재 차단 사유와 분리했다.
- `git count-objects` stderr는 숨겨 runtime 점검 출력에 git 저장소 노이즈가 섞이지 않게 했다. git object 자체는 trading runtime과 무관하므로 삭제하지 않았다.
- workspace와 runtime_src의 `check_runtime_stack.sh`를 동기화했다.

### 왜 그렇게 판단했는가
- 현재 주문 상태를 판단할 때 기준은 current WS runtime 이후의 live route 상태다.
- 과거 audit count는 참고용으로는 유용하지만, 현재 주문 미발생 원인처럼 보이면 운영 판단을 흐린다.
- git 저장소 정리 문제는 별도 관리 대상이며, 주문 실행/시장 데이터/DB/worker 상태와 섞어 읽으면 안 된다.

### 최신 검증 스냅샷
- `bash -n scripts/check_runtime_stack.sh` PASS
- `bash -n runtime_src/scripts/check_runtime_stack.sh` PASS
- workspace/runtime_src `check_runtime_stack.sh` -> `synced`
- `check_runtime_stack.sh` execution summary:
  - current runtime intent `none`
  - current audit: `no_live_route_candidate_plan`, `ws_stream_active_route_suppressed`, `no_fresh_candidates`, shadow-only `symbol_not_live_enabled_for_auto_route`
  - 24h historical audit is now explicitly `reference_not_current_blockers`
  - live route diagnosis remains `WAIT/no_fresh_live_signal`

## 2026-05-14 Iteration #152
### 무엇을 발견했는가
- selected symbol readiness는 `WAIT/no_promotable_live_candidate`였지만, global readiness는 shadow-only symbols 신호 때문에 `WATCH/shadow_signal_only`가 headline이 될 수 있었다.
- 이 경우 실제 live 11개는 모두 fresh live candidate가 없는 상태인데도, 대시보드 headline만 보면 shadow-only 관측이 live 주문 문제처럼 보일 수 있었다.
- 재시작 직후처럼 shadow-only 신호가 없을 때도 global headline candidate symbols가 live 11개가 아니라 tracked universe 전체 14개로 보일 수 있었다.

### 무엇을 수정했는가
- runtime live candidate readiness의 headline scope를 current MICRO_LIVE allowlist 기준으로 보정했다.
- live 11개가 fresh candidate 없음이면 headline은 `WAIT/no_promotable_live_candidate`로 유지하고, `SUI/AAVE/HBAR` 같은 shadow-only 신호는 `shadow_only_auxiliary`로 분리한다.
- compact readiness report에도 `shadow_only_auxiliary`를 출력하게 했다.
- workspace와 runtime_src의 readiness runtime/service script를 동기화하고 runtime stack을 재시작했다.

### 왜 그렇게 판단했는가
- 주문 가능 여부의 1차 truth는 current live allowlist 11개다.
- secondary/tracked-only symbols의 shadow signal은 promotion queue 관측값이지, 현재 주문 미발생의 live blocker가 아니다.
- 따라서 global readiness headline은 live routable symbols 기준이어야 하고, shadow-only symbols는 보조 관측으로 분리되어야 한다.

### 최신 검증 스냅샷
- 테스트:
  - `./.venv/bin/python -m py_compile app/services/live_candidate_promotion_readiness_runtime.py scripts/run_live_candidate_promotion_readiness.py`
  - `./.venv/bin/pytest -q tests/test_live_candidate_promotion_readiness.py::test_runtime_readiness_keeps_shadow_only_as_auxiliary_when_live_symbols_are_waiting tests/test_live_candidate_promotion_readiness.py::test_runtime_readiness_wait_headline_uses_live_symbols_only tests/test_live_candidate_promotion_readiness.py::test_readiness_separates_shadow_signal_from_live_candidate -q`
- runtime 배포:
  - workspace/runtime_src readiness runtime script -> `synced`
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=0 ./scripts/restart_runtime_stack_tmp.sh` -> `/health/ready` ready
- API 확인:
  - global readiness headline -> `WAIT/no_promotable_live_candidate`
  - `headline_scope=live_routable_symbols`
  - `headline_candidate_count=11`
  - headline symbols = `ADA,AVAX,BCH,BNB,BTC,ETH,LINK,LTC,NEAR,SOL,XRP`
  - `shadow_only_auxiliary.symbols=['AAVEUSDC','HBARUSDC','SUIUSDC']`
- current runtime 운영 확인:
  - runtime guard -> `PASS/PASS`
  - current runtime live intent `0`, submit-ready `0`, live submission `0`

## 2026-05-14 Iteration #154
### 무엇을 발견했는가
- readiness API/CLI는 live 11개와 auxiliary 3개를 분리했지만, `execution_operator_ui`의 Live Candidate Review 화면은 새 scope/state count 필드를 직접 보여주지 않았다.
- 이 상태에서는 API payload를 열어보면 정확해도, 실제 운영 화면에서는 `candidate_count=14`와 shadow-only symbols가 live 주문 차단처럼 다시 읽힐 여지가 있었다.

### 무엇을 수정했는가
- 운영 UI의 Live Candidate Review에 다음 값을 명시적으로 표시하게 했다.
  - `Global Scope Counts`: `headline_scope`와 `candidate_scope_counts`
  - `Live State Counts`: live routable symbols 상태 집계
  - `Auxiliary State Counts`: auxiliary display 상태 집계
  - `Auxiliary Shadow Symbols`: `shadow_only_auxiliary.symbols`
- UI 테스트에 위 label과 payload key가 빠지지 않도록 assertion을 추가했다.
- workspace 변경을 `runtime_src`에 동기화하고 runtime stack을 재시작했다.

### 왜 그렇게 판단했는가
- 주문 가능 여부는 live 11개 기준이고, auxiliary 3개는 관측/승격 대기 queue다.
- 이 분리는 백엔드 payload만 맞아서는 부족하다. 실제 operator가 보는 화면에서도 같은 truth separation이 보여야 한다.
- 주문 승인/제출 조건은 바꾸지 않고, 사람이 오해할 수 있는 표시 계층만 보강했다.

### 최신 검증 스냅샷
- 테스트:
  - `./.venv/bin/python -m py_compile app/services/execution_operator_ui.py`
  - `./.venv/bin/pytest -q tests/test_execution_operator_ui.py -q`
  - `git diff --check -- app/services/execution_operator_ui.py tests/test_execution_operator_ui.py`
- runtime 배포:
  - workspace/runtime_src `execution_operator_ui.py` -> `synced`
  - runtime `execution_operator_ui.py` py_compile PASS
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=0 ./scripts/restart_runtime_stack_tmp.sh` -> `/health/ready` ready
- API/UI 확인:
  - `/execution/operator-ui` contains `Global Scope Counts`, `Auxiliary State Counts`, `candidate_scope_counts`, `shadow_only_auxiliary`
  - global readiness -> `WAIT/no_promotable_live_candidate`
  - `headline_scope=live_routable_symbols`
  - `candidate_scope_counts={'total': 14, 'live_routable': 11, 'auxiliary': 3}`
  - `live_state_counts={'NO_FRESH_LIVE_CANDIDATE': 11}`
  - latest auxiliary snapshot -> `AUXILIARY_SHADOW_SIGNAL_ONLY=3`
- current runtime 운영 확인:
  - runtime guard -> `PASS/PASS`
  - runtime_started_at `2026-05-13T18:57:19.849828+00:00`
  - current runtime/current family live intent `0`, submit-ready `0`, live submission `0`

## 2026-05-14 Iteration #155
### 무엇을 발견했는가
- dashboard의 `portfolio_summary.accepted_candidate_count`가 `2`로 보였다.
- 하지만 실제 accepted rows는 `SUIUSDC/legacy_zone_plan`, `NEARUSDC/legacy_zone_plan`이었고, 현재 MICRO_LIVE 주문 경로인 `session_impulse_retest + CONFIRM` 후보가 아니었다.
- 이 숫자는 portfolio/scanner context 후보로는 맞지만, 운영 화면에서는 “주문 후보 2개가 있는데 왜 주문이 안 들어갔나”로 오해될 수 있었다.

### 무엇을 수정했는가
- dashboard payload에 `portfolio_summary.live_route_context`와 `signal_funnel.portfolio_live_route_context`를 추가했다.
- 이 context는 portfolio accepted 후보를 현재 live route 계약 기준으로 다시 분해한다.
  - `live_routable_accepted_candidate_count`
  - `context_only_accepted_candidate_count`
  - `accepted_candidate_route_statuses`
  - active live route family/symbol scope
- 운영 UI의 Top Opportunity와 Portfolio Candidate Drilldown에 `Live Route Context`를 표시하게 했다.
- UI/대시보드 테스트에 해당 context가 빠지지 않도록 assertion을 추가했다.

### 왜 그렇게 판단했는가
- `portfolio_summary`는 후보 탐색/예산 관점이고, 실제 주문 가능 여부의 truth는 `live_candidate_promotion_readiness`다.
- 따라서 portfolio accepted 후보를 삭제하거나 주문 로직에 억지로 연결하지 않고, 현재 live route 주문 후보인지 여부만 명시적으로 분리하는 것이 맞다.
- 이 변경은 주문 승인/제출 조건을 바꾸지 않고, 운영자가 숫자를 잘못 해석할 여지만 줄인다.

### 최신 검증 스냅샷
- 테스트:
  - `./.venv/bin/python -m py_compile app/services/strategy_engine.py app/services/execution_operator_ui.py`
  - `./.venv/bin/pytest -q tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_fast_skips_heavy_research_layers tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_marks_non_route_portfolio_candidates_context_only tests/test_execution_operator_ui.py -q`
  - `git diff --check -- app/services/strategy_engine.py app/services/execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_execution_operator_ui.py`
- runtime 배포:
  - workspace/runtime_src `strategy_engine.py`, `execution_operator_ui.py` -> `synced`
  - runtime py_compile PASS
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=0 ./scripts/restart_runtime_stack_tmp.sh` -> `/health/ready` ready
- API/UI 확인:
  - portfolio accepted candidates -> `2`
  - live route accepted candidates -> `0`
  - context-only accepted candidates -> `2`
  - context-only symbols -> `SUIUSDC`, `NEARUSDC`
  - current live route family -> `session_impulse_retest`
  - current live route headline -> `WAIT/no_promotable_live_candidate`
  - `/execution/operator-ui` contains `Live Route Context`
- current runtime 운영 확인:
  - runtime guard -> `PASS/PASS`
  - no-order watchdog -> `OK/no_recent_live_intents`
  - current runtime/current family live intent `0`, requested live order `0`, submission `0`

## 2026-05-14 Iteration #156
### 무엇을 발견했는가
- Iteration #155 이후 portfolio accepted 후보는 context-only로 분리됐지만, 상단 Approval Strip은 여전히 `approval usable`, 서버 승인 `GO`를 먼저 보여줬다.
- 이 `GO`는 “runtime gate가 열려 있다”는 뜻이지 “현재 live route 주문 후보가 있다”는 뜻이 아니다.
- 하지만 운영 화면에서는 `GO`가 주문 가능 상태처럼 먼저 읽힐 수 있어, no-order 원인 설명과 다시 충돌할 수 있었다.

### 무엇을 수정했는가
- dashboard payload에 `order_route_summary`를 추가했다.
  - `signal_funnel.order_route_summary`
  - `portfolio_summary.order_route_summary`
  - `approval_strip_summary.order_route_approve_value`
- live route accepted 후보가 0이면 `order_route_approve_value=waiting_for_live_candidate`로 표시한다.
- portfolio live route context는 현재 allowed entry model까지 확인하도록 좁혔다.
  - current live route family: `session_impulse_retest`
  - current live route entry model: `CONFIRM`
- 운영 UI의 Approval Strip에 `Order Route Truth`를 추가하고, live route 후보가 없으면 상단 문구를 `신규 진입 게이트는 열려 있지만 현재 live route 주문 후보는 없습니다.`로 표시하게 했다.

### 왜 그렇게 판단했는가
- 안전 게이트가 열려 있는 것과 실제 주문 가능한 후보가 존재하는 것은 다른 truth source다.
- 전자는 `deployment_go_no_go=GO`, 후자는 `live_candidate_promotion_readiness`와 `order_route_summary`가 말해야 한다.
- 주문 조건은 바꾸지 않고, `GO` 문구가 주문 가능 신호처럼 과대해석되는 것만 줄였다.

### 최신 검증 스냅샷
- 테스트:
  - `./.venv/bin/python -m py_compile app/services/strategy_engine.py app/services/execution_operator_ui.py`
  - `./.venv/bin/pytest -q tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_fast_skips_heavy_research_layers tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_marks_non_route_portfolio_candidates_context_only tests/test_execution_operator_ui.py -q`
  - `git diff --check -- app/services/strategy_engine.py app/services/execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_execution_operator_ui.py`
- runtime 배포:
  - workspace/runtime_src `strategy_engine.py`, `execution_operator_ui.py` -> `synced`
  - runtime py_compile PASS
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=0 ./scripts/restart_runtime_stack_tmp.sh` -> `/health/ready` ready
- API/UI 확인:
  - top-level `deployment_go_no_go=GO`
  - `approval_strip_summary.order_route_approve_value=waiting_for_live_candidate`
  - `signal_funnel.order_route_summary.approve_value=waiting_for_live_candidate`
  - live route accepted candidates -> `0`
  - context-only accepted candidates -> `2`
  - current live route family/entry model -> `session_impulse_retest / CONFIRM`
  - current live route headline -> `WAIT/no_promotable_live_candidate`
  - `/execution/operator-ui` contains `Order Route Truth`
- current runtime 운영 확인:
  - no-order watchdog -> `OK/no_recent_live_intents`
  - current runtime/current family live intent `0`, requested live order `0`, submission `0`

## 2026-05-14 Iteration #158
### 무엇을 발견했는가
- `live_route_context`가 symbol/family/entry model은 비교했지만, MICRO_LIVE 계약의 direction/session 축은 아직 표시하지 않았다.
- 실제 승인 계층은 session allowlist와 direction contract도 본다.
- 따라서 나중에 symbol/family/entry model이 맞는 portfolio 후보가 생겨도, direction/session이 맞지 않으면 live-route 후보처럼 보일 수 있었다.

### 무엇을 수정했는가
- `portfolio_summary.live_route_context`가 다음 계약 축까지 비교하게 했다.
  - `active_sessions`
  - `active_direction_contract`
  - candidate `direction`
  - candidate `session_name`
- route status reason에 다음 사유를 추가했다.
  - `direction_not_live_route`
  - `direction_missing_for_live_route`
  - `session_not_live_route`
  - `session_missing_for_live_route`
- dashboard candidate row 요약에서 이미 보존한 `entry_model/direction/session_guidance/validity`를 live route 판정에 사용한다.
- 운영 UI의 `candidateLiveRouteStatus()`도 direction/session까지 비교한다.

### 왜 그렇게 판단했는가
- 주문 가능 여부는 “전략 family만 맞음”이 아니라 현재 MICRO_LIVE 계약 전체와 맞아야 한다.
- direction/session은 실제 approval gate에서 차단될 수 있는 축이므로, operator context에서도 같은 축을 보여줘야 한다.
- 이 변경도 주문 로직이 아니라 관측/해석 계층 보강이다.

### 최신 검증 스냅샷
- 테스트:
  - `./.venv/bin/python -m py_compile app/services/strategy_engine.py app/services/execution_operator_ui.py app/services/execution_operator_dashboard.py`
  - `./.venv/bin/pytest -q tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_fast_skips_heavy_research_layers tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_marks_non_route_portfolio_candidates_context_only tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_keeps_route_match_waiting_until_readiness_allows tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_route_context_checks_direction_and_session tests/test_execution_operator_ui.py -q`
  - `git diff --check -- app/services/strategy_engine.py app/services/execution_operator_ui.py app/services/execution_operator_dashboard.py tests/test_execution_operator_dashboard.py tests/test_execution_operator_ui.py`
- runtime 배포:
  - workspace/runtime_src `strategy_engine.py`, `execution_operator_ui.py`, `execution_operator_dashboard.py` -> `synced`
  - runtime py_compile PASS
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=0 ./scripts/restart_runtime_stack_tmp.sh` -> `/health/ready` ready
- API/UI 확인:
  - `signal_funnel.order_route_summary.approve_value=waiting_for_live_candidate`
  - active sessions -> `dead_session,london,new_york`
  - active direction contract -> live 11 symbols all `LONG|SHORT`
  - current accepted sample -> `TIAUSDC legacy_zone_plan LIMIT SHORT`, `AAVEUSDC legacy_zone_plan SWEEP_CONFIRM SHORT`
  - route status -> `context_only`
  - route reasons -> `symbol_not_live_routable`, `strategy_family_not_live_route`, `entry_model_not_live_route`
- current runtime 운영 확인:
  - no-order watchdog -> `OK/no_recent_live_intents`
  - current runtime/current family live intent `0`, requested live order `0`, submission `0`

## 2026-05-14 Iteration #157
### 무엇을 발견했는가
- Iteration #156의 `order_route_summary`는 `portfolio accepted 후보가 current live route와 매칭되면 available`로 해석될 여지가 있었다.
- 하지만 portfolio row가 symbol/family/entry model과 맞더라도, 실제 주문 truth는 `live_candidate_promotion_readiness`다.
- 또한 dashboard용 portfolio candidate 압축 과정에서 `entry_model`, `entry_type`, `direction`, `validity`가 빠져 live route context가 entry model까지 엄밀히 판단하기 어려웠다.

### 무엇을 수정했는가
- `order_route_summary`의 판단을 portfolio match가 아니라 readiness headline/attention flag 기준으로 보수화했다.
  - live submission 있음 -> `live_submission_observed`
  - submit-ready gap -> `investigate_submit_ready_gap`
  - readiness blocked -> `blocked_by_live_candidate_readiness`
  - shadow-only -> `shadow_only_not_live_route`
  - wait/no fresh -> `waiting_for_live_candidate`
- portfolio candidate row 요약에 `entry_model`, `entry_type`, `direction`, `validity`를 보존하게 했다.
- UI의 `candidateLiveRouteStatus()`도 current live route entry model까지 비교하게 했다.
- route match가 있어도 readiness가 `WAIT/no_promotable_live_candidate`이면 `waiting_for_live_candidate`로 남는 테스트를 추가했다.

### 왜 그렇게 판단했는가
- 실제 fresh 후보가 생기면 runtime은 intent/submission 상태로 말해야 한다.
- 따라서 대시보드가 portfolio match만 보고 `available`에 가까운 표현을 쓰면 또 주문 가능 상태처럼 오해될 수 있다.
- order truth는 끝까지 `live_candidate_promotion_readiness`이며, portfolio match는 context 정보로만 둔다.

### 최신 검증 스냅샷
- 테스트:
  - `./.venv/bin/python -m py_compile app/services/strategy_engine.py app/services/execution_operator_ui.py app/services/execution_operator_dashboard.py`
  - `./.venv/bin/pytest -q tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_fast_skips_heavy_research_layers tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_marks_non_route_portfolio_candidates_context_only tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_keeps_route_match_waiting_until_readiness_allows tests/test_execution_operator_ui.py -q`
  - `git diff --check -- app/services/strategy_engine.py app/services/execution_operator_ui.py app/services/execution_operator_dashboard.py tests/test_execution_operator_dashboard.py tests/test_execution_operator_ui.py`
- runtime 배포:
  - workspace/runtime_src `strategy_engine.py`, `execution_operator_ui.py`, `execution_operator_dashboard.py` -> `synced`
  - runtime py_compile PASS
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=0 ./scripts/restart_runtime_stack_tmp.sh` -> `/health/ready` ready
- API/UI 확인:
  - `signal_funnel.order_route_summary.approve_value=waiting_for_live_candidate`
  - `approval_strip_summary.order_route_approve_value=waiting_for_live_candidate`
  - accepted sample -> `TIAUSDC legacy_zone_plan LIMIT`, `SUIUSDC legacy_zone_plan SWEEP_CONFIRM`
  - current live route -> `session_impulse_retest / CONFIRM`
  - live route accepted candidates -> `0`
  - context-only accepted candidates -> `2`
  - current live route headline -> `WAIT/no_promotable_live_candidate`
- current runtime 운영 확인:
  - no-order watchdog -> `OK/no_recent_live_intents`
  - current runtime/current family live intent `0`, requested live order `0`, submission `0`

## 2026-05-14 Iteration #153
### 무엇을 발견했는가
- Iteration #152 이후 headline은 live 11개 기준으로 맞았지만, `candidate_count=14`와 `state_counts`가 전체 tracked universe 기준이라 여전히 “왜 live 11개인데 14개인가”라는 오해가 남을 수 있었다.
- auxiliary symbols가 fresh signal이 없을 때 `NO_FRESH_LIVE_CANDIDATE`로 보이는 것도 live 후보처럼 읽힐 여지가 있었다.

### 무엇을 수정했는가
- readiness payload에 `candidate_scope_counts`를 추가했다.
  - `total=14`
  - `live_routable=11`
  - `auxiliary=3`
- live/auxiliary 상태를 `live_state_counts`, `auxiliary_state_counts`로 분리했다.
- auxiliary display 전용 상태를 추가해 `AUXILIARY_SHADOW_SIGNAL_ONLY`, `AUXILIARY_TRACKED_NO_FRESH_SIGNAL`처럼 live 후보 상태와 구분되게 했다.
- compact readiness report에도 scope/state 분리 값을 출력하게 했다.

### 왜 그렇게 판단했는가
- 주문 가능성 판단은 live 11개 기준이어야 하고, tracked-only 3개는 관측/승격 대기 queue로 읽혀야 한다.
- 전체 universe count는 유용하지만, live order blocker처럼 보이면 안 된다.
- 따라서 숫자 자체를 숨기기보다 scope를 명시해서 운영자가 현재 live 상태와 auxiliary 관측을 동시에 읽게 하는 편이 낫다.

### 최신 검증 스냅샷
- 테스트:
  - `./.venv/bin/python -m py_compile app/services/live_candidate_promotion_readiness_runtime.py scripts/run_live_candidate_promotion_readiness.py`
  - `./.venv/bin/pytest -q tests/test_live_candidate_promotion_readiness.py::test_runtime_readiness_keeps_shadow_only_as_auxiliary_when_live_symbols_are_waiting tests/test_live_candidate_promotion_readiness.py::test_runtime_readiness_wait_headline_uses_live_symbols_only tests/test_live_candidate_promotion_readiness.py::test_readiness_separates_shadow_signal_from_live_candidate -q`
- runtime 배포:
  - workspace/runtime_src readiness files -> `synced`
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=0 ./scripts/restart_runtime_stack_tmp.sh` -> `/health/ready` ready
- API 확인:
  - global readiness -> `WAIT/no_promotable_live_candidate`
  - `headline_scope=live_routable_symbols`
  - `headline_candidate_count=11`
  - `candidate_scope_counts={'total': 14, 'live_routable': 11, 'auxiliary': 3}`
  - `live_state_counts={'NO_FRESH_LIVE_CANDIDATE': 11}`
  - `auxiliary_display_state_counts={'AUXILIARY_SHADOW_SIGNAL_ONLY': 3}`
- current runtime 운영 확인:
  - runtime guard -> `PASS/PASS`
  - current runtime live intent `0`, submit-ready `0`, live submission `0`

## 2026-05-14 Iteration #159
### 무엇을 발견했는가
- active contract의 핵심 주문 조건은 symbol/family/entry model/direction/session인데, 일부 운영 요약은 session allowlist를 필터로 끝까지 전달하지 않았다.
- 실제 live route context는 `dead_session,london,new_york` 세션 계약을 보지만, active contract execution quality, score-to-outcome funnel, replay flow baseline, recent intent filter는 세션을 명시적으로 좁히지 않아 라이브 주문 경로보다 넓은 기준선으로 읽힐 수 있었다.

### 무엇을 수정했는가
- active contract filters에 `sessions`를 추가했다.
- active contract execution quality와 score-to-outcome funnel 호출에 session filters를 전달하게 했다.
- replay baseline과 same-window replay hit 계산도 `generated_session/session_name/session` 기준으로 session allowlist를 적용하게 했다.
- recent intent active-contract filter가 intent의 `session_guidance.current_session.name`, `session_name`, `state`, plan validity session fields를 읽어 세션까지 비교하게 했다.
- operator dashboard intent row에 `session_guidance`를 보존해, recent intent contract filter가 실제 주문 세션을 잃지 않게 했다.

### 왜 그렇게 판단했는가
- 사용자가 보는 “백테스트/리플레이 기준”과 “실제 주문 가능 기준”은 최대한 같은 계약을 봐야 한다.
- 세션 조건이 리포트에서 빠지면 주문 경로는 좁은데 기준선은 넓게 보여, 또 “왜 백테스트보다 주문이 적지?”라는 오해가 생긴다.
- 이번 변경은 진입 조건을 완화하거나 전략을 바꾸는 것이 아니라, 운영 truth/source-of-truth가 현재 MICRO_LIVE 계약을 더 정확히 표시하게 하는 정합성 보강이다.

### 최신 검증 스냅샷
- 테스트:
  - `./.venv/bin/python -m py_compile app/services/strategy_engine.py app/services/execution_operator_dashboard.py app/services/execution_quality.py app/services/score_to_outcome_funnel.py app/services/execution_operator_ui.py`
  - `./.venv/bin/pytest -q tests/test_strategy_engine_ops.py::test_active_contract_summary_filters_portfolio_budget_to_contract_lane tests/test_strategy_engine_ops.py::test_active_contract_filters_include_direction_contract_and_apply_it tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_intent_row_and_contract_filter_respect_direction tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_route_context_checks_direction_and_session tests/test_score_to_outcome_funnel.py::test_generate_filters_to_active_contract`
  - `./.venv/bin/pytest -q tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_fast_skips_heavy_research_layers tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_marks_non_route_portfolio_candidates_context_only tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_keeps_route_match_waiting_until_readiness_allows tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_route_context_checks_direction_and_session tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_intent_row_and_contract_filter_respect_direction tests/test_execution_operator_ui.py -q`
  - `./.venv/bin/pytest -q tests/test_execution_quality.py::test_execution_quality_report_filters_to_active_contract`
  - `git diff --check`
- runtime 배포:
  - workspace/runtime_src `strategy_engine.py`, `execution_operator_dashboard.py`, `execution_quality.py`, `score_to_outcome_funnel.py` -> `synced`
  - runtime py_compile PASS

## 2026-05-14 Iteration #160
### 무엇을 발견했는가
- Iteration #159에서 세션까지 맞추자 BTC active-contract replay baseline이 `0/week`로 표시됐다.
- 확인 결과 세션 필터 문제가 아니라, active-contract baseline 파일 `strategy_proof_contract_live_subset.json` 자체가 현재 live family인 `session_impulse_retest + CONFIRM` 행을 갖고 있지 않았다.
- 즉 현재 라이브 전략은 SIR인데, 일부 active contract replay 기준선은 과거 sweep-reversal historical cache를 보고 있어 “현재 전략의 백테스트 빈도”로 해석하면 안 되는 상태였다.

### 무엇을 수정했는가
- `active_contract_replay_baseline.py`를 추가해 SIR active contract의 replay 기준선을 `micro_main_usdt_proxy_backtest_*.json`에서 읽게 했다.
- dashboard `replay_flow_baseline`은 family가 `session_impulse_retest`, entry model이 `CONFIRM`이면 USDT proxy backtest의 해당 symbol/direction/session 행으로 expected candidates/week를 계산한다.
- `promotion_shadow_counter.replay_contract_hits_same_window`도 SIR인 경우 같은 USDT proxy rows의 최근 window count를 사용한다.
- sweep-reversal 계열은 기존 historical walk-forward cache 경로를 유지한다.

### 왜 그렇게 판단했는가
- 현재 주문 경로가 SIR인데 replay baseline만 sweep cache를 보면, baseline이 0이거나 엉뚱한 빈도로 보여 운영 판단을 왜곡한다.
- 라이브와 백테스트를 맞춘다는 의미는 조건을 억지로 완화하는 것이 아니라, 비교 기준선도 현재 라이브 전략/진입모델/방향/세션과 같은 데이터 출처를 보게 하는 것이다.

### 최신 검증 스냅샷
- 테스트:
  - `./.venv/bin/python -m py_compile app/services/active_contract_replay_baseline.py app/services/strategy_engine.py app/services/execution_operator_dashboard.py app/services/execution_quality.py app/services/score_to_outcome_funnel.py`
  - `./.venv/bin/pytest -q tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_uses_usdt_proxy_for_sir_active_contract_replay_baseline tests/test_strategy_engine_ops.py::test_active_contract_replay_hits_uses_usdt_proxy_for_session_impulse_retest tests/test_strategy_engine_ops.py::test_active_contract_summary_filters_portfolio_budget_to_contract_lane tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_intent_row_and_contract_filter_respect_direction tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_route_context_checks_direction_and_session`
  - `./.venv/bin/pytest -q tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_fast_skips_heavy_research_layers tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_marks_non_route_portfolio_candidates_context_only tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_keeps_route_match_waiting_until_readiness_allows tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_route_context_checks_direction_and_session tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_intent_row_and_contract_filter_respect_direction tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_uses_usdt_proxy_for_sir_active_contract_replay_baseline tests/test_execution_operator_ui.py -q`
  - `./.venv/bin/pytest -q tests/test_strategy_engine_ops.py::test_active_contract_summary_filters_portfolio_budget_to_contract_lane tests/test_strategy_engine_ops.py::test_active_contract_filters_include_direction_contract_and_apply_it tests/test_strategy_engine_ops.py::test_active_contract_replay_hits_uses_usdt_proxy_for_session_impulse_retest tests/test_score_to_outcome_funnel.py::test_generate_filters_to_active_contract tests/test_score_to_outcome_funnel.py::test_historical_session_uses_submission_guidance_from_attachments tests/test_execution_quality.py::test_execution_quality_report_filters_to_active_contract`
  - `git diff --check`
- runtime 배포:
  - workspace/runtime_src `active_contract_replay_baseline.py`, `strategy_engine.py`, `execution_operator_dashboard.py`, `execution_quality.py`, `score_to_outcome_funnel.py` -> `synced`
  - runtime py_compile PASS
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=0 ./scripts/restart_runtime_stack_tmp.sh` -> `/health/ready` ready
- API/운영 확인:
  - BTC active contract replay baseline source -> `micro_main_usdt_proxy_backtest_20260510T153136Z.json`
  - BTC SIR/CONFIRM replay trade count -> `134`
  - BTC expected active-contract candidates/week from replay -> `0.8566`
  - `order_route_summary.approve_value=waiting_for_live_candidate`
  - runtime guard -> `PASS/PASS`
  - no-order watchdog -> `OK/no_recent_live_intents`

## 2026-05-15 Iteration #161
### 무엇을 발견했는가
- 최근 30일 SIR opportunity report 기준 주문 가능 후보는 44건이었다.
  - `missing_intent`: 28건, +10.980038R, 마지막 발생 2026-05-08 UTC.
  - `validation_do_not_deploy`: 4건, +5.529626R.
  - `rollout_session_not_allowed`: 6건, +4.346486R.
  - `session_impulse_retest_rollout_not_ready`: 6건, +3.069638R.
- `rollout_session_not_allowed` 6건은 모두 replay/session bucket 기준으로는 `dead_session`이었지만, execution approval 메시지는 `Current session inactive is outside...`로 남았다.
- 현재 live contract는 `dead_session,london,new_york`를 허용한다. 그런데 approval 세션 판정은 operating lock의 raw `inactive`를 session guidance의 canonical `dead_session`보다 먼저 사용했다.
- 결과적으로 같은 상태가 session guidance에서는 `dead_session`, execution approval에서는 `inactive`로 읽혀 롤아웃 세션 allowlist와 불일치할 수 있었다.

### 무엇을 수정했는가
- `ExecutionPlanningService._session_name()`이 session guidance의 `state=dead_session` 또는 `dead_session=true`를 우선 canonical bucket으로 사용하게 했다.
- operating lock/current session name이 `inactive`일 때도 execution approval 내부에서는 `dead_session`으로 정규화하게 했다.
- approval payload의 `safety_state.session_name`도 정규화된 세션명을 기록해, 이후 로그에서 `inactive`와 `dead_session`이 섞여 보이지 않게 했다.
- 회귀 테스트를 추가했다.
  - `dead_session`이 rollout/micro-live contract에 포함되면 `inactive` raw session이어도 `APPROVED_AUTO`까지 간다.
  - contract에서 `dead_session`을 제외하면 여전히 `rollout_session_not_allowed`로 막힌다.

### 왜 그렇게 판단했는가
- 세션을 완화한 것이 아니라, 이미 허용한 canonical bucket(`dead_session`)과 운영 raw state(`inactive`)를 같은 의미로 맞춘 것이다.
- 이 불일치가 남으면 사용자는 “백테스트는 dead_session 기회로 잡는데 live는 inactive라서 막힘”이라는 식의 모순을 계속 보게 된다.
- 반대로 contract에서 `dead_session`을 빼면 지금도 차단되므로, 안전 검증 계층은 유지된다.

### 최신 검증 스냅샷
- 30일 SIR opportunity report:
  - report: `reports/validation/micro_main_opportunity_reports/session_impulse_retest_opportunity_report_20260514T155802Z.json`
  - expected_order_count: `44`
  - potential_performance: `+23.925788R`, win_rate `65.9091%`
  - live submission: `0`
  - paper submission: `6`
- 테스트:
  - `./.venv/bin/python -m pytest -q tests/test_auto_trading_transition_phase1.py::test_approval_service_maps_inactive_dead_session_to_rollout_bucket tests/test_auto_trading_transition_phase1.py::test_approval_service_blocks_dead_session_when_rollout_contract_excludes_it tests/test_auto_trading_transition_phase1.py::test_approval_service_keeps_sir_live_bootstrap_degradation_advisory_without_execution_sample tests/test_auto_trading_transition_phase1.py::test_approval_service_downgrades_sir_when_execution_degradation_has_material_sample -q`
  - `./.venv/bin/python -m py_compile app/services/execution_approval.py`
  - `./.venv/bin/python -m pytest -q tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_notification_dispatcher.py tests/test_api_smoke.py -q`
  - `git diff --check`
- runtime 배포:
  - runtime_src `execution_approval.py` -> `synced`
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=true /Users/yumin/Library/Application Support/trading/runtime_src/scripts/restart_runtime_stack_tmp.sh` -> `/health/ready` ready
  - runtime loaded policy check -> `dead_session,london,new_york`
  - runtime probe -> `APPROVED_AUTO dead_session micro_live_rollout_enabled`

## 2026-05-15 Iteration #162
### 무엇을 발견했는가
- 전체 로컬 SIR attribution 가능 기간은 1m candle 기준 2025-11-11 이후다.
- 3년 proxy backtest 파일 자체는 2023-05-12~2026-05-10, 4,399 trades, `+2815.8915R`, EV `+0.6401R`를 갖지만, live/runtime attribution은 로컬 1m candle이 있는 기간만 정확히 비교할 수 있다.
- 전체기간 opportunity report(lookback 30000h) 기준 SIR 기회는 567건이었다.
  - `blocked_or_skipped`: 16건, `+12.94575R`.
  - `pre_runtime_backfill_without_intent`: 545건, `+378.253695R`.
  - `pre_runtime_unobservable`: 6건, `+7.951316R`.
- 기존 report는 현재 runtime 시작 전 backfill 구간도 `observed_without_intent/missing_intent`로 표시했다.
- 이 표현은 실제 runtime이 봤는데 주문 intent를 만들지 않은 것처럼 읽힐 수 있어, 전체기간 분석에서 가장 큰 오해 요인이었다.

### 무엇을 수정했는가
- `scripts/run_session_impulse_retest_opportunity_report.py`의 status attribution을 보강했다.
  - submission/intents가 있으면 기존처럼 실제 execution truth를 우선한다.
  - 현재 runtime 시작 전이고 intent가 없으면 `pre_runtime_backfill_without_intent/before_runtime_start`로 분리한다.
  - 현재 runtime 시작 전이면서 candle preload가 부족하면 `pre_runtime_unobservable/before_runtime_start_insufficient_candles`로 분리한다.
  - 현재 runtime 이후 미관측이면 observation reason을 그대로 유지한다.
- `tests/test_script_entrypoints.py`에 pre-runtime backfill과 live intent truth 우선순위 회귀 테스트를 추가했다.

### 왜 그렇게 판단했는가
- 전체기간의 551/567건은 현재 runtime 시작 이전이다.
- 이것을 live 미스나 주문 버그로 세면 “백테스트 기회가 있었는데 시스템이 주문 intent를 안 만들었다”는 잘못된 결론이 된다.
- 실제로 주문 판단까지 간 뒤 막힌 전체기간 케이스는 16건뿐이고, 원인은 이미 분리된 3개다.
  - `validation_do_not_deploy`: 4건, 검증 게이트 유지.
  - `rollout_session_not_allowed`: 6건, Iteration #161에서 `inactive -> dead_session` 정규화로 수정.
  - `session_impulse_retest_rollout_not_ready`: 6건, bootstrap readiness/advisory split 수정으로 해소.

### 최신 검증 스냅샷
- 전체기간 SIR opportunity report:
  - report: `reports/validation/micro_main_opportunity_reports/session_impulse_retest_opportunity_report_20260514T161931Z.json`
  - expected_order_count: `567`
  - status_counts: `blocked_or_skipped=16`, `pre_runtime_backfill_without_intent=545`, `pre_runtime_unobservable=6`
  - potential_performance: `+399.150761R`, win_rate `68.6067%`
  - live submission: `0`
- 3년 proxy backtest reference:
  - source: `micro_main_usdt_proxy_backtest_20260510T153136Z.json`
  - days: `1095`
  - trades: `4399`
  - aggregate: `+2815.8915R`, EV `+0.6401R`
- 테스트:
  - `./.venv/bin/python -m py_compile scripts/run_session_impulse_retest_opportunity_report.py app/services/execution_approval.py`
  - `./.venv/bin/python -m pytest -q tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_notification_dispatcher.py tests/test_api_smoke.py -q`

## 2026-05-15 Iteration #163
### 무엇을 비교했는가
- SIR 기준선을 세 겹으로 분리해 비교했다.
  - 3년 proxy backtest: `micro_main_usdt_proxy_backtest_20260510T153136Z.json`
  - current live-route opportunity replay: `session_impulse_retest_opportunity_report_20260514T161931Z.json`
  - runtime execution truth: `order_intents`, `order_submissions`

### 핵심 수치
- 3년 proxy backtest 전체:
  - period: 2023-05-12~2026-05-10
  - entries: `4399`
  - entries/day: `4.021`
  - total: `+2815.8915R`
  - avg: `+0.640121R`
  - win_rate: `65.674%`
  - 1% risk simple annualized: `~939.48%`
- proxy와 current opportunity가 겹치는 기간(2025-11-11~2026-05-10):
  - proxy: `653` entries, `3.615/day`, `+477.7255R`, avg `+0.731586R`, win_rate `69.066%`
  - current opportunity replay: `556` entries, `3.078/day`, `+393.106101R`, avg `+0.707025R`, win_rate `68.705%`
  - net entry delta: `-97` entries, `-14.85%`
  - avg R delta: `-3.36%`
- current opportunity full local window:
  - period: 2025-11-11~2026-05-14
  - entries: `567`
  - entries/day: `3.077`
  - total: `+399.150761R`
  - avg: `+0.70397R`
  - win_rate: `68.6067%`
- runtime execution truth:
  - SIR intents: `27`
  - live submissions: `0`
  - paper submissions: `6`
  - blocked opportunities matched to replay: `16`, `+12.94575R`

### 차이 해석
- current opportunity replay의 진입 빈도 `3.077/day`는 사용자가 기대한 “하루 약 3회”와 거의 일치한다.
- 3년 proxy 전체 평균 `4.021/day`와 비교하면 현재 live-route replay는 낮지만, 같은 기간 current opportunity 기준으로 보면 `3/day` 근처가 맞다.
- proxy overlap `653` vs current opportunity `556`의 `-14.85%` 차이는 주문 게이트 문제가 아니라 benchmark drift다.
  - proxy는 USDT 장기 proxy backtest 기준이다.
  - current opportunity는 현재 코드와 USDC live-route candle 기준으로 재계산한다.
  - exact entry timestamp match는 완전하지 않아, 두 파일을 같은 truth로 보면 안 된다.
- 따라서 앞으로 운영 판단은 아래처럼 분리한다.
  - 전략 장기 기대치: proxy 3년 backtest.
  - 현재 live 후보 빈도: current opportunity replay.
  - 실제 주문 여부: order_intents/order_submissions.

### 모순이 잡히고 있는지
- 이전에는 `missing_intent`가 큰 문제처럼 보였지만, Iteration #162 이후 pre-runtime backfill로 분리되어 live 미스로 과대계상되지 않는다.
- 실제 live 판단 구간에서 남은 구조적 모순은 이미 분류됐다.
  - `rollout_session_not_allowed`: `inactive -> dead_session` 정규화로 수정.
  - `session_impulse_retest_rollout_not_ready`: bootstrap advisory split로 수정.
  - `validation_do_not_deploy`: 검증 게이트라 유지.
- 새로 발견한 drift는 “백테스트 원본과 현재 live-route replay가 완전 동일하지 않다”는 기준선 drift이며, 주문 차단 버그와는 별도다.

## 2026-05-15 Iteration #164
### 현재 runtime 상태
- `/health/ready`: ready.
- `live_candidate_promotion_readiness --since-ws-start`:
  - state: `WAIT`
  - reason: `no_promotable_live_candidate`
  - live_routable: `11`
  - live_state_counts: `NO_FRESH_LIVE_CANDIDATE=11`
  - auxiliary: `AAVEUSDC,HBARUSDC,SUIUSDC` as `SHADOW_SIGNAL_ONLY`
  - top_intent_reasons: `{}`
- `run_micro_live_no_order_watchdog`:
  - status: `OK`
  - reason: `no_recent_live_intents`
  - live intent: `0`
  - submit_ready: `0`
  - live submission: `0`
- 최근 6시간 opportunity report:
  - expected_order_count: `0`
  - 해석: 현재는 후보가 있었는데 막힌 상태가 아니라, 실제 SIR live 후보가 아직 없는 상태다.

### 추가로 발견한 관측성 모순
- SIR runtime audit에서 `status=no_fresh_candidates`인데 payload summary의 `generation_state=generated`가 같이 보여 운영자가 “SIR 후보가 생성됐는데 왜 no_fresh?”로 읽을 수 있었다.
- 실제 의미는 다르다.
  - `status=no_fresh_candidates`: SIR live-route 후보 없음.
  - `plan_generation_diagnostics.generation_state=generated`: 일반/레거시 plan 생성됨.
- 즉 주문 경로 문제는 아니지만, 현재 상황을 해석하는 데 방해되는 observability drift였다.

### 무엇을 수정했는가
- `StrategyEngine.refresh_symbol()` response에 `legacy_plan_generation_state`와 `session_impulse_retest_generation_state`를 분리해 기록하게 했다.
- `scripts/run_session_impulse_retest_runtime_audit_report.py` compact summary도 아래처럼 분리한다.
  - `generation_state`: SIR 기준 상태.
  - `session_impulse_retest_generation_state`: SIR 기준 상태 명시.
  - `legacy_plan_generation_state`: 일반 plan generation 상태.
- 회귀 테스트:
  - 일반 plan은 `generated`지만 SIR count가 `0`이면 audit summary의 `generation_state`는 `no_fresh_candidates`로 유지된다.

### 최신 검증 스냅샷
- 테스트:
  - `./.venv/bin/python -m py_compile app/services/strategy_engine.py scripts/run_session_impulse_retest_runtime_audit_report.py`
  - `./.venv/bin/python -m pytest -q tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_notification_dispatcher.py tests/test_api_smoke.py -q`
  - `git diff --check`
- runtime 배포:
  - runtime_src `strategy_engine.py`, `run_session_impulse_retest_runtime_audit_report.py` -> `synced`
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=true /Users/yumin/Library/Application Support/trading/runtime_src/scripts/restart_runtime_stack_tmp.sh` -> `/health/ready` ready
- runtime audit 확인:
  - refresh rows now show `generation_state=no_fresh_candidates`
  - when generic plans exist, separate field shows `legacy_plan_generation_state=generated`

## 2026-05-15 Iteration #165
### 추가 확인한 운영 오해 지점
- 최근 audit에 `ws_stream_active_route_suppressed`가 많이 찍혔지만, 이것은 주문 차단이 아니다.
- 의미:
  - websocket stream worker가 live routing owner다.
  - sync-universe/backfill worker는 같은 후보를 중복 라우팅하지 않도록 auto-route를 생략한다.
  - 따라서 이 status는 duplicate-route guard이지, submit gate/blocker가 아니다.
- 코드에 아래 payload 필드를 추가해 리포트에서 바로 구분되게 했다.
  - `route_owner=ws_stream`
  - `suppression_scope=sync_universe_duplicate_route_guard`
  - `blocking_live_route=false`
  - `reason_detail=Sync-universe worker skipped duplicate auto-route ...`

### Discord entry surface 알림 정리
- `LIVE_ORDER_CANDIDATE=0`인데도 context/review 후보 변화만으로 Discord 알림이 반복되는 운영 UX 문제가 있었다.
- 이것은 주문 엔진 문제는 아니지만, 사용자가 “진입 확인신호인데 주문이 안 들어감”으로 오해하기 쉬운 노이즈였다.
- 수정 후 Discord 발송 기준:
  - live 주문 후보가 1개 이상이면 발송.
  - live-routable 후보가 실제로 blocked 상태면 발송.
  - context-only/review-only 후보 변화는 latest report에는 남기되 Discord로 반복 발송하지 않는다.

### 현재 해석
- 지금 주문이 안 들어가는 직접 원인은 fresh `session_impulse_retest` live 후보가 아직 없기 때문이다.
- 최근 entry surface의 `CONTEXT_REVIEW_SETUP`은 대부분 legacy/context-only 후보이며, 현재 live-route contract와 다르다.
- 주문 진입 신호로 봐야 하는 것은 `LIVE_ORDER_CANDIDATE > 0` 또는 order intent의 `submit_ready`/submission truth다.

### 검증
- targeted:
  - `./.venv/bin/python -m py_compile app/services/strategy_engine.py scripts/run_session_impulse_retest_runtime_audit_report.py scripts/notify_entry_surface.py`
  - `./.venv/bin/python -m pytest -q tests/test_script_entrypoints.py::test_session_impulse_retest_runtime_audit_summary_marks_ws_suppression_non_blocking tests/test_entry_surface_scripts.py::test_context_only_surface_is_not_discord_alertable tests/test_entry_surface_scripts.py::test_live_routable_blocked_surface_remains_discord_alertable tests/test_session_impulse_retest_execution_path.py::test_sync_universe_suppresses_auto_route_when_ws_stream_is_active -q`
- broad:
  - `./.venv/bin/python -m pytest -q tests/test_entry_surface_scripts.py tests/test_notification_dispatcher.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_api_smoke.py -q`
  - `git diff --check`
- runtime:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=true /Users/yumin/Library/Application Support/trading/runtime_src/scripts/restart_runtime_stack_tmp.sh` -> `/health/ready` ready.
  - `notify_entry_surface.py --dry-run`: `LIVE_ORDER_CANDIDATE=0`, `CONTEXT_REVIEW_SETUP=2`, `BLOCKED_SETUP=3`, `reason=no_alertable_rows`, `notified=false`.
  - `live_candidate_promotion_readiness --since-ws-start`: `WAIT/no_promotable_live_candidate`, live-routable `11`, all `NO_FRESH_LIVE_CANDIDATE`.
  - `run_micro_live_no_order_watchdog`: `OK/no_recent_live_intents`, `submit_ready=0`, `blocked=0`, `submission_count=0`.
  - recent 6h opportunity: `expected_order_count=0`.

## 2026-05-15 Iteration #166
### 추가 개선: readiness blocker scope 분리
- `live_candidate_promotion_readiness` compact 출력의 `top_blockers`는 live-routable 심볼과 auxiliary/shadow-only 심볼을 섞어 보여줬다.
- 이 때문에 `symbol_not_live_enabled_for_auto_route` 같은 보조 심볼 상태가 live 주문 차단처럼 보일 수 있었다.
- 출력에 아래 필드를 추가했다.
  - `top_live_blockers`: 현재 live route 대상 심볼만 집계.
  - `top_auxiliary_blockers`: shadow-only/보조 관측 심볼만 집계.
- 최신 런타임 확인:
  - `top_live_blockers={'no_fresh_live_candidate': 11}`
  - `top_auxiliary_blockers={'no_fresh_live_candidate': 2, 'symbol_not_live_enabled_for_auto_route': 1}`
  - 해석: live 대상 11개는 막힌 것이 아니라 fresh 후보 대기 상태다.

### 재검증
- `./.venv/bin/python -m py_compile app/services/live_candidate_promotion_readiness_runtime.py scripts/run_live_candidate_promotion_readiness.py`
- `./.venv/bin/python -m pytest -q tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_notification_dispatcher.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_api_smoke.py -q`
- `git diff --check`

- runtime 재시작 후 `/health/ready`: ready.
- no-order watchdog: `OK/no_recent_live_intents`, `submit_ready=0`, `blocked=0`, `submission_count=0`.
- recent 6h opportunity: `expected_order_count=0`.
- entry surface dry-run: `LIVE_ORDER_CANDIDATE=0`, `reason=no_alertable_rows`, `notified=false`.

## 2026-05-15 Iteration #167
### 추가 개선: entry surface 제목 로직을 실제 entry surface 메시지에만 적용
- `run_micro_live_no_order_watchdog.py`, `run_micro_live_ops_heartbeat.py`, `run_live_reconciliation_watchdog.py`는 Discord 발송 타입으로 `entry_surface_alert`를 재사용한다.
- 이전 dispatcher는 `entry_surface_alert`면 메시지 내용과 무관하게 `live_order_candidates`를 파싱했고, marker가 없으면 0으로 처리했다.
- 그래서 실제 운영 경고가 “주문 후보 없음” 제목으로 약하게 보일 수 있었다.
- 수정 후:
  - 메시지에 `live_order_candidates=`가 있을 때만 entry surface 제목 규칙을 적용한다.
  - watchdog/ops/reconciliation 같은 운영 경고는 기본 `[운영] {symbol} 확인 필요` 제목을 유지한다.
  - 실제 entry surface에서 `live_order_candidates=0`이면 여전히 `[모니터링] ... 주문 후보 없음`으로 표시된다.

### 검증
- `./.venv/bin/python -m py_compile app/services/notification_dispatcher.py`
- `./.venv/bin/python -m pytest -q tests/test_notification_dispatcher.py::test_dispatcher_entry_surface_context_only_title_is_monitoring tests/test_notification_dispatcher.py::test_dispatcher_entry_surface_live_candidate_title_requires_attention tests/test_notification_dispatcher.py::test_dispatcher_entry_surface_alert_without_entry_counts_uses_operational_title -q`
- `./.venv/bin/python -m pytest -q tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_api_smoke.py -q`
- `git diff --check`

## 2026-05-15 Iteration #168
### 추가 개선: `/portfolio/budget` 원본 응답에도 order route truth 부착
- `notify_entry_surface.py`와 operator dashboard는 live-route truth를 붙이고 있었지만, 원본 `/portfolio/budget?fast=true` 응답은 여전히 `accepted_candidates`만 보여줬다.
- 이 상태에서는 API/리포트 사용자가 `accepted_count=2`를 live 주문 후보 2개로 오해할 수 있었다.
- 수정 후 `portfolio_budget_report` 응답/리포트에 아래 필드가 포함된다.
  - root: `live_route_contract`
  - root: `portfolio_live_route_context`
  - root: `order_route_summary`
  - root: `order_route_truth`
  - candidate row: `entry_surface_route`
  - candidate row: `live_routable`
- 현재 live contract 밖 후보는 `entry_surface_route.status=context_only`, `live_routable=false`, `reasons=[...]`로 표시된다.

### 추가 수정: operating lock snapshot의 시간 기준 고정
- 운영락 snapshot이 내부 repository 조회에서는 실제 현재 시각을 사용하고, lock 평가에는 호출자가 넘긴 `now`를 사용하는 불일치가 있었다.
- replay/test/frozen runtime에서는 종료 거래와 submission이 조회 window에서 빠져 daily operating lock이 열려 보일 수 있다.
- `PlanRepository.list_recent_global()`와 `OrderSubmissionRepository.list_recent()`에 optional `now`를 추가했고, `StrategyEngine._operating_lock_snapshot()`이 같은 `now`를 전달하게 했다.

### 검증
- `./.venv/bin/python -m py_compile app/db/repositories.py app/services/strategy_engine.py app/services/portfolio_budget_report.py app/schemas/api.py`
- `./.venv/bin/python -m pytest -q tests/test_portfolio_budget_report.py::test_portfolio_budget_report_reflects_daily_operating_lock tests/test_api_smoke.py::test_health_and_bootstrap_flow -q`
- `./.venv/bin/python -m pytest -q tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py -q`
- `git diff --check`

## 2026-05-15 Iteration #169
### 추가 개선: operator UI의 accepted/context-only 표현 정리
- `Portfolio Candidate Drilldown`과 `Portfolio Candidate Inspector`에는 아직 `Accepted Candidate`라는 표현이 남아 있었다.
- 이 표현은 portfolio overlay가 문맥상 받아들인 후보를 실제 주문 후보처럼 읽히게 만들 수 있었다.
- 수정 후 화면 표현을 아래처럼 분리했다.
  - `Portfolio Accepted (Context)`: portfolio 문맥 후보 수.
  - `Live Route`: 실제 live route 후보 여부.
  - `Order Route`: 카드에서도 live route/context-only와 route reason을 직접 표시.
  - `Representative Portfolio Accepted Candidate`: 대표 카드가 주문 후보가 아니라 portfolio accepted context임을 명시.
- `Signal Funnel Inspector`의 `Runtime/Accepted` 배지도 `Runtime / Portfolio Context`로 바꿔, accepted count를 주문 승인 count로 오해하지 않게 했다.

### 현재 운영 해석
- 주문 진입 신호는 `LIVE_ORDER_CANDIDATE > 0`, `order_intent.submit_ready`, 실제 submission/fill truth다.
- `portfolio accepted`는 전략/포트폴리오 문맥 후보이며, `Live Route`가 `live route`가 아니면 주문 후보가 아니다.
- 따라서 현재처럼 `accepted_count > 0`이더라도 `live_routable_accepted_candidate_count=0`이면 주문이 안 들어가는 것이 정상이다.

### 검증
- `./.venv/bin/python -m py_compile app/services/execution_operator_ui.py`
- `./.venv/bin/python -m pytest -q tests/test_execution_operator_ui.py tests/test_api_smoke.py::test_health_and_bootstrap_flow -q`
- `./.venv/bin/python -m pytest -q tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py -q`
- `git diff --check`
- runtime 재시작 후 `/health/ready`: ready.
- operator UI HTML 확인:
  - `Runtime / Portfolio Context`
  - `Portfolio Accepted (Context)`
  - `Representative Portfolio Accepted Candidate`
  - `Order Route`
- runtime 상태:
  - `/portfolio/budget`: `accepted_count=2`, `live_routable_accepted_candidate_count=0`, `context_only_accepted_candidate_count=2`, `approve_value=portfolio_context_only_no_live_route_candidate`.
  - `live_candidate_promotion_readiness --since-ws-start`: `WAIT/no_promotable_live_candidate`, `top_live_blockers={'no_fresh_live_candidate': 11}`.
  - `run_micro_live_no_order_watchdog`: `OK/no_recent_live_intents`, `submit_ready=0`, `blocked=0`, `submission_count=0`.
  - recent 6h SIR opportunity: `expected_order_count=0`.
  - `notify_entry_surface.py --dry-run`: `LIVE_ORDER_CANDIDATE=0`, `CONTEXT_REVIEW_SETUP=2`, `BLOCKED_SETUP=3`, `notified=false`, `reason=no_alertable_rows`.

## 2026-05-15 Iteration #170
### 추가 개선: portfolio markdown report의 accepted 표현 정리
- `/portfolio/budget` API 필드명 `accepted_candidates`는 호환성을 위해 유지한다.
- 사람이 읽는 markdown report에는 `## Accepted Candidates`가 남아 있어, 주문 후보처럼 오해될 수 있었다.
- 수정 후 markdown report 표현을 아래처럼 바꿨다.
  - `portfolio_accepted_context_count`
  - `live_route_accepted_count`
  - `context_only_accepted_count`
  - `## Portfolio Accepted Candidates (Context)`
- 각 accepted row에도 `live_routable`, `route_status`, `route_reasons`를 같이 남긴다.

### 검증
- `./.venv/bin/python -m py_compile app/services/portfolio_budget_report.py`
- `./.venv/bin/python -m pytest -q tests/test_portfolio_budget_report.py tests/test_api_smoke.py::test_health_and_bootstrap_flow -q`
- `./.venv/bin/python -m pytest -q tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py -q`
- `git diff --check`
- runtime 재시작 후 `/health/ready`: ready.
- runtime markdown report 확인:
  - path: `/Users/yumin/Library/Application Support/trading/reports/portfolio/budget_usdc_perp_top30_a_only_20260515T042015Z.md`
  - `portfolio_accepted_context_count=2`
  - `live_route_accepted_count=0`
  - `context_only_accepted_count=2`
  - `## Portfolio Accepted Candidates (Context)`
  - accepted rows include `live_routable=False`, `route_status=context_only`, `route_reasons=[...]`.
- runtime 상태:
  - `live_candidate_promotion_readiness --since-ws-start`: `WAIT/no_promotable_live_candidate`, `top_live_blockers={'no_fresh_live_candidate': 11}`.
  - recent 6h SIR opportunity: `expected_order_count=0`.
  - `run_micro_live_no_order_watchdog`: `OK/no_recent_live_intents`, `submit_ready=0`, `blocked=0`, `submission_count=0`.

## 2026-05-15 Iteration #173
### 추가 개선: operator dashboard active-contract filter의 dead_session 정규화
- `execution_operator_dashboard.py`에도 별도 `_row_session_name()`이 남아 있었다.
- 이 parser도 `session_guidance.state=dead_session`보다 `current_session.name=inactive`를 먼저 읽을 수 있어, active-contract filter/replay cadence comparison에서 dead_session 후보를 잘못 제외할 여지가 있었다.
- dashboard도 `live_route_contract.row_session_name()` 공통 helper를 쓰게 바꿨다.
- 추가 테스트로 `state=dead_session`, `current_session.name=inactive` row가 `sessions=['dead_session']` contract filter를 통과하는지 고정했다.

### 검증
- `./.venv/bin/python -m py_compile app/services/execution_operator_dashboard.py app/services/live_route_contract.py`
- `./.venv/bin/python -m pytest -q tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_contract_filter_maps_dead_session_guidance tests/test_execution_operator_dashboard.py::test_execution_operator_dashboard_route_context_checks_direction_and_session tests/test_execution_operator_dashboard.py -q`
- `./.venv/bin/python -m pytest -q tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py -q`
- `git diff --check`
- runtime 재시작 후 `/health/ready`: ready.
- runtime operator dashboard:
  - `accepted=2`, `live=0`, `context=2`, `order_route_summary.approve_value=waiting_for_live_candidate`.
  - accepted route rows now show `session_name=dead_session` and no false `session_not_live_route`.
- runtime no-order watchdog:
  - `OK/no_recent_live_intents`, `submit_ready=0`, `blocked=0`, `submission_count=0`.
- runtime readiness:
  - `WAIT/no_promotable_live_candidate`, `top_live_blockers={'no_fresh_live_candidate': 11}`.

## 2026-05-15 Iteration #174
### 추가 개선: StrategyEngine active-contract filter의 dead_session 정규화
- `StrategyEngine._row_session_name()`도 별도 구현으로 남아 있었다.
- 이 함수는 `_row_matches_contract_filters()`, `_filtered_portfolio_summary()`, active-contract replay hit 계산에서 사용된다.
- 따라서 `session_guidance.state=dead_session` + `current_session.name=inactive` row가 active-contract filter에서 제외될 여지가 있었다.
- 수정 후 `StrategyEngine`도 `live_route_contract.row_session_name()` 공통 helper를 사용한다.
- strategy family / entry model / direction row parser도 같은 helper로 맞췄다.

### 검증
- 신규 테스트:
  - `test_active_contract_filters_map_dead_session_guidance`
- `./.venv/bin/python -m py_compile app/services/strategy_engine.py app/services/live_route_contract.py`
- `./.venv/bin/python -m pytest -q tests/test_strategy_engine_ops.py::test_active_contract_filters_include_direction_contract_and_apply_it tests/test_strategy_engine_ops.py::test_active_contract_filters_map_dead_session_guidance tests/test_strategy_engine_ops.py::test_active_contract_replay_hits_uses_usdt_proxy_for_session_impulse_retest -q`
- `./.venv/bin/python -m pytest -q tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py -q`
- `git diff --check`
- runtime 재시작 후 `/health/ready`: ready.
- runtime 상태:
  - `live_candidate_promotion_readiness --since-ws-start`: `WAIT/no_promotable_live_candidate`, `top_live_blockers={'no_fresh_live_candidate': 11}`.
  - `run_micro_live_no_order_watchdog`: `OK/no_recent_live_intents`, `submit_ready=0`, `blocked=0`, `submission_count=0`.
  - `/portfolio/budget`: `accepted=2`, `live=0`, `context=2`.
  - route rows: `DOGEUSDC/TIAUSDC session_name=dead_session`, reasons no false `session_not_live_route`.

## 2026-05-15 Iteration #176
### 추가 개선: 저장 validity와 portfolio overlay session bucket 정규화
- PlanGenerator는 dead session에서 `session_guidance_state=dead_session`과 `session_guidance_session_name=inactive`를 같이 저장할 수 있다.
- 공통 helper가 validity의 `session_guidance_session_name`을 먼저 읽으면, 리포트/필터에서 다시 `inactive`가 살아날 수 있었다.
- 수정 후:
  - validity에서 `session_guidance_state=dead_session`이면 `session_guidance_session_name=inactive`보다 우선한다.
  - `portfolio_risk_overlay.py`의 capital allocator / outcome bias session bucket도 공통 helper를 사용한다.
- 이로써 portfolio overlay, score-to-outcome, execution quality, live-route truth가 같은 dead-session bucket을 본다.

### 검증
- 신규 테스트:
  - `test_portfolio_overlay_session_name_maps_dead_session_before_inactive_name`
- `./.venv/bin/python -m py_compile app/services/live_route_contract.py app/services/portfolio_risk_overlay.py app/services/execution_quality.py app/services/score_to_outcome_funnel.py`
- `./.venv/bin/python -m pytest -q tests/test_portfolio_overlay.py::test_portfolio_overlay_session_name_maps_dead_session_before_inactive_name tests/test_execution_quality.py::test_execution_quality_session_name_maps_dead_session_state tests/test_score_to_outcome_funnel.py::test_historical_session_maps_dead_session_attachment_before_inactive_name tests/test_score_to_outcome_funnel.py::test_runtime_session_maps_dead_session_guidance_before_inactive_name -q`
- `./.venv/bin/python -m pytest -q tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py -q`
- `git diff --check`
- runtime 재시작 후 `/health/ready`: ready.
- runtime 상태:
  - `live_candidate_promotion_readiness --since-ws-start`: `WAIT/no_promotable_live_candidate`, `top_live_blockers={'no_fresh_live_candidate': 11}`.
  - `run_micro_live_no_order_watchdog`: `OK/no_recent_live_intents`, `submit_ready=0`, `blocked=0`, `submission_count=0`.
  - `/portfolio/budget`: `accepted=2`, `live=0`, `context=2`.
  - route rows: `DOGEUSDC/TIAUSDC session_name=dead_session`, reasons no false `session_not_live_route`.

## 2026-05-15 Iteration #175
### 추가 개선: execution quality / score-to-outcome session bucket 정규화
- `score_to_outcome_funnel.py`와 `execution_quality.py`에도 별도 session parser가 남아 있었다.
- 이 경로는 주문 제출 경로는 아니지만, 운영/검증 리포트에서 `dead_session` 표본이 `inactive`로 갈라져 보일 수 있다.
- 수정 후:
  - runtime row session bucket은 `live_route_contract.row_session_name()`을 사용한다.
  - submission attachment/raw session guidance도 같은 helper로 해석한다.
  - execution quality plan session bucket도 같은 helper로 해석한다.
- `session_guidance.state=dead_session` + `current_session.name=inactive`이면 리포트 계층도 `dead_session`으로 기록한다.

### 검증
- 신규 테스트:
  - `test_historical_session_maps_dead_session_attachment_before_inactive_name`
  - `test_runtime_session_maps_dead_session_guidance_before_inactive_name`
  - `test_execution_quality_session_name_maps_dead_session_state`
- `./.venv/bin/python -m py_compile app/services/score_to_outcome_funnel.py app/services/execution_quality.py app/services/live_route_contract.py`
- `./.venv/bin/python -m pytest -q tests/test_score_to_outcome_funnel.py::test_historical_session_maps_dead_session_attachment_before_inactive_name tests/test_score_to_outcome_funnel.py::test_runtime_session_maps_dead_session_guidance_before_inactive_name tests/test_execution_quality.py::test_execution_quality_session_name_maps_dead_session_state -q`
- `./.venv/bin/python -m pytest -q tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py -q`
- `git diff --check`
- runtime 재시작 후 `/health/ready`: ready.
- runtime 상태:
  - `live_candidate_promotion_readiness --since-ws-start`: `WAIT/no_promotable_live_candidate`, `top_live_blockers={'no_fresh_live_candidate': 11}`.
  - `run_micro_live_no_order_watchdog`: `OK/no_recent_live_intents`, `submit_ready=0`, `blocked=0`, `submission_count=0`.
  - `/portfolio/budget`: `accepted=2`, `live=0`, `context=2`.
  - route rows: `DOGEUSDC/TIAUSDC session_name=dead_session`, reasons no false `session_not_live_route`.
  - `run_micro_live_no_order_watchdog`: `OK/no_recent_live_intents`, `submit_ready=0`, `blocked=0`, `submission_count=0`.

## 2026-05-15 Iteration #171
### 추가 개선: stage monitor/operator dashboard의 no-candidate 문구 정리
- 운영 stage monitor와 stage board에 `no accepted candidate is visible` 문구가 남아 있었다.
- actionable/live-candidate 맥락에서는 이 문구가 `portfolio accepted`와 `live-route candidate`를 섞어 읽히게 만들 수 있었다.
- 수정 후:
  - `no live-route candidate is visible ...`
  - `no live-route candidate is currently visible on the operator surface`
  - `portfolio accepted context candidate exists, but no entry timing review target is active yet`
- operator dashboard route context helper도 `accepted_count=0`일 때 `Portfolio accepted candidates align...`이라고 말할 수 있던 문구 버그를 고쳤다.
  - 이제 `No portfolio accepted context candidates are visible; wait for a live-route candidate.`로 표시한다.
- top opportunity empty 상태도 `portfolio accepted context 후보 없음`으로 표시한다.
- runtime mitigation wait status label도 `accepted candidate present...`에서 `portfolio accepted context candidate present...`로 바꿔, stage board label에서도 주문 후보처럼 읽히지 않게 했다.

### 검증
- `./.venv/bin/python -m py_compile app/services/execution_operator_ui.py app/services/portfolio_budget_report.py app/services/strategy_engine.py scripts/stage_monitor_tick.py scripts/ops_stage_board.py`
- `./.venv/bin/python -m pytest -q tests/test_execution_operator_dashboard.py tests/test_execution_operator_ui.py tests/test_portfolio_budget_report.py tests/test_api_smoke.py::test_health_and_bootstrap_flow -q`
- `./.venv/bin/python -m py_compile app/core/operator_surface_contracts.py scripts/stage_monitor_tick.py scripts/ops_stage_board.py`
- `./.venv/bin/python -m pytest -q tests/test_execution_operator_dashboard.py tests/test_api_smoke.py::test_health_and_bootstrap_flow -q`
- `./.venv/bin/python -m pytest -q tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py -q`
- `git diff --check`
- runtime 재시작 후 `/health/ready`: ready.
- operator UI HTML 확인:
  - `portfolio accepted context 후보가 없습니다.`
  - `Runtime / Portfolio Context`
  - `Portfolio Accepted (Context)`
  - `Representative Portfolio Accepted Candidate`
- runtime 상태:
  - `live_candidate_promotion_readiness --since-ws-start`: `WAIT/no_promotable_live_candidate`, `top_live_blockers={'no_fresh_live_candidate': 11}`.
  - `run_micro_live_no_order_watchdog`: `OK/no_recent_live_intents`, `submit_ready=0`, `blocked=0`, `submission_count=0`.
  - recent 6h SIR opportunity: `expected_order_count=0`.
  - `notify_entry_surface.py --dry-run`: `LIVE_ORDER_CANDIDATE=0`, `CONTEXT_REVIEW_SETUP=2`, `BLOCKED_SETUP=3`, `notified=false`, `reason=no_alertable_rows`.

## 2026-05-15 Iteration #172
### 추가 개선: live route truth 판정 로직 공통화
- `/portfolio/budget`, operator dashboard, `notify_entry_surface.py`가 live route contract/status 판정을 각각 구현하고 있었다.
- 이 중복은 나중에 한쪽만 수정되면 “리포트는 live-route, 알림은 context-only” 같은 drift를 만들 수 있다.
- `app/services/live_route_contract.py`를 추가해 아래 로직을 단일 truth source로 묶었다.
  - settings/readiness 기반 live route contract 생성.
  - candidate row의 symbol/family/entry_model/direction/session 판정.
  - `entry_surface_route`와 `live_routable` 부착.
  - portfolio accepted context/live-route summary 생성.

### 추가로 발견한 실제 모순
- route truth의 session 판정은 `session_guidance.state=dead_session`이어도 `current_session.name=inactive`를 먼저 읽을 수 있었다.
- execution approval에서는 이미 `inactive -> dead_session` 정규화가 적용됐지만, entry surface/portfolio route truth는 같은 정규화를 보장하지 않았다.
- 수정 후:
  - `session_guidance.state=dead_session` 또는 `dead_session=true`이면 route truth도 `session_name=dead_session`으로 판정한다.
  - live contract가 `dead_session`을 허용하면 `inactive` raw name 때문에 `session_not_live_route`가 붙지 않는다.
  - `ExecutionMode.MICRO_LIVE` enum 값도 helper에서 `.value`로 정규화한다.

### 검증
- 신규 테스트:
  - `test_dead_session_guidance_maps_inactive_current_session_to_live_route_bucket`
- `./.venv/bin/python -m py_compile app/services/live_route_contract.py app/services/portfolio_budget_report.py app/services/strategy_engine.py scripts/notify_entry_surface.py`
- `./.venv/bin/python -m pytest -q tests/test_entry_surface_scripts.py tests/test_execution_operator_dashboard.py tests/test_portfolio_budget_report.py tests/test_api_smoke.py::test_health_and_bootstrap_flow -q`
- `./.venv/bin/python -m pytest -q tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py -q`
- `git diff --check`
- runtime 재시작 후 `/health/ready`: ready.
- runtime route truth 비교:
  - `/portfolio/budget`: `accepted=2`, `live=0`, `context=2`, `approve=portfolio_context_only_no_live_route_candidate`.
  - `notify_entry_surface.py --dry-run`: `LIVE_ORDER_CANDIDATE=0`, `CONTEXT_REVIEW_SETUP=2`, `BLOCKED_SETUP=3`, `notified=false`, `reason=no_alertable_rows`.
  - 양쪽 route reasons가 동일하게 나왔다.
    - `TIAUSDC`: `session_name=dead_session`, reasons=`symbol_not_live_routable,strategy_family_not_live_route,entry_model_not_live_route`.
    - `DOGEUSDC`: `session_name=dead_session`, reasons=`symbol_not_live_routable,strategy_family_not_live_route,entry_model_not_live_route`.
  - 이전처럼 `session_not_live_route`가 false reason으로 붙지 않는다.
- runtime 상태:
  - `live_candidate_promotion_readiness --since-ws-start`: `WAIT/no_promotable_live_candidate`, `top_live_blockers={'no_fresh_live_candidate': 11}`.
  - recent 6h SIR opportunity: `expected_order_count=0`.

## 2026-05-15 Iteration #177
### 추가 개선: 후보 생성/백테스트/parity audit의 dead-session 및 baseline 기준 정렬
- 후보 생성기(`PlanGenerator`)가 `session_guidance.state=dead_session`을 감지해도 저장 validity에는 `session_guidance_session_name=inactive`를 남길 수 있었다.
- 이 값은 주문 제출 경로를 직접 막지는 않지만, fast-failure validity, portfolio/entry surface, live/replay 비교에서 같은 dead session을 `inactive`와 `dead_session`으로 갈라 보이게 만든다.
- 수정 후:
  - `PlanGenerator`는 공통 `live_route_contract.row_session_name()`으로 session bucket을 저장한다.
  - dead session 후보 metadata도 `session_guidance_session_name=dead_session`으로 저장된다.
  - fast-failure session name도 같은 bucket을 사용한다.
- historical walk-forward proof의 raw-candle fast-failure path도 같은 공통 helper를 쓰게 했다.
  - 현재 live contract가 `dead_session`을 허용할 때 백테스트 proof path가 `inactive`로 필터 탈락하는 일을 막는다.
- live/replay parity audit의 intent session parser도 공통 helper를 사용하게 했다.
  - `session_guidance.state=dead_session + current_session.name=inactive`이면 parity filter도 `dead_session`으로 본다.
- stage monitor runtime mitigation wait context도 비활성 세션을 `dead_session` bucket으로 표시한다.
  - `allowed_sessions=dead_session,london,new_york`인데 `current_session=inactive`라서 outside-session처럼 보이는 운영 오해를 줄였다.
- 추가로 발견한 baseline drift:
  - operator dashboard는 `session_impulse_retest + CONFIRM` active contract baseline에 `micro_main_usdt_proxy_backtest`를 쓰고 있었다.
  - 하지만 `run_live_replay_parity_audit.py`는 예전 historical walk-forward cache만 읽어, 현재 live contract baseline이 있는데도 `matched_replay_rows=0`, `INSUFFICIENT_BASELINE`으로 표시했다.
  - parity audit도 `usdt_proxy_rows_for_active_contract()`를 사용하게 해 dashboard와 같은 baseline truth를 보도록 맞췄다.

### 검증
- 신규/갱신 테스트:
  - `test_plan_generator_applies_dead_session_penalty`
  - `test_live_replay_parity_maps_dead_session_guidance_before_inactive_name`
  - `test_runtime_mitigation_session_context_maps_inactive_to_dead_session`
  - `test_historical_walk_forward_fast_failure_maps_dead_session_guidance`
  - `test_live_replay_parity_uses_usdt_proxy_baseline_for_session_impulse_retest`
- `./.venv/bin/python -m py_compile app/services/historical_walk_forward_proof.py app/services/plan_generator.py scripts/run_live_replay_parity_audit.py scripts/stage_monitor_tick.py`
- `./.venv/bin/pytest tests/test_plan_generator.py tests/test_plan_quality_gates.py tests/test_historical_walk_forward_proof.py tests/test_script_entrypoints.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `170 passed`
- 최종 회귀:
  - `./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `401 passed`
- `git diff --check`
- runtime 재시작 후 `/health/ready`: ready.

### runtime 상태
- `live_candidate_promotion_readiness --since-ws-start`:
  - `WAIT/no_promotable_live_candidate`
  - `top_live_blockers={'no_fresh_live_candidate': 11}`
  - live-routable scope 11개 모두 fresh evidence지만 fresh live candidate 없음.
- `run_micro_live_no_order_watchdog`:
  - `OK/no_recent_live_intents`
  - `intent_count=0`, `submit_ready=0`, `blocked=0`, `submission_count=0`
  - 현재 차단 사유 없음, fresh live 후보 대기 상태.
- `/portfolio/budget`:
  - `accepted=2`, `live=0`, `context=2`
  - context symbols: `DOGEUSDC`, `TIAUSDC`
  - route reasons: `symbol_not_live_routable`, `strategy_family_not_live_route`, `entry_model_not_live_route`
  - session bucket: `dead_session`, false `session_not_live_route` 없음.
- `notify_entry_surface.py --dry-run`:
  - `LIVE_ORDER_CANDIDATE=0`, `CONTEXT_REVIEW_SETUP=2`, `BLOCKED_SETUP=3`
  - `notified=false`, `reason=no_alertable_rows`
- `run_session_impulse_retest_opportunity_report --lookback-hours 6`:
  - `expected_order_count=0`
- `run_live_replay_parity_audit --all-live-symbols --days 3`:
  - baseline source: `micro_main_usdt_proxy_backtest`
  - portfolio aggregate: `expected_per_week=28.1213`, `observed_per_week=23.3333`, `ratio=0.8297`
  - stage counts: `flow_within_baseline=4`, `approval_gate_blocked=4`, `signal_or_plan_generation_gap=3`
  - 더 이상 `portfolio_replay_flow_baseline_unavailable`가 아니다.

## 2026-05-15 Iteration #178
### 추가 개선: live/replay parity ALERT 기준을 짧은 심볼별 창과 주문 경로 장애로 분리
- Iteration #177 이후 parity audit는 현재 SIR/CONFIRM baseline을 정상적으로 읽게 됐다.
- 그러나 `--all-live-symbols --days 3`에서 포트폴리오 aggregate는 `ratio=0.8297`로 충분한데도, 일부 심볼의 3일 expected count가 2건 미만인 상태에서 관측 0건이면 전체를 `ALERT`로 올렸다.
- 예:
  - `BCHUSDC expected_per_week≈1.3`이면 3일 기대 건수는 약 `0.56`건이다.
  - 이런 창에서 0건은 즉시 장애라기보다 표본이 얇은 관찰 상태다.
- 수정 후:
  - per-symbol expected window candidates가 2건 미만이면 flow shortfall은 `WATCH`로 둔다.
  - `submit_ready`가 있는데 submission이 없거나, exchange reject/error가 있으면 여전히 `ALERT`다.
  - `LiveOrderLifecycleReporter.generate()`에는 active contract의 `strategy_families`를 넘겨, parity block reason이 다른 전략 family의 과거 live intent와 섞이지 않게 했다.
- README와 operating runbook에도 `ALERT`/`WATCH` 의미를 갱신했다.

### 검증
- 신규 테스트:
  - `test_live_replay_parity_marks_thin_symbol_window_as_watch`
  - `test_live_replay_parity_lifecycle_uses_active_contract_family_filter`
- targeted:
  - `./.venv/bin/python -m py_compile scripts/run_live_replay_parity_audit.py`
  - `./.venv/bin/pytest tests/test_micro_live_operational_guards.py::test_live_replay_parity_flags_flow_below_replay_baseline tests/test_micro_live_operational_guards.py::test_live_replay_parity_classifies_approval_gate_blocked_flow tests/test_micro_live_operational_guards.py::test_live_replay_parity_marks_thin_symbol_window_as_watch tests/test_micro_live_operational_guards.py::test_live_replay_parity_lifecycle_uses_active_contract_family_filter tests/test_micro_live_operational_guards.py::test_live_replay_parity_portfolio_aggregates_live_symbols -q`
- broad:
  - `./.venv/bin/pytest tests/test_micro_live_operational_guards.py tests/test_execution_operator_dashboard.py tests/test_script_entrypoints.py tests/test_stage_monitor_tick.py -q`
  - `136 passed`
- runtime parity after change:
  - overall_status: `WATCH`
  - reason: `portfolio_symbol_order_flow_blocked_or_waiting`
  - expected/week: `28.1213`
  - observed/week: `23.3333`
  - ratio: `0.8297`
  - alert_symbol_count: `0`
  - watch_symbol_count: `7`
  - stage counts: `signal_or_plan_generation_gap=6`, `flow_within_baseline=4`, `approval_gate_blocked=1`
  - 해석: 포트폴리오 전체 flow collapse가 아니라, 짧은 심볼별 창과 일부 승인 게이트 관찰 상태다.

## 2026-05-15 Iteration #179
### 추가 개선: portfolio parity WATCH reason을 실제 병목 유형별로 분리
- Iteration #178에서 per-symbol `ALERT`/`WATCH`는 정리됐지만, portfolio aggregate의 `WATCH` reason은 여전히 `portfolio_symbol_order_flow_blocked_or_waiting` 한 가지로 고정돼 있었다.
- 현재 실제 stage 분포는 `signal_or_plan_generation_gap=6`, `approval_gate_blocked=1`인데 headline이 order flow 문제처럼 읽힐 수 있었다.
- 수정:
  - thin/signal flow watch: `portfolio_symbol_live_flow_watch_thin_window`
  - order gate watch: `portfolio_symbol_order_flow_blocked_or_waiting`
  - 둘이 섞인 경우: `portfolio_symbol_live_flow_and_order_gate_watch`
  - evaluation에 `flow_shortfall_watch_count`, `order_gate_watch_count`를 추가했다.
- README와 operating runbook에 portfolio `WATCH` reason 해석을 문서화했다.

### 검증
- targeted:
  - `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/run_live_replay_parity_audit.py`
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py::test_live_replay_parity_portfolio_labels_thin_window_watch_reason tests/test_micro_live_operational_guards.py::test_live_replay_parity_portfolio_labels_mixed_watch_reason tests/test_micro_live_operational_guards.py::test_live_replay_parity_portfolio_aggregates_live_symbols -q`
  - `3 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py tests/test_script_entrypoints.py -q`
  - `79 passed`
- runtime parity after change:
  - overall_status: `WATCH`
  - reason: `portfolio_symbol_live_flow_and_order_gate_watch`
  - expected/week: `28.1213`
  - observed/week: `23.3333`
  - ratio: `0.8297`
  - alert_symbol_count: `0`
  - watch_symbol_count: `7`
  - flow_shortfall_watch_count: `6`
  - order_gate_watch_count: `1`
  - stage counts: `signal_or_plan_generation_gap=6`, `flow_within_baseline=4`, `approval_gate_blocked=1`

## 2026-05-15 Iteration #180
### 추가 개선: portfolio parity markdown report 상단 요약을 포트폴리오용으로 분리
- `run_live_replay_parity_audit.py --all-live-symbols`는 JSON에는 portfolio aggregate 정보를 담고 있었지만, markdown report 상단은 단일 심볼용 필드(`dashboard_source`, `order_flow_status`)를 그대로 보여줄 수 있었다.
- 사람이 최신 report를 먼저 볼 때 null/빈 단일심볼 필드가 현재 병목처럼 보일 수 있어, portfolio mode에서는 다음 필드를 상단에 노출하도록 분리했다.
  - `symbol_count`
  - `alert_symbol_count`
  - `watch_symbol_count`
  - `flow_shortfall_watch_count`
  - `order_gate_watch_count`
  - `flow_stage_counts`
  - `flow_primary_reason_counts`

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/run_live_replay_parity_audit.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py::test_live_replay_parity_portfolio_report_uses_portfolio_summary tests/test_micro_live_operational_guards.py::test_live_replay_parity_portfolio_labels_thin_window_watch_reason tests/test_micro_live_operational_guards.py::test_live_replay_parity_portfolio_labels_mixed_watch_reason -q`
- 결과: `3 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `406 passed`
- `git diff --check`

## 2026-05-15 Iteration #181
### 추가 개선: live/replay parity report에도 latest alias를 추가
- 대부분의 운영 리포트는 timestamp 파일과 함께 `latest.md/latest.json`을 atomic write로 남기는데, `run_live_replay_parity_audit.py`는 timestamp 파일만 남기고 있었다.
- 이 때문에 운영자가 고정 경로에서 최신 parity truth를 보려는 흐름과 어긋날 수 있었다.
- 수정:
  - `run_live_replay_parity_audit.py`가 timestamp report 작성 후 `latest.md/latest.json`도 쓴다.
  - stdout payload에 `latest_report_path`, `latest_json_path`를 포함한다.
  - README와 operating runbook에 parity latest alias를 문서화했다.

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/run_live_replay_parity_audit.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py::test_live_replay_parity_main_writes_latest_aliases tests/test_micro_live_operational_guards.py::test_live_replay_parity_portfolio_report_uses_portfolio_summary -q`
- 결과: `2 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py tests/test_script_entrypoints.py -q`
  - `81 passed`
- runtime write check:
  - `scripts/run_live_replay_parity_audit.py --all-live-symbols --days 3 --no-fail-exit`
  - `reports/operations/live_replay_parity/latest.md`와 `latest.json` 생성 확인
  - latest status: `WATCH`
  - latest reason: `portfolio_symbol_live_flow_and_order_gate_watch`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `407 passed`
- `git diff --check`

## 2026-05-15 Iteration #182
### 추가 개선: live/replay parity를 launchd와 ops heartbeat 감시 대상에 포함
- `run_live_replay_parity_audit.py`가 latest alias를 쓰게 됐지만, launchd 생성 목록과 `run_micro_live_ops_heartbeat.py` 기본 감시 대상에는 아직 포함되지 않았다.
- 이 상태에서는 replay 대비 live flow 괴리가 생겨도 운영 heartbeat 요약에 자동으로 드러나지 않는다.
- 수정:
  - `install_micro_live_ops_launchd.py`에 `live_replay_parity` job을 추가했다.
  - 실행 주기: 60분
  - 명령: `run_live_replay_parity_audit.py --all-live-symbols --days 3 --no-fail-exit`
  - `run_micro_live_ops_heartbeat.py` 기본 jobs에 `live_replay_parity`를 추가했다.
  - `PASS`는 통과, `WATCH`는 운영 주의로 노출, `ALERT/INSUFFICIENT_BASELINE` 등은 hard failure로 드러난다.
  - README, operating runbook, hardening plan에 감시 대상 추가를 문서화했다.

### 운영 리포트 갱신 결과
- 변경 직후 실제 heartbeat를 돌리니 여러 리포트가 2026-05-13 이후 stale 상태라 `FAIL`이었다.
- 최신 리포트들을 수동 갱신했다.
  - `run_micro_live_runtime_guard.py`: `PASS`
  - `run_micro_live_no_order_watchdog.py`: `OK/no_recent_live_intents`
  - `run_live_reconciliation_watchdog.py`: `OK/no_reconciliation_gap_detected`
  - `run_micro_live_synthetic_canary.py --no-network`: `PASS`, `no_live_order_sent=true`
  - `run_binance_rule_drift_snapshot.py`: `PASS`, `drift_count=0`
  - `run_replay_validation_bridge.py --all-live-symbols`: `PASS`
  - `run_session_impulse_retest_runtime_audit_report.py --hours 3`: `PASS`
  - `build_micro_live_event_blackouts.py`: `PASS_WITH_WARNINGS` because BLS endpoints returned 403, but fallback preserved future windows and heartbeat horizon check passes.
  - `run_micro_live_failure_drill.py`: `PASS`, `8/8`
  - `run_micro_live_boot_check.py`: `PASS`
- 최종 `run_micro_live_ops_heartbeat.py --no-fail-exit`:
  - overall_status: `WATCH`
  - hard_failure_count: `0`
  - warning_count: `1`
  - only warning: `live_replay_parity=WATCH`
  - 해석: 운영 리포트 stale 문제는 해소됐고, 남은 WATCH는 replay 대비 live flow 관찰 상태다.
- `install_micro_live_ops_launchd.py --output-dir reports/operations/launchd --python ./.venv/bin/python`:
  - overall_status: `PASS`
  - job_count: `12`
  - `live_replay_parity` plist 생성 확인

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/install_micro_live_ops_launchd.py scripts/run_micro_live_ops_heartbeat.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py::test_launchd_generator_includes_remaining_operational_guards tests/test_micro_live_operational_guards.py::test_ops_heartbeat_defaults_include_live_replay_parity tests/test_micro_live_operational_guards.py::test_ops_heartbeat_warns_on_live_replay_parity_watch tests/test_micro_live_operational_guards.py::test_ops_heartbeat_main_writes_latest_aliases -q`
- 결과: `4 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `409 passed`
- `git diff --check`

## 2026-05-15 Iteration #186
### 추가 개선: Discord 운영 알림이 WATCH 원인을 잘라먹지 않도록 보강
- Iteration #185에서 heartbeat row에는 `status_detail`이 들어가지만, Discord 운영 formatter는 기본적으로 메시지 앞 두 줄만 노출했다.
- 그래서 실제 알림은 `MICRO_LIVE 운영 점검 / 상태: WATCH`까지만 보이고, 핵심 원인인 `주의: live_replay_parity=... portfolio_symbol_live_flow_and_order_gate_watch`가 잘릴 수 있었다.
- 수정:
  - `NotificationDispatcher._format_discord_operational()`이 운영 메시지에서 `상태:`, `긴급:`, `주의:` 라인을 우선 노출한다.
  - `긴급: 없음`처럼 내용 없는 라인은 숨긴다.
  - entry surface의 기존 `live_order_candidates=` 기반 제목 분류는 유지한다.
- 기대 알림 형태:
  - `[운영] MICRO_LIVE 확인 필요`
  - `요약: MICRO_LIVE 운영 점검`
  - `추가: 상태: WATCH / fail=0 watch=1`
  - `상세: 주의: live_replay_parity=WATCH/WATCH content_status_watch portfolio_symbol_live_flow_and_order_gate_watch`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `NotificationDispatcher`와 `run_micro_live_ops_heartbeat.py`가 workspace와 동일한지 diff로 확인했다.
  - runtime_src 기준 Discord message preview도 `상세: 주의: live_replay_parity=WATCH/WATCH ... portfolio_symbol_live_flow_and_order_gate_watch`를 포함한다.

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile app/services/notification_dispatcher.py scripts/run_micro_live_ops_heartbeat.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_notification_dispatcher.py::test_dispatcher_entry_surface_context_only_title_is_monitoring tests/test_notification_dispatcher.py::test_dispatcher_entry_surface_live_candidate_title_requires_attention tests/test_notification_dispatcher.py::test_dispatcher_entry_surface_alert_without_entry_counts_uses_operational_title tests/test_notification_dispatcher.py::test_dispatcher_operational_heartbeat_includes_watch_detail tests/test_micro_live_operational_guards.py::test_ops_heartbeat_warns_on_live_replay_parity_watch -q`
- 결과: `5 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_notification_dispatcher.py tests/test_micro_live_operational_guards.py tests/test_script_entrypoints.py -q`
  - `100 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `410 passed`
- `git diff --check`

## 2026-05-15 Iteration #187
### 추가 개선: hard failure 없는 WATCH heartbeat는 “확인 필요”가 아니라 “운영 관찰”로 표시
- Iteration #185/#186으로 WATCH 원인은 보이게 됐지만, `fail=0`인 watch-only heartbeat도 제목이 `[운영] MICRO_LIVE 확인 필요`라서 실제보다 급해 보일 수 있었다.
- 수정:
  - `run_micro_live_ops_heartbeat._message()`가 hard failure 없이 warning만 있으면 다음 조치를 `WATCH는 자동 관찰; 반복/악화 시 해당 리포트 확인`으로 낮춘다.
  - `NotificationDispatcher._format_discord_operational()`이 `MICRO_LIVE 운영 점검` + `상태: WATCH / fail=0 ...` 메시지는 `[모니터링] MICRO_LIVE 운영 관찰` 제목으로 표시한다.
  - `상태`, `주의`, `다음` 라인을 함께 노출해 원인과 조치가 알림 안에서 바로 보인다.
- 현재 workspace 기준 preview:
  - `[모니터링] MICRO_LIVE 운영 관찰`
  - `추가: 상태: WATCH / fail=0 watch=1`
  - `상세: 주의: live_replay_parity=WATCH/WATCH content_status_watch portfolio_symbol_live_flow_and_order_gate_watch`
  - `조치: 다음: WATCH는 자동 관찰; 반복/악화 시 해당 리포트 확인`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `NotificationDispatcher`와 `run_micro_live_ops_heartbeat.py`가 workspace와 동일한지 diff로 확인했다.
  - runtime_src 기준 preview도 `[모니터링] MICRO_LIVE 운영 관찰`과 `WATCH는 자동 관찰; 반복/악화 시 해당 리포트 확인`을 표시한다.
  - runtime_src no-order watchdog는 계속 `OK/no_recent_live_intents`, `intent_count=0`, `submit_ready=0`, `blocked=0`, `submission_count=0`이다.

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile app/services/notification_dispatcher.py scripts/run_micro_live_ops_heartbeat.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_notification_dispatcher.py::test_dispatcher_operational_heartbeat_includes_watch_detail tests/test_micro_live_operational_guards.py::test_ops_heartbeat_message_watch_only_is_monitoring_action tests/test_micro_live_operational_guards.py::test_ops_heartbeat_message_separates_failures_and_warnings -q`
- 결과: `3 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_notification_dispatcher.py tests/test_micro_live_operational_guards.py tests/test_script_entrypoints.py -q`
  - `101 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `411 passed`
- `git diff --check`

## 2026-05-15 Iteration #188
### 추가 개선: no-order watchdog의 runtime scope와 3일 lookback context 분리
- `run_micro_live_no_order_watchdog.py`는 active alert 판단을 WS worker `runtime_started_at` 이후로 제한한다.
- 이 자체는 맞다. 재시작 전 오래된 blocked intent를 새 runtime 장애처럼 띄우면 오탐이 된다.
- 다만 출력에는 `window_days=3`만 보여서 재시작 직후 `최근 3일 전체에 아무 intent도 없었다`처럼 오해될 수 있었다.
- 수정:
  - active evaluation은 기존처럼 `runtime_since_ws_start` scope를 사용한다.
  - full `--days` context는 별도 `lookback_lifecycle_summary`로 항상 같이 계산한다.
  - payload에 `watchdog_scope`, `watchdog_scope_label`, `lookback_window_start`, `runtime_lifecycle_summary`, `lookback_lifecycle_summary`를 추가했다.
  - 알림 메시지는 runtime scope일 때 `런타임 재시작 이후: ...`와 `참고: 최근 N일 전체 ...`를 분리한다.
- 현재 workspace 기준 확인:
  - active scope: `runtime_since_ws_start`
  - runtime 이후: intent `0`, submission `0`, alert `false`
  - 최근 3일 lookback: intent `10`, submission `0`
  - lookback top reasons: `session_impulse_retest_rollout_not_ready=8`, `rollout_session_not_allowed=2`
  - 해석: 지금 runtime 주문 경로가 막힌 게 아니라, 최근 3일 후보는 live submit 대상이 아니라 shadow/rollout-not-ready 또는 session-not-allowed로 분류됐다.
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `run_micro_live_no_order_watchdog.py`가 workspace와 동일한지 diff로 확인했다.
  - runtime_src 기준 결과도 `status=OK`, `reason=no_recent_live_intents`, `scope=runtime_since_ws_start`, runtime intents `0`, lookback intents `10`, lookback submissions `0`, lookback reasons `session_impulse_retest_rollout_not_ready=8`, `rollout_session_not_allowed=2`다.
  - runtime_src 기준 `run_micro_live_no_order_watchdog.py --no-fail-exit`로 latest report를 새 구조로 갱신했다.
  - runtime_src ops heartbeat에서 no-order row는 `PASS/OK/no_recent_live_intents`이고, 남은 warning은 `live_replay_parity=WATCH` 1개다.

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/run_micro_live_no_order_watchdog.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py::test_no_order_watchdog_notification_message_is_concise tests/test_micro_live_operational_guards.py::test_no_order_watchdog_message_separates_runtime_scope_from_lookback_context tests/test_micro_live_operational_guards.py::test_no_order_watchdog_no_recent_intents_message_waits_for_candidate -q`
- 결과: `3 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py tests/test_script_entrypoints.py tests/test_notification_dispatcher.py -q`
  - `102 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `412 passed`
- `git diff --check`

## 2026-05-15 Iteration #189
### 추가 개선: live candidate promotion readiness도 runtime scope와 lookback context 분리
- no-order watchdog는 runtime 이후와 3일 lookback을 분리했지만, `run_live_candidate_promotion_readiness.py` 기본 실행은 여전히 최근 24시간 전체 intent를 headline으로 읽을 수 있었다.
- 이 때문에 재시작 전 오래된 `session_impulse_retest_rollout_not_ready` intent가 현재 headline을 `BLOCKED`로 만들고, 실제 현재 runtime audit의 `no_live_route_candidate_plan` / `ws_stream_active_route_suppressed`와 충돌해 보였다.
- 확인:
  - 설정상 `session_impulse_retest_shadow_only=false`, `core_live_slots=11`, `BTCUSDC` rollout priority `1`이라 현재 BTC가 readiness 자체로 hard-block될 이유는 없다.
  - `evaluate_micro_main_live_readiness(... shadow_summary=None)`도 `blockers=[]`, `advisory_blockers=['shadow_not_available', 'no_recent_closed_sample']`, `status=live_bootstrap_collecting`로 나온다.
  - 실제 runtime audit 최신 BTC row는 `no_live_route_candidate_plan` / `ws_stream_active_route_suppressed`이며, `rollout_not_ready`가 아니다.
- 수정:
  - `run_live_candidate_promotion_readiness.py`는 WS heartbeat `started_at`이 있으면 기본 active window를 `runtime_since_ws_start`로 둔다.
  - 재시작 전 `--hours` window의 blocker는 `lookback_readiness_summary`와 compact 출력의 `lookback_context`로만 표시한다.
  - 과거 전체 window를 headline으로 보고 싶을 때는 `--lookback-only`를 명시한다.
  - `--since-ws-start`는 호환용 플래그로 유지한다.
- 현재 workspace 기준 compact 결과:
  - `readiness_scope=runtime_since_ws_start`
  - `state=WAIT reason=no_promotable_live_candidate`
  - live state counts: `NO_FRESH_LIVE_CANDIDATE=11`
  - `top_intent_reasons={}`
  - `lookback_context=state=BLOCKED reason=session_impulse_retest_rollout_not_ready ...`
  - 해석: 현재 주문 truth는 fresh live candidate 대기이고, 과거 rollout_not_ready는 lookback 설명이다.
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `run_live_candidate_promotion_readiness.py`가 workspace와 동일한지 diff로 확인했다.
  - runtime_src 기본 compact도 `readiness_scope=runtime_since_ws_start`, `state=WAIT`, `reason=no_promotable_live_candidate`, `top_intent_reasons={}`로 나온다.
  - runtime_src no-order watchdog도 `status=OK`, `reason=no_recent_live_intents`, `scope=runtime_since_ws_start`, runtime intents `0`, lookback intents `10`이다.
  - runtime_src `run_live_candidate_promotion_readiness.py --compact`로 latest report를 새 scope 구조로 갱신했다.

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/run_live_candidate_promotion_readiness.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_live_candidate_promotion_readiness.py::test_readiness_script_runtime_scope_keeps_lookback_context tests/test_live_candidate_promotion_readiness.py::test_runtime_readiness_wait_headline_uses_live_symbols_only -q`
- 결과: `2 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_live_candidate_promotion_readiness.py tests/test_script_entrypoints.py tests/test_execution_operator_dashboard.py -q`
  - `37 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `413 passed`
- `git diff --check`
- `/health/ready`: ready

## 2026-05-15 Iteration #185
### 추가 개선: ops heartbeat WATCH 메시지에 원인 detail 승격
- `run_micro_live_ops_heartbeat.py`는 각 리포트의 `WATCH` 상태는 잘 감지했지만, 하위 리포트의 `evaluation.reason`을 heartbeat 요약으로 끌어올리지 않았다.
- 이 때문에 `live_replay_parity=WATCH`가 떠도 실제 원인인 `portfolio_symbol_live_flow_and_order_gate_watch`가 Discord/heartbeat summary에서 바로 보이지 않을 수 있었다.
- 수정:
  - markdown/json 리포트 payload에서 `evaluation.reason`, `status_detail`, `message`를 `report_reason`으로 추출한다.
  - heartbeat row의 `status_detail`은 기존 macro blackout 자체 진단을 우선하고, 없으면 `report_reason`을 사용한다.
  - dedupe key와 `_message()`는 기존처럼 `status_detail`을 포함하므로, 같은 WATCH라도 원인이 바뀌면 알림도 별도 이슈로 취급된다.
- 현재 workspace 기준 heartbeat 확인:
  - overall_status: `WATCH`
  - hard_failure_count: `0`
  - warning_count: `1`
  - warning detail: `live_replay_parity=WATCH/WATCH content_status_watch portfolio_symbol_live_flow_and_order_gate_watch`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `run_micro_live_ops_heartbeat.py`가 workspace와 동일한지 diff로 확인했다.
  - runtime_src 기준 heartbeat도 `status_detail=portfolio_symbol_live_flow_and_order_gate_watch`를 포함한다.

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/run_micro_live_ops_heartbeat.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py::test_ops_heartbeat_warns_on_live_replay_parity_watch tests/test_micro_live_operational_guards.py::test_ops_heartbeat_message_separates_failures_and_warnings -q`
- 결과: `2 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py tests/test_script_entrypoints.py -q`
  - `83 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `409 passed`
- `git diff --check`

## 2026-05-15 Iteration #183
### 운영 반영: workspace 변경을 실제 runtime_src와 launchd에 배포
- 실제 설치된 launchd plist는 workspace가 아니라 `/Users/yumin/Library/Application Support/trading/runtime_src`를 실행한다.
- 따라서 workspace 코드만 고치면 주기 실행되는 운영 job에는 반영되지 않을 수 있었다.
- 확인:
  - 기존 LaunchAgents에는 `com.trading.micro-live.live-replay-parity.plist`가 없었다.
  - 기존 launchd jobs는 `/Users/yumin/Library/Application Support/trading/runtime_src`와 `runtime_venv`를 사용하고 있었다.
- 조치:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`로 workspace의 `app/`, `scripts/`, `.env`를 runtime_src에 강제 반영하고 API/worker를 재시작했다.
  - `/health/ready`: ready
  - runtime_src의 `run_micro_live_ops_heartbeat.py`, `install_micro_live_ops_launchd.py`, `run_live_replay_parity_audit.py`가 workspace와 동일한지 diff로 확인했다.
  - runtime_src 기준으로 `install_micro_live_ops_launchd.py --install`을 실행해 12개 plist를 설치했다.
  - `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.trading.micro-live.live-replay-parity.plist`로 새 parity job을 로드했다.
- 확인:
  - `launchctl print gui/$(id -u)`에 `com.trading.micro-live.live-replay-parity`가 표시됨.
  - plist args:
    - `runtime_venv/bin/python`
    - `runtime_src/scripts/run_live_replay_parity_audit.py`
    - `--all-live-symbols --days 3 --no-fail-exit`
  - `RunAtLoad=true`, `StartInterval=3600`, `WorkingDirectory=runtime_src`
- runtime_src 기준 최종 상태:
  - ops heartbeat: `WATCH`
  - hard_failure_count: `0`
  - warning_count: `1`
  - only warning: `live_replay_parity=WATCH`
  - no-order watchdog: `OK/no_recent_live_intents`, `intent_count=0`, `submit_ready=0`, `blocked=0`, `submission_count=0`
  - live/replay parity: `WATCH`, reason `portfolio_symbol_live_flow_and_order_gate_watch`, ratio `0.8297`, alert symbols `0`, watch symbols `7`

## 2026-05-15 Iteration #184
### 추가 개선: runtime 로그 무한 증가 방지
- 실제 durable runtime 로그를 확인하니 `~/Library/Application Support/trading/logs/trading_worker_loop.log`가 `652MB`까지 커져 있었다.
- 주문 경로 문제는 아니지만 장기 운영에서 디스크 사용량과 파일 I/O 부담으로 이어질 수 있다.
- 수정:
  - `restart_runtime_stack_tmp.sh`와 legacy `restart_runtime_stack.sh`에 로그 회전을 추가했다.
  - 대상: `trading_api.log`, `trading_worker_loop.log`, `trading_worker_ws.log`
  - 기본 임계값: `TRADING_LOG_ROTATE_MAX_BYTES=104857600`
  - 기본 보관 개수: `TRADING_LOG_ROTATE_KEEP=5`
  - 프로세스를 내린 뒤 새 프로세스를 띄우기 전에 큰 로그만 `*.log.1` 형식으로 회전한다.
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - 실제 결과:
    - `trading_worker_loop.log`: `114KB`
    - `trading_worker_loop.log.1`: `652MB`
  - runtime_src의 restart scripts가 workspace와 동일한지 diff로 확인했다.
- runtime_src 기준 ops heartbeat:
  - overall_status: `WATCH`
  - hard_failure_count: `0`
  - warning_count: `1`
  - only warning: `live_replay_parity=WATCH`

### 검증
- `bash -n scripts/restart_runtime_stack_tmp.sh scripts/restart_runtime_stack.sh`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py::test_launchd_generator_includes_remaining_operational_guards tests/test_micro_live_operational_guards.py::test_ops_heartbeat_defaults_include_live_replay_parity tests/test_micro_live_operational_guards.py::test_ops_heartbeat_warns_on_live_replay_parity_watch -q`
- 결과: `3 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `409 passed`
- `git diff --check`
- `/health/ready`: ready

## 2026-05-15 Iteration #190
### 추가 개선: live/replay parity도 runtime scope와 lookback context 분리
- no-order watchdog와 promotion readiness는 재시작 이후 runtime scope를 active truth로 보지만, `run_live_replay_parity_audit.py --all-live-symbols --days 3`는 여전히 최근 3일 전체를 headline으로 읽었다.
- 이 때문에 현재 런타임에는 fresh live intent가 0건인데도, 재시작 전 3일 lookback의 `session_impulse_retest_rollout_not_ready` / `rollout_session_not_allowed` 이력이 `live_replay_parity=WATCH`로 남아 현재 주문 경로 문제처럼 보일 수 있었다.
- 수정:
  - WS worker heartbeat `started_at`이 있으면 parity active window도 기본 `runtime_since_ws_start`로 둔다.
  - 전체 `--days` 결과는 `lookback_evaluation_summary`에 별도 보존한다.
  - `--lookback-only`를 추가해 과거 window를 의도적으로 headline으로 볼 수 있게 했다.
  - 런타임 이후 replay 기대 후보가 2건 미만이고 live intent/submission/reject가 없으면 `runtime_window_below_live_replay_parity_evidence_floor`로 `PASS` 처리한다.
  - 현재 runtime에서 실제 blocked intent, submit-ready gap, reject/error가 발생하면 기존처럼 `WATCH/ALERT`로 유지한다.
- 현재 workspace 기준 확인:
  - active parity: `PASS`
  - reason: `portfolio_runtime_window_below_live_replay_parity_evidence_floor`
  - scope: `runtime_since_ws_start`
  - expected_window_candidates: `0.0172`
  - lookback context: `WATCH`, reason `portfolio_symbol_live_flow_and_order_gate_watch`, top reasons `session_impulse_retest_rollout_not_ready=8`, `rollout_session_not_allowed=2`
- 해석: 지금 상태는 “주문 경로 장애”가 아니라 “재시작 이후 아직 parity 판단에 충분한 후보 기대치가 쌓이지 않은 fresh 후보 대기”다. 재시작 전 3일의 차단 이력은 사라진 게 아니라 lookback context에 남는다.
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `run_live_replay_parity_audit.py`, `run_micro_live_ops_heartbeat.py`, `NotificationDispatcher`가 workspace와 동일한지 diff로 확인했다.
  - runtime_src parity latest: `PASS`, reason `portfolio_runtime_window_below_live_replay_parity_evidence_floor`, scope `runtime_since_ws_start`, lookback reason `portfolio_symbol_live_flow_and_order_gate_watch`
  - runtime_src ops heartbeat: `PASS`, hard `0`, watch `0`

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/run_live_replay_parity_audit.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py::test_live_replay_parity_runtime_short_window_without_flow_is_pass tests/test_micro_live_operational_guards.py::test_live_replay_parity_portfolio_runtime_scope_keeps_lookback_context tests/test_micro_live_operational_guards.py::test_live_replay_parity_portfolio_labels_mixed_watch_reason -q`
- 결과: `3 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py tests/test_script_entrypoints.py tests/test_live_candidate_promotion_readiness.py -q`
  - `100 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `415 passed`
- `git diff --check`
- `/health/ready`: ready

## 2026-05-15 Iteration #191
### 추가 개선: readiness blocker 표시를 headline/live 기준으로 명확화
- 현재 runtime readiness는 `WAIT/no_promotable_live_candidate`이고 live 대상 11개는 모두 `NO_FRESH_LIVE_CANDIDATE`다.
- 보조 관측 심볼 3개는 `SHADOW_SIGNAL_ONLY`라서 `symbol_not_live_enabled_for_auto_route`가 나오지만, 이것은 live 주문 차단이 아니라 auxiliary shadow queue다.
- 이미 JSON에는 `top_live_blockers`와 `top_auxiliary_blockers`가 있었지만 compact/report가 `top_blockers`를 먼저 보여줘 auxiliary blocker가 현재 live 차단처럼 보일 수 있었다.
- 수정:
  - readiness payload에 `headline_top_blockers`와 `top_all_blockers`를 추가했다.
  - compact/report는 `top_blockers` 대신 `headline_top_blockers`와 `top_all_blockers`를 표시한다.
  - JSON의 기존 `top_blockers`는 호환성 때문에 유지한다.
- 현재 workspace compact 확인:
  - `headline_top_blockers={'no_fresh_live_candidate': 11}`
  - `top_all_blockers={'no_fresh_live_candidate': 11, 'symbol_not_live_enabled_for_auto_route': 3}`
  - `top_auxiliary_blockers={'symbol_not_live_enabled_for_auto_route': 3}`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 readiness runtime service, readiness script, parity script가 workspace와 동일한지 diff로 확인했다.
  - runtime_src compact도 `headline_top_blockers={'no_fresh_live_candidate': 11}`와 `top_all_blockers=...symbol_not_live_enabled_for_auto_route...`를 분리한다.
  - runtime_src no-order watchdog: `OK/no_recent_live_intents`, scope `runtime_since_ws_start`, runtime intents `0`
  - runtime_src live/replay parity: `PASS`, reason `portfolio_runtime_window_below_live_replay_parity_evidence_floor`
  - runtime_src ops heartbeat: `PASS`, hard `0`, watch `0`
  - runtime_src entry surface dry-run: `notified=false`, reason `no_alertable_rows`, counts `LIVE_ORDER_CANDIDATE=0`, `CONTEXT_REVIEW_SETUP=2`, `BLOCKED_SETUP=3`
  - runtime_src recent 6h opportunity: `expected_order_count=0`, potential performance `0R`

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile app/services/live_candidate_promotion_readiness_runtime.py scripts/run_live_candidate_promotion_readiness.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_live_candidate_promotion_readiness.py -q`
- 결과: `13 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_live_candidate_promotion_readiness.py tests/test_script_entrypoints.py tests/test_execution_operator_dashboard.py -q`
  - `37 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `415 passed`
- `git diff --check`

## 2026-05-15 Iteration #192
### 추가 개선: entry surface dry-run 결과에 top-level count 노출
- `notify_entry_surface.py --dry-run`은 `snapshot.counts` 안에는 `LIVE_ORDER_CANDIDATE`, `CONTEXT_REVIEW_SETUP`, `BLOCKED_SETUP` 수를 담았지만, top-level에는 counts가 없었다.
- 사람이 직접 보거나 작은 점검 스크립트에서 파싱할 때 `notified=false/no_alertable_rows`만 보고 실제 후보 수를 다시 nested snapshot에서 찾아야 했다.
- 수정:
  - 결과 JSON top-level에 `entry_counts`, `live_order_candidates`, `context_review_setups`, `blocked_setups`, `research_only_setups`를 추가했다.
  - 기존 `snapshot.counts`와 alert state는 그대로 유지한다.
- 현재 workspace dry-run:
  - `notified=false`
  - `reason=no_alertable_rows`
  - `live_order_candidates=0`
  - `context_review_setups=2`
  - `blocked_setups=3`
  - `research_only_setups=0`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `notify_entry_surface.py`와 readiness runtime service가 workspace와 동일한지 diff로 확인했다.
  - runtime_src entry surface dry-run도 top-level counts를 표시한다: `LIVE_ORDER_CANDIDATE=0`, `CONTEXT_REVIEW_SETUP=2`, `BLOCKED_SETUP=3`, `RESEARCH_ONLY_SETUP=0`
  - runtime_src readiness: `WAIT/no_promotable_live_candidate`, `headline_top_blockers={'no_fresh_live_candidate': 11}`
  - runtime_src no-order watchdog: `OK/no_recent_live_intents`, runtime intents `0`
  - runtime_src live/replay parity: `PASS`, reason `portfolio_runtime_window_below_live_replay_parity_evidence_floor`
  - runtime_src ops heartbeat: `PASS`, hard `0`, watch `0`

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/notify_entry_surface.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py::test_main_dry_run_prints_snapshot_without_dispatch tests/test_entry_surface_scripts.py::test_main_suppresses_when_alert_state_is_unchanged -q`
- 결과: `2 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py tests/test_notification_dispatcher.py tests/test_script_entrypoints.py -q`
  - `46 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `415 passed`
- `git diff --check`

## 2026-05-15 Iteration #193
### 추가 개선: SIR opportunity report도 runtime headline과 lookback context 분리
- runtime 리포트들은 재시작 이후를 active truth로 보는데, `run_session_impulse_retest_opportunity_report.py --lookback-hours 24 --summary-only`는 재시작 전 기회까지 `summary.expected_order_count`로 세고 있었다.
- 실제 확인 시점에는 `summary.expected_order_count=1`이었지만 그 1건은 `before_current_runtime_start_count=1`이었다. 즉 현재 runtime 이후 주문 가능 후보는 0건인데, 과거 후보 1건이 headline 기대 주문처럼 보였다.
- 수정:
  - payload schema를 `session_impulse_retest_opportunity_report_v2`로 올렸다.
  - WS/runtime start가 있으면 `opportunity_scope=runtime_since_ws_start`로 두고 `summary`는 runtime 이후 기회만 집계한다.
  - 전체 lookback의 과거 기회, 가상 성과, reason breakdown은 `lookback_summary`와 `lookback_opportunities`로 보존한다.
  - `--summary-only`에도 `schema_version`을 포함한다.
  - `check_runtime_stack.sh` 라벨도 `runtime headline + lookback context`로 바꿨다.
- 현재 workspace 24h summary:
  - `opportunity_scope=runtime_since_ws_start`
  - active `expected_order_count=0`
  - active potential performance `0R`
  - lookback `expected_order_count=1`
  - lookback `before_current_runtime_start_count=1`
  - lookback reason `session_impulse_retest_rollout_not_ready=1`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 opportunity report와 `check_runtime_stack.sh`가 workspace와 동일한지 diff로 확인했다.
  - runtime_src 24h summary: schema `session_impulse_retest_opportunity_report_v2`, scope `runtime_since_ws_start`, active `expected_order_count=0`, active `total_r=0`, lookback `expected_order_count=1`, lookback pre-runtime `1`
  - runtime_src ops heartbeat: `PASS`, hard `0`, watch `0`

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/run_session_impulse_retest_opportunity_report.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_script_entrypoints.py::test_session_impulse_retest_opportunity_report_performance_uses_configured_risk tests/test_script_entrypoints.py::test_session_impulse_retest_opportunity_report_status_separates_pre_runtime_backfill tests/test_script_entrypoints.py::test_session_impulse_retest_opportunity_report_status_keeps_live_intent_truth_first tests/test_script_entrypoints.py::test_session_impulse_retest_opportunity_summary_can_exclude_pre_runtime_rows -q`
- 결과: `4 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_script_entrypoints.py tests/test_micro_live_operational_guards.py -q`
  - `88 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `416 passed`
- `bash -n scripts/check_runtime_stack.sh`
- `git diff --check`

## 2026-05-15 Iteration #194
### 추가 개선: SIR runtime audit report도 runtime scope와 lookback context 분리
- `run_session_impulse_retest_runtime_audit_report.py --hours 3`도 아직 최근 3시간 전체 audit row를 headline으로 세고 있었다.
- 재시작 직후에는 이전 runtime row가 같은 3시간 창에 남을 수 있으므로, status/count가 현재 runtime row처럼 보일 수 있었다.
- 수정:
  - WS worker `started_at`이 있으면 active audit rows를 `runtime_since_ws_start` 이후로 제한한다.
  - 전체 `--hours` 결과는 `lookback_summary`와 `lookback_recent_audits`로 보존한다.
  - `--lookback-only`와 `--heartbeat-dir`를 추가했다.
  - markdown report 상단에 `audit_scope`, `runtime_started_at`, `lookback_summary`를 표시한다.
- 현재 workspace 기준 3h 결과:
  - `audit_scope=runtime_since_ws_start`
  - active `audit_count=141`
  - lookback `audit_count=200`
  - active hard failures `{}`; status `PASS`

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/run_session_impulse_retest_runtime_audit_report.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_script_entrypoints.py::test_session_impulse_retest_runtime_audit_filters_runtime_scope tests/test_script_entrypoints.py::test_session_impulse_retest_runtime_audit_summary_marks_ws_suppression_non_blocking tests/test_session_impulse_retest_execution_path.py::test_session_impulse_retest_runtime_audit_report_marks_hard_status_fail tests/test_session_impulse_retest_execution_path.py::test_session_impulse_retest_runtime_audit_report_main_writes_latest_aliases -q`
- 결과: `4 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_script_entrypoints.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_live_operational_guards.py -q`
  - `166 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `417 passed`
- `git diff --check`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `run_session_impulse_retest_runtime_audit_report.py`가 workspace와 동일한지 diff로 확인했다.
  - runtime_src latest report도 새 포맷으로 갱신했다.
  - runtime 3h audit headline: `PASS`, reason `runtime_audit_recent_and_no_hard_route_failures`, scope `runtime_since_ws_start`, active `audit_count=67`, lookback `audit_count=200`, hard failures `{}`
  - runtime no-order watchdog: `OK/no_recent_live_intents`, scope `runtime_since_ws_start`, runtime live intents `0`, lookback live intents `21`
  - runtime readiness: `WAIT/no_promotable_live_candidate`, live symbols `NO_FRESH_LIVE_CANDIDATE=11`, auxiliary shadow-only `3`
  - runtime entry surface dry-run: `notified=false`, reason `no_alertable_rows`, `LIVE_ORDER_CANDIDATE=0`, `CONTEXT_REVIEW_SETUP=0`, `BLOCKED_SETUP=0`, `RESEARCH_ONLY_SETUP=0`
  - runtime ops heartbeat: `PASS`, hard `0`, warning `0`

## 2026-05-15 Iteration #195
### 추가 개선: runtime audit status를 order-blocking / non-blocking / no-candidate로 분리
- `run_session_impulse_retest_runtime_audit_report.py` 상단의 `status_counts`에는 `ws_stream_active_route_suppressed`가 많이 보일 수 있다.
- 이 상태는 WS stream worker가 live routing owner라 sync-universe worker가 중복 auto-route를 생략했다는 뜻이고, 주문 차단이 아니다.
- 수정:
  - `_status_summary()`에 `order_blocking_status_counts`, `non_blocking_status_counts`, `no_candidate_status_counts`를 추가했다.
  - markdown report 상단에도 세 필드를 표시한다.
  - `ws_stream_active_route_suppressed`는 `non_blocking_status_counts`로 분리한다.
  - `no_live_route_candidate_plan`, `no_fresh_candidates`는 `no_candidate_status_counts`로 분리한다.
  - `intent_blocked`, `intent_creation_failed`, `submit_error` 또는 `blocking_live_route=true`는 `order_blocking_status_counts`로 분리한다.
- workspace 확인:
  - `overall_status=PASS`
  - `order_blocking={}`
  - `non_blocking={'ws_stream_active_route_suppressed': 84}`
  - `no_candidate={'no_live_route_candidate_plan': 33, 'no_fresh_candidates': 14}`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `run_session_impulse_retest_runtime_audit_report.py`가 workspace와 동일한지 diff로 확인했다.
  - runtime latest report 상단에 `order_blocking_status_counts`, `non_blocking_status_counts`, `no_candidate_status_counts`가 표시된다.
  - runtime 3h audit headline: `PASS`, scope `runtime_since_ws_start`, active `audit_count=32`, `order_blocking={}`, `non_blocking={'ws_stream_active_route_suppressed': 18}`, `no_candidate={'no_live_route_candidate_plan': 11}`, lookback `audit_count=200`
  - runtime no-order watchdog: `OK/no_recent_live_intents`, runtime live intents `0`, runtime submit-ready `0`, runtime blocked `0`, lookback live intents `21`
  - runtime entry surface dry-run: `notified=false`, reason `no_alertable_rows`, `LIVE_ORDER_CANDIDATE=0`, `CONTEXT_REVIEW_SETUP=0`, `BLOCKED_SETUP=0`, `RESEARCH_ONLY_SETUP=0`
  - runtime ops heartbeat: `PASS`, hard `0`, warning `0`

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/run_session_impulse_retest_runtime_audit_report.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_script_entrypoints.py::test_session_impulse_retest_runtime_audit_status_summary_splits_blocking_and_context tests/test_script_entrypoints.py::test_session_impulse_retest_runtime_audit_summary_marks_ws_suppression_non_blocking tests/test_session_impulse_retest_execution_path.py::test_session_impulse_retest_runtime_audit_report_marks_hard_status_fail -q`
- 결과: `3 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_script_entrypoints.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_live_operational_guards.py -q`
  - `167 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `418 passed`
- `git diff --check`

## 2026-05-15 Iteration #196
### 추가 개선: entry surface 알림 제목을 live 후보 없음 / live 후보 차단 / live 후보 확인으로 분리
- `notify_entry_surface.py`는 live 후보가 있거나 live-routable 후보가 blocked 상태면 Discord를 보낸다.
- 그런데 live-routable blocked 후보만 있는 경우 `live_order_candidates=0`이라서 Discord 제목이 `[모니터링] ... 주문 후보 없음`으로 보일 수 있었다.
- 이 상태는 실제 제출 가능 후보는 아니지만, live route 후보가 제출 전 차단된 것이므로 context-only보다 중요하게 보여야 한다.
- 수정:
  - entry surface message headline에 `blocked_live_candidates`를 추가했다.
  - JSON top-level에 `blocked_live_order_candidates`를 추가했다.
  - `order_route_truth`에도 `blocked_live_candidates`를 표시한다.
  - Discord 제목 분기:
    - `live_order_candidates>0`: `[중요] ... 라이브 주문 후보 확인`
    - `blocked_live_candidates>0`: `[주의] ... 라이브 주문 후보 차단`
    - 둘 다 0: `[모니터링] ... 주문 후보 없음`
  - 내부 display 상태 상수는 `SURFACE_STATUSES`로 분리하고 기존 `ALERT_STATUSES`는 호환 alias로 남겼다.
- workspace dry-run:
  - `notified=false`
  - `reason=no_alertable_rows`
  - `live_order_candidates=0`
  - `blocked_live_order_candidates=0`
  - `entry_counts={'LIVE_ORDER_CANDIDATE': 0, 'CONTEXT_REVIEW_SETUP': 0, 'BLOCKED_SETUP': 0, 'RESEARCH_ONLY_SETUP': 0}`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `notify_entry_surface.py`와 `notification_dispatcher.py`가 workspace와 동일한지 diff로 확인했다.
  - runtime dry-run: `notified=false`, `reason=no_alertable_rows`, `live_order_candidates=0`, `blocked_live_order_candidates=0`
  - runtime Discord title probe:
    - none: `[모니터링] USDC_PERP_TOP30 주문 후보 없음`
    - blocked: `[주의] USDC_PERP_TOP30 라이브 주문 후보 차단`
    - live: `[중요] USDC_PERP_TOP30 라이브 주문 후보 확인`

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/notify_entry_surface.py app/services/notification_dispatcher.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_notification_dispatcher.py::test_dispatcher_entry_surface_blocked_live_candidate_title_requires_review tests/test_notification_dispatcher.py::test_dispatcher_entry_surface_context_only_title_is_monitoring tests/test_notification_dispatcher.py::test_dispatcher_entry_surface_live_candidate_title_requires_attention tests/test_entry_surface_scripts.py::test_live_routable_blocked_surface_remains_discord_alertable tests/test_entry_surface_scripts.py::test_render_message_exposes_blocked_live_candidate_count tests/test_entry_surface_scripts.py::test_main_dry_run_prints_snapshot_without_dispatch -q`
- 결과: `6 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py tests/test_notification_dispatcher.py tests/test_script_entrypoints.py -q`
  - `51 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `420 passed`
- `git diff --check`

## 2026-05-15 Iteration #197
### 추가 개선: entry surface wrapper가 runtime venv를 fallback으로 사용
- `run_entry_surface_tick.sh`는 workspace에서 실행되면 `.venv/bin/python`을 사용한다.
- 하지만 runtime source copy에서 직접 실행되면 `.venv`가 없어 system `python3`로 떨어질 수 있었다.
- 수정:
  - `.venv/bin/python`이 없으면 `$TRADING_RUNTIME_BASE/runtime_venv/bin/python`을 먼저 사용한다.
  - runtime venv도 없을 때만 `python3`로 fallback한다.
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `run_entry_surface_tick.sh`, `notify_entry_surface.py`, `notification_dispatcher.py`가 workspace와 동일한지 diff로 확인했다.
  - runtime_src wrapper dry-run: `notified=false`, `reason=no_alertable_rows`, `live_order_candidates=0`, `blocked_live_order_candidates=0`

### 검증
- `bash -n scripts/run_entry_surface_tick.sh`
- workspace wrapper dry-run:
  - `ENTRY_SURFACE_DRY_RUN=1 ENTRY_SURFACE_STATE_FILE=/tmp/trading_entry_surface_tick_state.json ENTRY_SURFACE_LOCK_FILE=/tmp/trading_entry_surface_tick_state.lock ENTRY_SURFACE_OUTPUT_FILE=/tmp/trading_entry_surface_tick_output.json bash scripts/run_entry_surface_tick.sh`
  - `notified=false`, `reason=no_alertable_rows`, `live_order_candidates=0`, `blocked_live_order_candidates=0`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py tests/test_notification_dispatcher.py tests/test_script_entrypoints.py -q`
  - `51 passed`
- `git diff --check`

## 2026-05-15 Iteration #198
### 추가 개선: 운영 watchdog/heartbeat 알림 타입을 entry surface에서 분리
- `run_micro_live_no_order_watchdog.py`, `run_live_reconciliation_watchdog.py`, `run_micro_live_ops_heartbeat.py`가 Discord dispatch에서 `entry_surface_alert` 타입을 재사용하고 있었다.
- dispatcher 제목 방어로 오표시는 막았지만, 타입 의미가 섞이면 나중에 entry surface 규칙이 바뀔 때 운영 경고가 다시 영향을 받을 수 있다.
- 수정:
  - no-order watchdog: `micro_live_no_order_watchdog`
  - reconciliation watchdog: `live_reconciliation_watchdog`
  - ops heartbeat: `micro_live_ops_heartbeat`
  - dispatcher의 중요 알림 allowlist에 세 전용 타입을 추가했다.
  - 전용 타입은 여전히 operational formatter를 사용하므로 기존 Discord 문구 형태는 유지된다.
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 세 운영 스크립트와 `notification_dispatcher.py`가 workspace와 동일한지 diff로 확인했다.
  - runtime title probe:
    - no-order: `[운영] MICRO_LIVE 확인 필요`
    - reconciliation: `[운영] MICRO_LIVE 확인 필요`
    - heartbeat WATCH-only: `[모니터링] MICRO_LIVE 운영 관찰`
  - runtime skip probe: 세 전용 타입 모두 `skip=''`
  - runtime current no-order watchdog: `OK/no_recent_live_intents`, scope `runtime_since_ws_start`, runtime intents `0`, blocked `0`, submit-ready `0`
  - runtime current ops heartbeat: `PASS`, hard `0`, warning `0`
  - runtime current entry surface: `notified=false`, `reason=no_alertable_rows`, `live_order_candidates=0`, `blocked_live_order_candidates=0`

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/run_micro_live_no_order_watchdog.py scripts/run_live_reconciliation_watchdog.py scripts/run_micro_live_ops_heartbeat.py app/services/notification_dispatcher.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_notification_dispatcher.py::test_dispatcher_micro_live_no_order_watchdog_uses_operational_title tests/test_notification_dispatcher.py::test_dispatcher_operational_watchdog_types_are_not_low_importance_suppressed tests/test_notification_dispatcher.py::test_dispatcher_operational_heartbeat_includes_watch_detail tests/test_micro_live_operational_guards.py::test_no_order_watchdog_main_does_not_record_cooldown_when_delivery_fails tests/test_micro_live_operational_guards.py::test_reconciliation_watchdog_main_does_not_record_cooldown_when_delivery_fails tests/test_micro_live_operational_guards.py::test_ops_heartbeat_main_does_not_record_cooldown_when_delivery_fails -q`
- 결과: `6 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_notification_dispatcher.py tests/test_micro_live_operational_guards.py tests/test_entry_surface_scripts.py -q`
  - `111 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py -q`
  - `422 passed`
- `git diff --check`

## 2026-05-15 Iteration #199
### 추가 개선: pre-entry signal alert payload에도 “주문 아님” truth를 명시
- Discord confirm 제목은 이미 `조건 확인 신호(주문 아님)`이지만, DB/로그/retry queue에 저장되는 원본 payload message는 `confirm window open`처럼 보일 수 있었다.
- 사용자가 “진입 확인신호가 나오는데 주문이 안 들어간다”고 오해했던 경로와 같은 종류의 운영 혼선을 줄이기 위해 payload 자체를 보강했다.
- 수정:
  - `near/touch/confirm` subscription alert payload에 `order_submission_expected=false`를 추가했다.
  - 같은 payload에 `order_truth=pre_entry_signal_only`를 추가했다.
  - `order_truth_message`에 “Signal-only alert; it does not submit an order...”를 남긴다.
  - execution fill 계열 alert에는 `order_truth=execution_fill_truth`를 남긴다.
  - Discord formatter는 `order_submission_expected=false`이면 alert type과 무관하게 `주문: 제출 아님 | 실제 주문은 LIVE_ORDER_CANDIDATE/진입 발생 기준` 라인을 붙인다.
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `strategy_engine.py`와 `notification_dispatcher.py`가 workspace와 동일한지 diff로 확인했다.
  - runtime confirm title probe:
    - `[중요] BTCUSDC 조건 확인 신호(주문 아님)`
    - `주문: 제출 아님 | 실제 주문은 LIVE_ORDER_CANDIDATE/진입 발생 기준`
  - runtime no-order watchdog: `OK/no_recent_live_intents`, runtime intents `0`, submit-ready `0`, blocked `0`

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile app/services/strategy_engine.py app/services/notification_dispatcher.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_signal_alerts.py::test_pre_entry_touch_and_confirm_alerts_emit_from_subscriptions tests/test_signal_alerts.py::test_tv_webhook_fanouts_confirm_subscription tests/test_notification_dispatcher.py::test_dispatcher_confirm_signal_is_labeled_as_non_order_signal -q`
- 결과: `3 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_signal_alerts.py tests/test_notification_dispatcher.py tests/test_session_impulse_retest_execution_path.py -q`
  - `103 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py tests/test_signal_alerts.py -q`
  - `428 passed`
- `git diff --check`

## 2026-05-15 Iteration #200
### 결함 수정: `partial_exit`/`sl` execution alert가 낮은 중요도로 suppress될 수 있던 문제
- `StrategyEngine._emit_fill_stage_alerts()`는 부분청산을 `partial_exit`, 손절 종료를 `sl` alert type으로 발행한다.
- 그런데 `NotificationDispatcher`의 Discord 중요 알림 목록과 trade formatter 목록에는 `partial_exit`, `sl`이 빠져 있었다.
- 결과적으로 subscription이 있어도 Discord skip reason이 `discord_low_importance_alert_suppressed`가 되거나, trade alert가 아니라 운영 알림처럼 보일 수 있었다.
- 수정:
  - Discord important types에 `partial_exit`, `sl`을 추가했다.
  - trade signal formatter 대상에 `partial_exit`, `sl`을 추가했다.
  - 제목을 각각 `부분 청산 발생`, `손절 발생`으로 분리했다.
  - fill-stage 회귀 테스트를 추가해 `PARTIAL_EXIT -> partial_exit`, `CLOSED/stop_loss -> sl`이 execution fill truth로 발행되는지 확인한다.
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `notification_dispatcher.py`와 `strategy_engine.py`가 workspace와 동일한지 diff로 확인했다.
  - runtime title probe:
    - `partial_exit skip=''`, `[중요] BTCUSDC 부분 청산 발생`
    - `sl skip=''`, `[중요] BTCUSDC 손절 발생`
  - runtime ops heartbeat: `PASS`, hard `0`, warning `0`

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile app/services/notification_dispatcher.py app/services/strategy_engine.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_notification_dispatcher.py::test_dispatcher_partial_exit_and_sl_are_trade_alerts_not_suppressed tests/test_signal_alerts.py::test_ingest_execution_fill_emits_partial_exit_and_stop_loss_alerts tests/test_signal_alerts.py::test_ingest_execution_fill_emits_entry_tp_and_closed_alerts -q`
- 결과: `3 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_signal_alerts.py tests/test_notification_dispatcher.py tests/test_session_impulse_retest_execution_path.py -q`
  - `105 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py tests/test_signal_alerts.py -q`
  - `430 passed`
- `git diff --check`

## 2026-05-15 Iteration #201
### 추가 개선: execution fill 알림 가격이 실제 체결가를 누락할 수 있던 문제
- `partial_exit`/`sl`을 중요 알림으로 올리는 경로는 복구됐지만, Discord trade formatter의 가격 선택 순서가 `event_price/price/entry_price`였다.
- fill-stage alert payload는 실제 체결가를 `fill_price`에 담으므로, `event_price/price`가 없는 execution fill 알림은 `가격:` 라인이 없거나 진입가로 fallback될 수 있었다.
- 수정:
  - Discord trade formatter 가격 fallback을 `event_price/price/fill_price/entry_price`로 변경했다.
  - `partial_exit`/`sl` 회귀 테스트에서 `fill_price=99.5`가 `가격: 99.5`로 표시되는지 확인한다.
  - runbook에 execution fill truth 알림의 가격 표시는 `fill_price`를 포함해야 한다고 문서화했다.

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_notification_dispatcher.py::test_dispatcher_partial_exit_and_sl_are_trade_alerts_not_suppressed tests/test_signal_alerts.py::test_ingest_execution_fill_emits_partial_exit_and_stop_loss_alerts -q`
- 결과: `2 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_notification_dispatcher.py tests/test_signal_alerts.py tests/test_micro_live_operational_guards.py tests/test_entry_surface_scripts.py -q`
  - `119 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py tests/test_signal_alerts.py -q`
  - `430 passed`
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile app/services/notification_dispatcher.py app/services/strategy_engine.py scripts/notify_entry_surface.py scripts/run_micro_live_no_order_watchdog.py scripts/run_live_reconciliation_watchdog.py scripts/run_micro_live_ops_heartbeat.py`
- `git diff --check`

## 2026-05-15 Iteration #202
### 운영 truth 위치 재확인: workspace stale report와 runtime_src scheduled report 분리
- workspace에서 `run_micro_live_ops_heartbeat.py --no-write-report`를 실행하면 workspace의 `reports/operations/...`를 읽는다.
- 직전 workspace 리포트 일부가 stale이라 heartbeat가 `FAIL`로 보였지만, launchd plist는 runtime 배포본인 `~/Library/Application Support/trading/runtime_src`에서 실행되도록 설치되어 있었다.
- runtime_src의 실제 launchd logs와 latest reports를 확인했다.
  - runtime_src `micro_live_ops_heartbeat/latest.json`: `PASS`, hard `0`, warning `0`
  - runtime_src `micro_live_runtime_guard/latest.md`: fresh
  - runtime_src `live_reconciliation_watchdog/latest.md`: fresh
  - runtime_src `micro_live_no_order_watchdog/latest.md`: fresh
  - runtime_src `micro_live_boot_check/latest.md`: fresh
  - runtime_src `session_impulse_retest_runtime_audit/latest.md`: fresh
- workspace 리포트도 수동으로 갱신해 같은 결론을 확인했다.
  - runtime guard: `PASS/PASS`
  - reconciliation watchdog: `OK/no_reconciliation_gap_detected`
  - no-order watchdog: `OK/no_recent_live_intents`, runtime live intent `0`, submit-ready `0`, blocked `0`
  - session impulse retest runtime audit: `PASS`, hard route failures `0`
  - boot check: `PASS`, blocking failures `0`
  - ops heartbeat: `PASS`, hard `0`, warning `0`
- entry surface launchd는 runtime_src가 아니라 workspace의 `notify_entry_surface.py`와 `reports/operations/entry_surface/latest_entry_alert_run.json`을 사용한다.
  - latest entry surface: `notified=false`, `reason=no_alertable_rows`, `LIVE_ORDER_CANDIDATE=0`, `blocked_live_order_candidates=0`
- runbook에 운영 launchd truth 위치를 명시했다.

## 2026-05-15 Iteration #203
### 운영 개선: launchd scheduled guard stdout 로그 폭증 방지
- runtime_src launchd 로그를 확인했을 때 `session_impulse_retest_runtime_audit.out.log`가 10MB 이상으로 가장 크게 증가하고 있었다.
- 원인은 주기 실행 guard들이 `latest.md/latest.json`을 쓰면서도 매번 전체 JSON payload를 stdout에 출력하는 구조였다.
- 수정:
  - 아래 scheduled guard scripts에 `--quiet` 옵션을 추가했다. 수동 실행은 기존처럼 stdout JSON을 출력하고, `--quiet`일 때만 stdout 출력을 생략한다.
    - `run_micro_live_runtime_guard.py`
    - `run_micro_live_boot_check.py`
    - `run_micro_live_no_order_watchdog.py`
    - `run_live_reconciliation_watchdog.py`
    - `run_micro_live_ops_heartbeat.py`
    - `run_session_impulse_retest_runtime_audit_report.py`
  - `install_micro_live_ops_launchd.py`가 자주 도는 scheduled guard에 `--quiet`를 붙여 plist를 생성하게 했다.
  - 회귀 테스트로 launchd generator의 quiet args 포함 여부와 runtime audit quiet 모드가 stdout 없이 `latest.md/latest.json`을 쓰는지 확인했다.

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/run_micro_live_runtime_guard.py scripts/run_micro_live_boot_check.py scripts/run_micro_live_no_order_watchdog.py scripts/run_live_reconciliation_watchdog.py scripts/run_micro_live_ops_heartbeat.py scripts/run_session_impulse_retest_runtime_audit_report.py scripts/install_micro_live_ops_launchd.py`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py::test_launchd_generator_includes_remaining_operational_guards tests/test_session_impulse_retest_execution_path.py::test_session_impulse_retest_runtime_audit_report_quiet_writes_without_stdout -q`
- 결과: `2 passed`
- quiet smoke:
  - `PYTHONPATH="$PWD" ./.venv/bin/python scripts/run_session_impulse_retest_runtime_audit_report.py --hours 3 --limit 5 --no-fail-exit --quiet --report-dir reports/operations/session_impulse_retest_runtime_audit_quiet_probe`
  - 결과: `exit=0`, stdout 없음, `latest.md/latest.json` 생성
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py tests/test_session_impulse_retest_execution_path.py tests/test_notification_dispatcher.py tests/test_entry_surface_scripts.py -q`
  - `190 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py tests/test_signal_alerts.py -q`
  - `431 passed`
- `git diff --check`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src에서 `install_micro_live_ops_launchd.py --install --unload --load` 실행
  - 결과: `overall_status=PASS`, 12개 launchd job unload/load 모두 returncode `0`
  - 설치된 plist 확인:
    - `com.trading.micro-live.session-impulse-retest-runtime-audit`: `--quiet`
    - `com.trading.micro-live.ops-heartbeat`: `--quiet`
    - `runtime-guard`, `no-order-watchdog`, `reconciliation-watchdog`, `boot-check`, `ops-heartbeat`, `session-impulse-retest-runtime-audit` 모두 `--quiet`
  - `launchctl list`: 12개 `com.trading.micro-live.*` job 로드 확인
  - runtime_src `micro_live_ops_heartbeat/latest.json`: `PASS`, hard `0`, warning `0`
  - runtime_src latest reports fresh:
    - `micro_live_runtime_guard/latest.md`
    - `live_reconciliation_watchdog/latest.md`
    - `micro_live_boot_check/latest.md`
    - `micro_live_ops_heartbeat/latest.md`
    - `session_impulse_retest_runtime_audit/latest.md`
  - 기존 stdout 로그 파일 크기는 그대로 남지만, 새 scheduled guard 실행은 `--quiet` 때문에 추가 JSON dump를 남기지 않는다.
  - quiet smoke 재확인:
    - `runtime_guard stdout_bytes=0`
    - `no_order stdout_bytes=0`
    - `reconciliation stdout_bytes=0`
    - `boot_check stdout_bytes=0`
    - `ops_heartbeat stdout_bytes=0`
    - `sir_audit stdout_bytes=0`
    - `latest_json_count=6`

## 2026-05-15 Iteration #204
### 운영 개선: entry surface launchd stdout 폭증 방지 및 설치 경로 정리
- entry surface launchd의 stdout log가 23MB까지 증가해 있었다.
- `notify_entry_surface.py`는 `latest_entry_alert_run.json`을 쓰면서도 매번 전체 JSON을 stdout에 출력하고 있었다.
- 수정:
  - `notify_entry_surface.py`에 `--quiet` 옵션을 추가했다.
  - `run_entry_surface_tick.sh`는 `ENTRY_SURFACE_QUIET=1`이면 `--quiet`를 넘긴다.
  - entry surface launchd plist는 `--quiet`, `--lock-file`, `--output-file`, `--min-repeat-minutes`를 명시한다.
  - 처음에는 wrapper 실행으로 바꿨지만 launchd에서 macOS Documents 권한 문제로 `/bin/bash ... Operation not permitted`가 발생했다.
  - 따라서 설치 plist는 직접 Python 호출로 되돌리고, quiet/lock/output 계약만 명시하는 방식으로 고정했다.
  - `docs/ENTRY_ALERT_AUTOMATION.md`와 runbook에 quiet 운영 방식을 문서화했다.

### 검증
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/notify_entry_surface.py`
- `bash -n scripts/run_entry_surface_tick.sh`
- `plutil -lint launchd/com.yumin.trading.entry-surface.plist`
- `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py::test_emit_result_quiet_writes_output_without_stdout tests/test_entry_surface_scripts.py::test_main_emits_request_failure_without_dispatch tests/test_entry_surface_scripts.py::test_main_writes_state_after_successful_delivery -q`
- 결과: `3 passed`
- quiet smoke:
  - `ENTRY_SURFACE_DRY_RUN=1 ENTRY_SURFACE_QUIET=1 ... /bin/bash scripts/run_entry_surface_tick.sh`
  - 결과: `exit=0`, `stdout_bytes=0`, latest output `reason=no_alertable_rows`, `live_order_candidates=0`, `blocked_live_order_candidates=0`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py tests/test_notification_dispatcher.py tests/test_micro_live_operational_guards.py tests/test_session_impulse_retest_execution_path.py -q`
  - `191 passed`
- installed launchd:
  - 첫 시도는 workspace bash wrapper를 사용했지만 launchd에서 `/bin/bash ... Operation not permitted`가 발생했다.
  - 두 번째 시도는 workspace Python 직접 호출이었고 latest는 갱신됐지만 `launchctl list` last exit code가 `78/EX_CONFIG`로 남았다.
  - 최종 설치는 runtime_src Python/script/report 경로로 통일했다.
  - `~/Library/LaunchAgents/com.yumin.trading.entry-surface.plist` 재설치/로드
  - installed ProgramArguments includes runtime_src `notify_entry_surface.py`, `--quiet`, `--lock-file`, `--output-file`
  - installed WorkingDirectory/StandardOutPath/StandardErrorPath are under `~/Library/Application Support/trading/runtime_src`
  - runtime_src code and installed plist are synced with workspace source.
  - kickstart 후 종료 상태:
    - `launchctl list`: `com.yumin.trading.entry-surface` status `0`
    - runtime_src entry surface stdout/stderr logs: `0` bytes
    - runtime_src latest entry surface: `notified=false`, `reason=no_alertable_rows`, `live_order_candidates=0`, `blocked_live_order_candidates=0`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py tests/test_signal_alerts.py -q`
  - `432 passed`
- `git diff --check`

## 2026-05-15 Iteration #205
### 운영 개선: entry surface schedule도 ops heartbeat truth에 포함
- entry surface launchd는 별도 agent라서 `latest_entry_alert_run.json`이 stale 되거나 `/portfolio/budget` 요청 실패가 남아도, 기존 MICRO_LIVE ops heartbeat만 보면 다른 guard들이 PASS인 상태로 보일 수 있었다.
- 수정:
  - `run_micro_live_ops_heartbeat.py` 기본 job에 `entry_surface`를 추가했다.
  - 감시 대상은 runtime/workspace 기준 `reports/operations/entry_surface/latest_entry_alert_run.json`이다.
  - `source_request_failed`, snapshot missing, stale file은 hard failure로 올린다.
  - `entry_surface_tick_already_running`은 이전 tick이 아직 돈다는 뜻이라 WATCH로 올린다.
  - delivery가 neither delivered nor skipped이면 WATCH로 올린다.
  - 정상적인 `no_alertable_rows`는 PASS로 남기되, `status_detail/report_reason`에 원인을 보존한다.
  - `docs/ENTRY_ALERT_AUTOMATION.md`와 runbook에 entry surface가 ops heartbeat 감시 대상이라는 점을 문서화했다.

### 검증
- targeted:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py::test_ops_heartbeat_defaults_include_entry_surface tests/test_micro_live_operational_guards.py::test_ops_heartbeat_checks_entry_surface_latest_payload tests/test_micro_live_operational_guards.py::test_ops_heartbeat_fails_on_entry_surface_source_request_failure -q`
  - `3 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py tests/test_entry_surface_scripts.py tests/test_notification_dispatcher.py -q`
  - `116 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py tests/test_signal_alerts.py -q`
  - `435 passed`
- `PYTHONPATH="$PWD" ./.venv/bin/python -m py_compile scripts/run_micro_live_ops_heartbeat.py scripts/notify_entry_surface.py app/services/notification_dispatcher.py`
- `git diff --check`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `run_micro_live_ops_heartbeat.py`가 workspace와 동일한지 diff로 확인했다.
  - `launchctl list`: `com.yumin.trading.entry-surface`, `com.trading.micro-live.ops-heartbeat` 모두 status `0`
  - entry surface kickstart 후 runtime latest:
    - `notified=false`
    - `reason=no_alertable_rows`
    - `LIVE_ORDER_CANDIDATE=0`
    - `BLOCKED_SETUP=3`
    - `CONTEXT_REVIEW_SETUP=2`
    - `blocked_live_order_candidates=0`
  - runtime entry surface stdout/stderr logs: `0` bytes
  - runtime ops heartbeat:
    - `overall_status=PASS`
    - hard `0`, warning `0`
    - `entry_surface.status=PASS`
    - `entry_surface.status_detail=no_alertable_rows`
  - ops heartbeat launchd kickstart 후 `latest.json`도 같은 결과로 갱신됨
  - runtime ops heartbeat stdout/stderr logs: `0` bytes

## 2026-05-15 Iteration #206
### 운영 개선: `BLOCKED_SETUP`을 live-blocked와 context-only blocked로 분해
- 현재 runtime entry surface는 `BLOCKED_SETUP=3`이지만, 각 row의 `entry_surface_route.status`는 `context_only`였다.
- 이 상태는 portfolio surface의 blocked context가 있다는 뜻이지, live-route 주문 후보가 submit 전에 막혔다는 뜻은 아니다.
- 기존 payload에도 `blocked_live_order_candidates=0`은 있었지만, `BLOCKED_SETUP=3`만 보면 주문 차단처럼 오해할 수 있었다.
- 수정:
  - entry surface headline에 `blocked_context_only`를 추가했다.
  - message counts line에 `blocked_breakdown=live:N,context_only:M`을 추가했다.
  - `BLOCKED_SETUP` 섹션 제목도 `(live=N, context_only=M)`를 같이 보여준다.
  - result top-level에 `blocked_context_only_setups`와 `blocked_setup_breakdown`을 추가했다.
  - alertable 조건은 유지했다: `LIVE_ORDER_CANDIDATE>0` 또는 `blocked_live_order_candidates>0`일 때만 Discord alert 대상이다.
  - `docs/ENTRY_ALERT_AUTOMATION.md`와 runbook에 `BLOCKED_SETUP` 전체와 live-blocked 주문 후보를 분리해서 읽어야 한다고 문서화했다.

### 검증
- targeted:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py::test_context_only_surface_is_not_discord_alertable tests/test_entry_surface_scripts.py::test_render_message_exposes_blocked_live_candidate_count tests/test_entry_surface_scripts.py::test_render_message_includes_all_sections_and_reasons -q`
  - `3 passed`
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_notification_dispatcher.py::test_dispatcher_entry_surface_context_only_blocked_title_stays_monitoring tests/test_notification_dispatcher.py::test_dispatcher_entry_surface_blocked_live_candidate_title_requires_review -q`
  - `2 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py tests/test_notification_dispatcher.py tests/test_micro_live_operational_guards.py -q`
  - `116 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py tests/test_signal_alerts.py -q`
  - `436 passed`
- `git diff --check`
- workspace dry-run:
  - `reason=no_alertable_rows`
  - `LIVE_ORDER_CANDIDATE=0`
  - `blocked_live_order_candidates=0`
  - `blocked_context_only_setups=3`
  - `blocked_setup_breakdown={context_only: 3, live_routable: 0}`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `notify_entry_surface.py`가 workspace와 동일한지 diff로 확인했다.
  - entry surface launchd kickstart 후 runtime latest:
    - `reason=no_alertable_rows`
    - `notified=false`
    - `LIVE_ORDER_CANDIDATE=0`
    - `blocked_live_order_candidates=0`
    - `blocked_context_only_setups=3`
    - `blocked_setup_breakdown={context_only: 3, live_routable: 0}`
  - runtime entry surface stdout/stderr logs: `0` bytes
  - runtime ops heartbeat:
    - `overall_status=PASS`
    - hard `0`, warning `0`
    - `entry_surface.status_detail=no_alertable_rows`

## 2026-05-16 Iteration #208
### 운영 개선: no-order 진단에 백테스트 조건 재생값을 같이 붙임
- 판단:
  - 사용자의 지적대로, 주문 빈도/수익률을 백테스트와 비교하려면 live 전략 계약은 백테스트를 만든 조건과 같아야 한다.
  - 현재 live 전략 계약은 `session_impulse_retest + CONFIRM + 11개 MICRO_LIVE 심볼 + dead_session/london/new_york + partial_activation_ratio=1.00`로 맞아 있다.
  - 단, exchange submit 전의 운영 안전장치(검증 GO, close-only, liquidity, exchange rule, position cap, event blackout)는 백테스트 전략 조건이 아니라 실전 안전장치이므로 끄지 않는다. 대신 이 장치가 백테스트 기대 주문을 막으면 리포트에서 명시적으로 보여야 한다.
- 최근 runtime 확인:
  - runtime ops heartbeat: `PASS`, hard `0`, warning `0`.
  - runtime no-order watchdog: `status=OK`, `reason=no_recent_live_intents`.
  - runtime 재시작 이후 SIR 백테스트 조건 재생 기대 주문: `0`건.
  - 최근 72시간 lookback 기준 기대 주문: `2`건, `+1.235292R`; 둘 다 현재 runtime 재시작 이전의 차단 이력이다.
  - 따라서 현재는 “조건이 됐는데 또 막히는 상태”가 아니라 “재시작 이후 아직 SIR fresh 후보가 없는 상태”다.
- 수정:
  - `run_micro_live_no_order_watchdog.py`가 `session_impulse_retest_opportunity_report` 요약을 함께 포함한다.
  - no-order 상태에서도 `SIR_opportunity=active_expected=N,lookback_expected=M`을 남긴다.
  - runtime 재시작 이후 백테스트 조건 기대 후보가 있는데 live intent가 0이면 `sir_backtest_opportunity_without_live_intent` WARN으로 올린다.
  - runtime_src에도 동일 스크립트를 반영했다.

### 검증
- `./.venv/bin/python -m py_compile scripts/run_micro_live_no_order_watchdog.py tests/test_micro_live_operational_guards.py`
- `./.venv/bin/python -m pytest tests/test_micro_live_operational_guards.py::test_no_order_watchdog_augments_no_intents_with_sir_candidate_context tests/test_micro_live_operational_guards.py::test_no_order_watchdog_alerts_when_backtest_opportunity_has_no_live_intent tests/test_micro_live_operational_guards.py::test_no_order_watchdog_message_separates_runtime_scope_from_lookback_context tests/test_micro_live_operational_guards.py::test_no_order_watchdog_message_includes_backtest_opportunity_context -q` -> `4 passed`
- `git diff --check -- scripts/run_micro_live_no_order_watchdog.py tests/test_micro_live_operational_guards.py`
- runtime:
  - `runtime_src/scripts/run_micro_live_no_order_watchdog.py --days 3 --no-fail-exit --quiet`
  - `runtime_src/scripts/run_micro_live_ops_heartbeat.py --no-fail-exit --quiet`
  - latest heartbeat `overall_status=PASS`, failure `0`, warning `0`.

## 2026-05-16 Iteration #209
### 추가 빈틈 점검: SIR core slot 계산과 runtime guard warning 숨김
- 발견:
  - `NEARUSDC`는 현재 MICRO_LIVE allowlist에 포함되어 있고 universe policy에서도 `core`다.
  - 하지만 SIR rollout window check/readiness는 `core_live_slots=11`을 전체 `rollout_priority`와 비교하고 있었다.
  - universe priority에는 live가 아닌 secondary `SUIUSDC`가 중간에 있어 `NEARUSDC`가 raw priority `12`로 계산됐고, `outside_current_core_live_window` warning/blocker 후보가 될 수 있었다.
  - 즉 “11개 core live 심볼”이라는 계약과 “전체 priority 11번까지”라는 계산이 달랐다.
  - runtime guard는 이 warning check를 내부 `FAIL`로 갖고도 top-level `PASS`로 표시해, top-level만 보면 놓칠 수 있었다.
- 수정:
  - `evaluate_micro_main_live_readiness(...)`는 core slot을 raw priority가 아니라 core 심볼끼리의 순위(`core_live_rank`)로 계산한다.
  - preflight/runtime guard의 `session_impulse_retest_live_rollout_window`도 같은 core-rank 기준으로 바꿨다.
  - runtime guard는 warning severity check 실패도 top-level `WATCH`와 `warning_failures`로 드러내게 했다.
  - `.env.example`을 실제 runtime 계약과 맞춰 `SESSION_IMPULSE_RETEST_CORE_LIVE_SLOTS=11`, `SESSION_IMPULSE_RETEST_SATURDAY_RISK_MULTIPLIER=0.75`, tracked symbol list를 정렬했다.
  - runtime_src에 수정 파일을 반영하고 runtime stack을 재시작했다.
- runtime 확인:
  - `/health/ready`: ready.
  - runtime guard: `overall_status=PASS`, `operational_status=PASS`, `blocking_failures=[]`, `warning_failures=[]`.
  - `session_impulse_retest_live_rollout_window`: `PASS`, `outside_core_window=none`.
  - `NEARUSDC` readiness: `status=live_bootstrap_collecting`, `blockers=[]`, `core_live_rank=11`.
  - runtime no-order watchdog: `status=OK`, `reason=no_recent_live_intents`, `active_expected=0`, `lookback_expected=2`.
  - runtime ops heartbeat: `PASS`, failure `0`, warning `0`.
- 남은 의도적 표기:
  - `live_replay_parity.latest.json`의 `lookback_evaluation_summary.status=WATCH`는 현재 runtime headline이 아니라 재시작 전 lookback 이력이다. active headline은 `runtime_since_ws_start` 기준이라 `PASS`가 맞다.
  - `failure_drill` 내부의 `FAIL/ALERT`는 실패 시나리오가 감지되는지 확인하는 drill의 expected/observed payload라 정상이다.

### 검증
- `./.venv/bin/python -m pytest tests/test_micro_main_live_readiness.py tests/test_micro_live_preflight.py::test_micro_live_config_drift_checks_warn_when_live_symbol_is_outside_sir_core_window tests/test_micro_live_runtime_guard.py -q` -> `8 passed`
- `./.venv/bin/python -m pytest tests/test_session_impulse_retest_execution_path.py::test_session_impulse_retest_live_readiness_without_blockers_can_approve tests/test_session_impulse_retest_execution_path.py::test_session_impulse_retest_live_bootstrap_advisory_sample_gap_can_submit tests/test_session_impulse_retest_execution_path.py::test_session_impulse_retest_secondary_symbol_stays_shadow_even_if_allowlisted -q` -> `3 passed`
- `./.venv/bin/python -m pytest tests/test_micro_main_live_readiness.py tests/test_micro_live_preflight.py tests/test_micro_live_runtime_guard.py tests/test_micro_live_operational_guards.py -q` -> `110 passed`

## 2026-05-15 Iteration #208
### 운영 개선: no-order watchdog에 SIR 후보 생성 context 추가
- `run_micro_live_no_order_watchdog.py`는 live intent/submission gap을 잘 보여주지만, live intent가 0이면 `fresh live 후보 대기`로 끝났다.
- 이 경우 사용자는 "시작하지 않으면 실전 종료 표본이 계속 0 아닌가?"라는 모순을 다시 확인해야 했다.
- 수정:
  - no-order watchdog payload에 `candidate_generation_context`를 추가했다.
  - current family filter에 `session_impulse_retest`가 있으면 DB의 SIR runtime audit을 같은 runtime scope로 집계한다.
  - `no_candidate_status_counts`, `non_blocking_status_counts`, `order_blocking_status_counts`, `watch_status_counts`, `hard_status_counts`를 함께 남긴다.
  - live intent가 0일 때 `next_action_text`를 SIR audit 기준으로 구체화한다.
    - 예: `SIR fresh 후보 대기: no_live_route_candidate_plan=11`
  - watchdog Discord message에도 `후보: SIR audit ... / no_candidate=... / non_blocking=... / order_blocking=...` 라인을 추가했다.
  - message 안의 `actions=`도 새 `next_action_text`와 일관되도록 갱신했다.
  - runbook에 no-order watchdog이 SIR 후보 생성 context를 함께 보여준다고 문서화했다.

### 검증
- targeted:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py::test_no_order_watchdog_augments_no_intents_with_sir_candidate_context tests/test_micro_live_operational_guards.py::test_no_order_watchdog_message_separates_runtime_scope_from_lookback_context -q`
  - `2 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py tests/test_entry_surface_scripts.py tests/test_notification_dispatcher.py -q`
  - `118 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py tests/test_signal_alerts.py -q`
  - `437 passed`
- `git diff --check`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `run_micro_live_no_order_watchdog.py`가 workspace와 동일한지 diff로 확인했다.
  - runtime no-order watchdog direct run:
    - `status=OK`
    - `reason=no_recent_live_intents`
    - `next=SIR fresh 후보 대기: no_live_route_candidate_plan=11`
    - `candidate_generation_status=no_live_route_candidate`
    - `audit_count=27`
    - `order_blocking_status_counts={}`
    - `no_candidate_status_counts={no_live_route_candidate_plan: 11}`
    - `non_blocking_status_counts={ws_stream_active_route_suppressed: 14}`
  - no-order watchdog launchd kickstart 후 latest:
    - `status=OK`
    - `reason=no_recent_live_intents`
    - `next=SIR fresh 후보 대기: no_live_route_candidate_plan=11`
    - `candidate_generation_status=no_live_route_candidate`
    - `audit_count=35`
    - `order_blocking_status_counts={}`
  - runtime ops heartbeat:
    - `overall_status=PASS`
    - hard `0`, warning `0`
    - `no_order_watchdog.report_reason=no_recent_live_intents`
    - `entry_surface.report_reason=no_alertable_rows`
  - no-order/ops-heartbeat stdout/stderr logs: `0` bytes

## 2026-05-15 Iteration #209
### 운영 개선: no-order SIR 후보 context에 WATCH 상태도 노출
- Iteration #208에서 no-order watchdog에 SIR 후보 생성 context를 붙였지만, `symbol_not_live_enabled_for_auto_route` 같은 WATCH 상태는 payload에는 있어도 message 요약에는 나오지 않았다.
- 현재 runtime에서도 `watch_status_counts={symbol_not_live_enabled_for_auto_route: N}`가 발생하고 있었다.
- 이 상태는 주문 차단은 아니지만, 왜 auto-route audit이 쌓이면서 intent가 0인지 이해하는 데 필요하다.
- 수정:
  - `watch_status_counts`를 no-order watchdog message의 `후보:` 라인에 추가했다.
  - evaluation message에도 `watch=...`를 추가했다.
  - no-candidate가 없고 watch만 있는 경우 `candidate_generation_status=watch_candidate_context`, `next_action_text=SIR 후보 생성 watch 확인: ...`로 표시한다.

### 검증
- targeted:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py::test_no_order_watchdog_augments_no_intents_with_sir_candidate_context tests/test_micro_live_operational_guards.py::test_no_order_watchdog_augments_watch_only_sir_candidate_context tests/test_micro_live_operational_guards.py::test_no_order_watchdog_message_separates_runtime_scope_from_lookback_context -q`
  - `3 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py tests/test_entry_surface_scripts.py tests/test_notification_dispatcher.py -q`
  - `119 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py tests/test_signal_alerts.py -q`
  - `438 passed`
- `git diff --check`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime no-order watchdog launchd latest:
    - `status=OK`
    - `reason=no_recent_live_intents`
    - `next=SIR fresh 후보 대기: no_live_route_candidate_plan=9`
    - `candidate_generation_status=no_live_route_candidate`
    - `watch={symbol_not_live_enabled_for_auto_route: 2}`
    - message includes `watch=symbol_not_live_enabled_for_auto_route=2`
    - `order_blocking=none`
  - runtime ops heartbeat:
    - `overall_status=PASS`
    - hard `0`, warning `0`
    - `no_order_watchdog.report_reason=no_recent_live_intents`
  - no-order/ops-heartbeat stdout/stderr logs: `0` bytes

## 2026-05-15 Iteration #215
### 운영 수정: workspace/runtime_src entry surface 배포 drift 해소
- 추가 점검 중 workspace의 `notify_entry_surface.py`와 runtime_src의 `notify_entry_surface.py`가 달라진 상태를 발견했다.
- workspace는 `reason=no_live_order_candidates_context_only_route_mismatch`와 `legacy_reason=no_alertable_rows` 계약을 갖고 있었지만, runtime_src는 직전 버전이라 launchd latest가 계속 `reason=no_alertable_rows`를 쓰고 있었다.
- 조치:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`로 runtime_src를 다시 갱신했다.
  - workspace/runtime_src `notify_entry_surface.py` diff가 비었는지 확인했다.
  - entry surface와 ops heartbeat launchd를 kickstart했다.
- 결과:
  - runtime entry surface latest:
    - `reason=no_live_order_candidates_context_only_route_mismatch`
    - `legacy_reason=no_alertable_rows`
    - `live_order_candidates=0`
    - `blocked_live_order_candidates=0`
    - `operator_action_summary.state=context_only_outside_live_route`
  - runtime ops heartbeat:
    - `overall_status=PASS`
    - hard `0`, warning `0`
    - `entry_surface.report_reason=no_live_order_candidates_context_only_route_mismatch`
    - `entry_surface.status_detail=no_live_order_candidates_context_only_route_mismatch | operator_action=context_only_outside_live_route | next=wait_for_live_route_candidate_or_change_live_contract_intentionally | route_reason=strategy_family_not_live_route:22`
  - entry surface/ops heartbeat stdout/stderr logs: `0` bytes

## 2026-05-15 Iteration #214
### 결함 수정: entry surface lock contention이 latest output에 기록되지 않던 문제
- entry surface는 non-overlap lock을 써서 이전 `/portfolio/budget` tick이 아직 실행 중이면 다음 tick을 시작하지 않는다.
- 문서와 ops heartbeat 계약상 이 경우 `reason=entry_surface_tick_already_running`이 latest run payload에 남아야 한다.
- 하지만 lock 획득 실패 branch가 `_emit_result(None, ...)`를 호출하고 있어서, launchd quiet 모드에서는 stdout도 latest output도 남지 않을 수 있었다.
- 수정:
  - lock contention branch도 `output_file`로 `_emit_result`를 호출한다.
  - quiet mode에서는 stdout 없이 `latest_entry_alert_run.json`에 `entry_surface_tick_already_running`을 기록한다.
  - source request는 lock 획득 후에만 실행되는 기존 계약을 유지한다.

### 검증
- targeted:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py::test_main_lock_contention_writes_latest_output_file tests/test_micro_live_operational_guards.py::test_ops_heartbeat_checks_entry_surface_latest_payload -q`
  - `2 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py tests/test_notification_dispatcher.py tests/test_micro_live_operational_guards.py -q`
  - `122 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py tests/test_signal_alerts.py -q`
  - `441 passed`
- `git diff --check`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `notify_entry_surface.py`가 workspace와 동일한지 diff로 확인했다.
  - entry surface launchd kickstart 후 runtime latest:
    - `reason=no_alertable_rows`
    - `notified=false`
    - `state_written=true`
    - `message` present
    - `live_order_candidates=0`
    - `blocked_live_order_candidates=0`
    - `operator_action_summary.state=context_only_outside_live_route`
  - runtime ops heartbeat:
    - `overall_status=PASS`
    - hard `0`, warning `0`
    - `entry_surface.status_detail=no_alertable_rows | operator_action=context_only_outside_live_route | next=wait_for_live_route_candidate_or_change_live_contract_intentionally | route_reason=strategy_family_not_live_route:22`
  - entry surface/ops heartbeat stdout/stderr logs: `0` bytes

## 2026-05-15 Iteration #213
### 운영 개선: no-alert entry surface result에도 rendered message 보존
- entry surface는 Discord 전송이 필요한 경우에만 `message`를 result에 붙이고 있었다.
- 그래서 `reason=no_alertable_rows`인 정상 대기 상태에서는 latest JSON 안에 counts/operator action은 있지만, 실제 Discord와 같은 human-readable 요약은 없었다.
- 수정:
  - `notify_entry_surface.py`가 snapshot 생성 직후 항상 `render_message(snapshot)`를 result에 저장한다.
  - `no_alertable_rows`, `unchanged_surface_state`, `recent_surface_state_repeat`, `dry_run`, 실제 dispatch 모두 같은 message 형식을 공유한다.
  - Discord dispatch 여부는 기존 `_has_alertable_rows`와 dedupe 결과를 그대로 따른다.
  - docs에 no-alert saved result도 rendered `message`를 가진다는 점을 추가했다.

### 검증
- targeted:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py::test_main_no_alertable_rows_still_emits_rendered_message tests/test_entry_surface_scripts.py::test_main_dry_run_prints_snapshot_without_dispatch tests/test_entry_surface_scripts.py::test_context_only_surface_is_not_discord_alertable -q`
  - `3 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py tests/test_notification_dispatcher.py tests/test_micro_live_operational_guards.py -q`
  - `121 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py tests/test_signal_alerts.py -q`
  - `440 passed`
- `git diff --check`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `notify_entry_surface.py`가 workspace와 동일한지 diff로 확인했다.
  - entry surface launchd kickstart 후 runtime latest:
    - `reason=no_alertable_rows`
    - `notified=false`
    - `message` present
    - message headline: `Trading entry surface alert: live_order_candidates=0, review_candidates=2, blocked_live_candidates=0, blocked_context_only=20`
    - message operator line: `operator_action: state=context_only_outside_live_route | priority=monitor | next=wait_for_live_route_candidate_or_change_live_contract_intentionally | reason=strategy_family_not_live_route:22`
  - runtime ops heartbeat:
    - `overall_status=PASS`
    - hard `0`, warning `0`
    - `entry_surface.status_detail=no_alertable_rows | operator_action=context_only_outside_live_route | next=wait_for_live_route_candidate_or_change_live_contract_intentionally | route_reason=strategy_family_not_live_route:22`
  - entry surface/ops heartbeat stdout/stderr logs: `0` bytes

## 2026-05-15 Iteration #212
### 운영 개선: heartbeat가 entry surface operator action까지 표시
- Iteration #211에서 entry surface 자체에는 `operator_action_summary`가 생겼지만, ops heartbeat만 보면 정상 케이스가 여전히 `status_detail=no_alertable_rows`로 축약됐다.
- 이러면 runtime이 PASS여도 "정말 후보가 없는지, route 밖 context-only인지"를 다시 latest entry surface JSON까지 열어야 했다.
- 수정:
  - `run_micro_live_ops_heartbeat.py`의 entry surface content check가 `operator_action_summary`를 읽는다.
  - healthy run에서는 `report_reason=no_alertable_rows`를 보존하면서 `status_detail`에 `operator_action=<state>`, `next=<next_action>`, `route_reason=<top_route_mismatch_reason>`을 붙인다.
  - heartbeat job row에도 `entry_surface_operator_action_state`, `entry_surface_operator_next_action`, `entry_surface_operator_route_reason`을 보존한다.
  - docs에 heartbeat에서 entry surface operator action을 읽는 법을 추가했다.

### 검증
- targeted:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py::test_ops_heartbeat_checks_entry_surface_latest_payload tests/test_micro_live_operational_guards.py::test_ops_heartbeat_fails_on_entry_surface_source_request_failure -q`
  - `2 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_micro_live_operational_guards.py tests/test_entry_surface_scripts.py tests/test_notification_dispatcher.py -q`
  - `120 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py tests/test_signal_alerts.py -q`
  - `439 passed`
- `git diff --check`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `run_micro_live_ops_heartbeat.py`가 workspace와 동일한지 diff로 확인했다.
  - entry surface + ops heartbeat launchd kickstart 후 runtime latest:
    - `overall_status=PASS`
    - hard `0`, warning `0`
    - `entry_surface.report_reason=no_alertable_rows`
    - `entry_surface.status_detail=no_alertable_rows | operator_action=context_only_outside_live_route | next=wait_for_live_route_candidate_or_change_live_contract_intentionally | route_reason=strategy_family_not_live_route:22`
    - `entry_surface.entry_surface_operator_action_state=context_only_outside_live_route`
  - runtime entry surface latest:
    - `live_order_candidates=0`
    - `blocked_live_order_candidates=0`
    - `blocked_context_only_setups=20`
    - `operator_action_summary.state=context_only_outside_live_route`
  - entry surface/ops heartbeat stdout/stderr logs: `0` bytes

## 2026-05-15 Iteration #211
### 운영 개선: entry surface에 operator action summary 추가
- Iteration #210에서 entry surface의 source count와 route mismatch 집계를 정확히 만들었지만, operator가 먼저 어떤 상태로 읽어야 하는지는 아직 메시지와 JSON에 명시되지 않았다.
- 특히 `route_mismatch_summary.context_only_total>0`이고 `LIVE_ORDER_CANDIDATE=0`인 경우, "후보는 많은데 왜 주문이 안 들어가나"로 다시 오해할 수 있었다.
- 수정:
  - `operator_action_summary`를 entry surface snapshot/result top-level에 추가했다.
  - 상태는 `live_order_candidate_present`, `live_order_candidate_blocked`, `context_only_outside_live_route`, `no_surface_candidates` 중 하나로 정규화한다.
  - live 후보가 있으면 intent/submission/fill 확인, live-routable blocked 후보가 있으면 validation/portfolio/risk blocker 확인, context-only뿐이면 live route 후보 대기 또는 의도적 live contract 변경으로 안내한다.
  - message에 `operator_action: state=... | priority=... | next=... | reason=... | family=... | entry_model=... | symbol=...` 라인을 추가했다.
  - docs에 `operator_action_summary` 읽는 법을 추가했다.

### 검증
- targeted:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py::test_build_entry_snapshot_maps_rows_to_three_statuses tests/test_entry_surface_scripts.py::test_entry_snapshot_counts_source_rows_not_display_cap tests/test_entry_surface_scripts.py::test_render_message_includes_all_sections_and_reasons tests/test_entry_surface_scripts.py::test_context_only_surface_is_not_discord_alertable tests/test_entry_surface_scripts.py::test_render_message_exposes_blocked_live_candidate_count -q`
  - `5 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py tests/test_notification_dispatcher.py tests/test_micro_live_operational_guards.py -q`
  - `120 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py tests/test_signal_alerts.py -q`
  - `439 passed`
- `git diff --check`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `notify_entry_surface.py`가 workspace와 동일한지 diff로 확인했다.
  - entry surface launchd kickstart 후 runtime latest:
    - `reason=no_alertable_rows`
    - `notified=false`
    - `live_order_candidates=0`
    - `blocked_live_order_candidates=0`
    - `context_review_setups=2`
    - `blocked_setups=20`
    - `blocked_context_only_setups=20`
    - `route_mismatch_summary.context_only_total=22`
    - `operator_action_summary.state=context_only_outside_live_route`
    - `operator_action_summary.next_action=wait_for_live_route_candidate_or_change_live_contract_intentionally`
    - `operator_action_summary.top_route_mismatch_reason=strategy_family_not_live_route:22`
    - `operator_action_summary.top_route_mismatch_family=legacy_zone_plan:19`
    - `operator_action_summary.top_route_mismatch_entry_model=SWEEP_CONFIRM:11`
  - runtime ops heartbeat:
    - `overall_status=PASS`
    - hard `0`, warning `0`
    - `entry_surface.report_reason=no_alertable_rows`
  - entry surface/ops heartbeat stdout/stderr logs: `0` bytes

## 2026-05-15 Iteration #210
### 결함 수정: entry surface counts가 표시 cap 기준으로 과소 집계되던 문제
- `notify_entry_surface.py`는 `--max-per-status`로 각 section의 표시 row 수를 제한한다.
- 그런데 기존 `snapshot.counts`와 top-level `entry_counts/blocked_setups/context_review_setups`가 제한 후 row 수를 세고 있었다.
- 문서에는 `snapshot.counts`가 full source truth라고 되어 있었기 때문에, 실제 후보가 20개여도 operator surface에는 `BLOCKED_SETUP=3`처럼 보일 수 있었다.
- 수정:
  - source row 전체를 먼저 분류/정렬하고, `counts/source_counts`는 전체 source row 수로 둔다.
  - `sections`는 compact display로 유지한다.
  - `display_counts`는 실제 표시된 row 수를 담는다.
  - `truncated_counts/truncated_entry_counts`는 compact display에서 생략된 row 수를 담는다.
  - `route_mismatch_summary`와 `blocked_setup_breakdown`도 display cap 이후가 아니라 source 전체 기준으로 계산한다.
  - entry surface message의 counts line에 `displayed=...`, `truncated=...`를 추가했다.
  - section title에 `showing=X/Y`를 붙여 표시 row가 전체가 아닐 때 바로 알 수 있게 했다.
  - docs에 `counts/source_counts`와 `display_counts/truncated_entry_counts`의 차이를 문서화했다.

### 검증
- targeted:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py::test_entry_snapshot_counts_source_rows_not_display_cap tests/test_entry_surface_scripts.py::test_context_only_surface_is_not_discord_alertable tests/test_entry_surface_scripts.py::test_render_message_includes_all_sections_and_reasons -q`
  - `3 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py tests/test_notification_dispatcher.py tests/test_micro_live_operational_guards.py -q`
  - `120 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py tests/test_signal_alerts.py -q`
  - `439 passed`
- `git diff --check`
- workspace dry-run:
  - `reason=no_alertable_rows`
  - `live_order_candidates=0`
  - `blocked_live_order_candidates=0`
  - `context_review_setups=2`
  - `blocked_setups=20`
  - `display_counts.BLOCKED_SETUP=3`
  - `truncated_entry_counts.BLOCKED_SETUP=17`
  - `route_mismatch_summary.context_only_total=22`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `notify_entry_surface.py`가 workspace와 동일한지 diff로 확인했다.
  - entry surface launchd kickstart 후 runtime latest:
    - `reason=no_alertable_rows`
    - `notified=false`
    - `live_order_candidates=0`
    - `blocked_live_order_candidates=0`
    - `context_review_setups=2`
    - `blocked_setups=20`
    - `blocked_context_only_setups=20`
    - `display_counts.BLOCKED_SETUP=3`
    - `truncated_entry_counts.BLOCKED_SETUP=17`
    - `route_mismatch_summary.context_only_total=22`
    - `route_mismatch_summary.by_strategy_family={legacy_zone_plan: 19, sweep_reversal: 3}`
  - runtime entry surface stdout/stderr logs: `0` bytes
  - runtime ops heartbeat direct check:
    - `overall_status=PASS`
    - hard `0`, warning `0`
    - `entry_surface.report_reason=no_alertable_rows`
  - ops heartbeat launchd kickstart 후 latest도 `PASS`, hard `0`, warning `0`
  - runtime 후보별 route 확인:
    - `BLOCKED_SETUP NEARUSDC LONG SWEEP_CONFIRM legacy_zone_plan -> context_only(strategy_family_not_live_route, entry_model_not_live_route)`
    - `BLOCKED_SETUP SUIUSDC LONG SWEEP_CONFIRM legacy_zone_plan -> context_only(symbol_not_live_routable, strategy_family_not_live_route, entry_model_not_live_route)`
    - `BLOCKED_SETUP DOGEUSDC LONG SWEEP_CONFIRM legacy_zone_plan -> context_only(symbol_not_live_routable, strategy_family_not_live_route, entry_model_not_live_route)`
    - `CONTEXT_REVIEW_SETUP NEARUSDC LONG CONFIRM legacy_zone_plan -> context_only(strategy_family_not_live_route)`
    - `CONTEXT_REVIEW_SETUP DOGEUSDC LONG SWEEP_CONFIRM legacy_zone_plan -> context_only(symbol_not_live_routable, strategy_family_not_live_route, entry_model_not_live_route)`

## 2026-05-15 Iteration #207
### 운영 개선: live 후보 0의 route mismatch 원인을 entry surface artifact에 직접 요약
- 현재 주문 계약은 `session_impulse_retest + CONFIRM + 11개 MICRO_LIVE 심볼 + dead_session/london/new_york`다.
- runtime entry surface에는 `legacy_zone_plan` 후보가 계속 보였고, 일부는 `SWEEP_CONFIRM` 또는 live 심볼 밖이었다.
- 기존에는 row를 하나씩 열어야 `strategy_family_not_live_route`, `entry_model_not_live_route`, `symbol_not_live_routable`를 알 수 있었다.
- 수정:
  - `route_mismatch_summary`를 entry surface snapshot/result top-level에 추가했다.
  - `CONTEXT_REVIEW_SETUP`과 `BLOCKED_SETUP` 중 live-routable이 아닌 row를 reason/family/entry_model/symbol/status별로 집계한다.
  - entry surface message에 `route_mismatch: context_only=N | reasons=... | families=... | entry_models=... | symbols=...` 라인을 추가했다.
  - `.env.example`의 “Current MICRO_LIVE shape”도 실제 runtime 계약에 맞춰 `session_impulse_retest`, `CONFIRM`, `dead_session,london,new_york`로 정렬했다.
  - docs에 `route_mismatch_summary` 읽는 법을 추가했다.

### 검증
- targeted:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py::test_build_entry_snapshot_maps_rows_to_three_statuses tests/test_entry_surface_scripts.py::test_render_message_includes_all_sections_and_reasons tests/test_entry_surface_scripts.py::test_context_only_surface_is_not_discord_alertable tests/test_entry_surface_scripts.py::test_main_dry_run_prints_snapshot_without_dispatch -q`
  - `4 passed`
- broader:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_entry_surface_scripts.py tests/test_notification_dispatcher.py tests/test_micro_live_operational_guards.py -q`
  - `117 passed`
- full regression:
  - `PYTHONPATH="$PWD" ./.venv/bin/pytest tests/test_api_smoke.py tests/test_portfolio_budget_report.py tests/test_notification_dispatcher.py tests/test_live_candidate_promotion_readiness.py tests/test_entry_surface_scripts.py tests/test_script_entrypoints.py tests/test_auto_trading_transition_phase1.py tests/test_session_impulse_retest_execution_path.py tests/test_micro_main_live_readiness.py tests/test_transition_variant_live_readiness.py tests/test_replay_validation_bridge.py tests/test_live_order_lifecycle.py tests/test_execution_operator_ui.py tests/test_execution_operator_dashboard.py tests/test_strategy_engine_ops.py tests/test_score_to_outcome_funnel.py tests/test_execution_quality.py tests/test_portfolio_overlay.py tests/test_plan_generator.py tests/test_historical_walk_forward_proof.py tests/test_stage_monitor_tick.py tests/test_micro_live_operational_guards.py tests/test_signal_alerts.py -q`
  - `436 passed`
- workspace dry-run:
  - `reason=no_alertable_rows`
  - `live_order_candidates=0`
  - `blocked_live_order_candidates=0`
  - `blocked_context_only_setups=3`
  - `route_mismatch_summary.context_only_total=5`
  - `by_strategy_family={legacy_zone_plan: 5}`
  - `by_reason={strategy_family_not_live_route: 5, entry_model_not_live_route: 3, symbol_not_live_routable: 3}`
- runtime 반영:
  - `TRADING_REFRESH_TMP_RUNTIME_SRC=1 ./scripts/restart_runtime_stack_tmp.sh`
  - `/health/ready`: ready
  - runtime_src의 `notify_entry_surface.py`가 workspace와 동일한지 diff로 확인했다.
  - entry surface launchd kickstart 후 runtime latest:
    - `reason=no_alertable_rows`
    - `notified=false`
    - `live_order_candidates=0`
    - `blocked_live_order_candidates=0`
    - `blocked_context_only_setups=3`
    - `route_mismatch_summary.context_only_total=5`
    - `by_strategy_family={legacy_zone_plan: 5}`
    - `by_entry_model={CONFIRM: 2, SWEEP_CONFIRM: 3}`
    - `by_symbol={DOGEUSDC: 1, NEARUSDC: 2, SUIUSDC: 2}`
  - runtime entry surface stdout/stderr logs: `0` bytes
  - runtime ops heartbeat:
    - `overall_status=PASS`
    - hard `0`, warning `0`
    - `entry_surface.status_detail=no_alertable_rows`

## 2026-05-15 Iteration #210
### 검증: MICRO_LIVE 안전장치 작동성과 백테스트 수익률 drag 수치화
- 추가:
  - `scripts/run_micro_live_safety_drag_audit.py`
  - `tests/test_micro_live_safety_drag_audit.py`
- 목적:
  - 기존 `session_impulse_retest` USDT proxy 백테스트 trade list에 현재 `.env` MICRO_LIVE 계약과 재현 가능한 safety gate를 순서대로 적용한다.
  - live 계약 필터와 운영 안전장치가 백테스트 진입 수/총 R/EV를 얼마나 줄이는지 분리한다.
- 기준 리포트:
  - `reports/validation/micro_main_usdt_proxy_backtests/micro_main_usdt_proxy_backtest_20260515T175711Z.json`
- 산출 리포트:
  - `reports/validation/micro_live_safety_drag_audits/micro_live_safety_drag_audit_20260515T180801Z.md`
- 결과:
  - baseline: `closed=4399`, `total_r=2826.3175`, `ev_r=0.6425`
  - contract filters only: `closed=4399`, `total_r=2826.3175`, `ev_r=0.6425`
  - replayable safety gates: `closed=3261`, `total_r=2036.5773`, `ev_r=0.6245`
  - replayable safety gates + Saturday risk multiplier: `closed=3261`, `total_r=1980.8518`, `ev_r=0.6074`
  - safety drag: `closed -1138` (`-25.8695%`), `total_r -789.7402` (`-27.9424%`), `ev_r -0.0180`
  - risk-multiplier까지 포함한 drag: `total_r -845.4657` (`-29.9140%`), `ev_r -0.0351`
  - 차단 reason: `live_family_cluster_window_cap_reached=1059`, `live_family_loss_cooldown_active=79`
- waterfall:
  - position cap only: `closed -269`, `total_r -206.0708`
  - + daily cap: 추가 drag 없음 (`AUTO_TRADING_MICRO_LIVE_MAX_DAILY_NEW_ENTRIES=0`)
  - + family cluster window: 추가 `closed -812`, `total_r -543.7666`
  - + same-direction exposure: 추가 drag 없음, 현재 family cluster가 더 엄격함
  - + loss cooldown: 추가 `closed -57`, `total_r -39.9028`
- 현재 runtime 확인:
  - `/health/ready`: `ready`
  - `/execution/safety-state?symbol=BTCUSDC`: `new_entry_allowed=true`, kill/close-only 모두 false
  - `run_replay_validation_bridge.py --all-live-symbols`: `overall_status=PASS`, 11개 live symbol 모두 `ELIGIBLE_FOR_RUNTIME_VALIDATION_BRIDGE`
  - `run_micro_live_synthetic_canary.py --symbol BTCUSDC --entry-model CONFIRM`: `overall_status=PASS`, `no_live_order_sent=true`, liquidity gate `PASS`
  - `run_micro_live_preflight.py`: safety/config/blackout/liquidity checks는 PASS지만 cached validation payload 부재로 `validation_language/checklist_language=FAIL`, overall `NOT_READY`
- 주의:
  - liquidity depth/spread/slippage drag는 과거 orderbook snapshot이 백테스트 artifact에 없어서 historical drag로 정확히 계산하지 않았다.
  - 현재 snapshot canary는 통과했지만, liquidity gate drag는 live 제출 시점의 snapshot으로 계속 축적해야 한다.

### 검증 명령
- `./.venv/bin/python scripts/run_micro_live_safety_drag_audit.py --backtest-report reports/validation/micro_main_usdt_proxy_backtests/micro_main_usdt_proxy_backtest_20260515T175711Z.json --include-samples`
- `./.venv/bin/python scripts/run_micro_live_synthetic_canary.py --symbol BTCUSDC --entry-model CONFIRM --direction long --stop-bps 50 --no-fail-exit`
- `./.venv/bin/python scripts/run_replay_validation_bridge.py --all-live-symbols --no-write-report --no-fail-exit`
- `./.venv/bin/pytest tests/test_micro_live_safety_drag_audit.py tests/test_session_impulse_retest_execution_path.py::test_session_impulse_retest_live_readiness_without_blockers_can_approve tests/test_session_impulse_retest_execution_path.py::test_session_impulse_retest_live_bootstrap_advisory_sample_gap_can_submit tests/test_session_impulse_retest_execution_path.py::test_session_impulse_retest_secondary_symbol_stays_shadow_even_if_allowlisted tests/test_session_impulse_retest_execution_path.py::test_live_cluster_guard_ignores_missing_opened_ts_for_recent_window tests/test_session_impulse_retest_execution_path.py::test_live_cluster_guard_ignores_malformed_loss_exit_ts tests/test_session_impulse_retest_execution_path.py::test_live_cluster_guard_tolerates_malformed_window_settings tests/test_micro_live_preflight.py::test_micro_live_config_drift_checks_flag_missing_direction_contract_symbol tests/test_micro_live_preflight.py::test_event_blackout_coverage_check_blocks_missing_live_symbols tests/test_micro_live_preflight.py::test_event_blackout_freshness_check_blocks_expired_contract tests/test_micro_live_operational_guards.py::test_synthetic_canary_passes_with_no_network_and_valid_settings`
  - `13 passed`
- legacy `LIMIT` liquidity tests:
  - current `.env`는 `AUTO_TRADING_MICRO_LIVE_ALLOWED_ENTRY_MODELS=CONFIRM`라서 기존 `LIMIT` fixture는 그대로 돌리면 contract mismatch로 실패한다.
  - 기계적 liquidity/sizing 회귀 확인은 `AUTO_TRADING_MICRO_LIVE_ALLOWED_ENTRY_MODELS=LIMIT,CONFIRM` override로 실행했다.
  - `6 passed`
