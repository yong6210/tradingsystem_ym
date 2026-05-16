# Auto Trading Live Go-Live 체크리스트

최종 갱신: 2026-05-16

## 1. 범위
- 이 문서는 `SHADOW -> PAPER -> MICRO_LIVE -> LIVE` 전환 전 점검 항목을 고정한다.
- 기본 원칙: `MICRO_LIVE` 전환 전까지는 신규 진입보다 `approval / intent / reconcile / safety`의 안정성이 먼저다.

## 2. 공통 전제
- `chart score != deployment approval`
- `chart plan != live order instruction`
- source-of-truth:
  - runtime operator 상태: `GET /execution/operator-dashboard`
  - 브라우저 operator 표면: `GET /execution/operator-ui`
  - 최종 승인: `POST /validation/report`, `POST /operations/checklist`
  - safety/lock 상태: `GET /execution/safety-state`

## 3. 환경 점검
- [ ] `.env`가 [.env.example](/Users/yumin/Documents/trading/.env.example)의 보수적 기준선을 따른다. 실제 주문은 `BINANCE_TRADE_LIVE_ENABLED=true`, `AUTO_TRADING_ENABLED=true`, 승인/intent/submit 조건이 모두 맞을 때만 열린다.
- [ ] `BINANCE_API_KEY`, `BINANCE_API_SECRET` 설정 완료
- [ ] `BINANCE_TRADE_LIVE_ENABLED` 의도한 값으로 설정 완료
- [ ] `pip install -e '.[integration]'`로 user-stream 의존성 설치 완료
- [ ] Discord/Telegram/Push 중 최소 1개 alert channel 동작 확인
- [ ] 서버 시간/UTC 저장 규칙 확인
- [ ] DB 백업/복구 절차 확인
- [ ] 테스트는 항상 temp DB로만 돌고, `pytest`가 실 [trading.db](/Users/yumin/Documents/trading/trading.db)를 건드리지 않음 (`tests/conftest.py`, `DATABASE_URL` 격리 확인)

## 4. SHADOW 진입 기준
- [ ] `GET /execution/operator-dashboard`에서 `new_entries_allowed` 계산이 정상
- [ ] `GET /execution/operator-ui`에서 dashboard/checklist/validation 요약이 동시에 표시됨
- [ ] `POST /execution/approve-plan`가 plan별로 결정적 결과를 반환
- [ ] `POST /execution/order-intents`가 `SUBMIT / SKIP_*`를 일관되게 기록
- [ ] duplicate thesis, stale plan, manual/shadow/blocked 경로 테스트 완료
- [ ] `GET /alerts/metrics`에서 validation alert 경로 정상

SHADOW exit criteria:
- [ ] blocked reason logging이 충분히 쌓임
- [ ] intent decision이 runtime state와 충돌하지 않음
- [ ] approval/intent replay debugging이 가능함

## 5. PAPER 진입 기준
- [ ] paper adapter에서 `partial fill / timeout / cancel` 테스트 통과
- [ ] `POST /execution/submit`가 paper submit 경로에서만 동작
- [ ] order lifecycle과 position lifecycle이 함께 추적됨
- [ ] `ENTRY -> PARTIAL_EXIT -> CLOSED`와 order ack/fill/cancel 경로 회귀 통과
- [ ] restart 이후 state restore / idempotent submit 확인

PAPER exit criteria:
- [ ] state machine 오류 없음
- [ ] stop/tp attach 실패가 경고/lock 경로로 잡힘
- [ ] paper/live-like drift가 허용 범위 내
- [ ] 최근 reconciliation mismatch가 낮음

## 6. MICRO_LIVE 진입 기준
- [ ] 현재 기준 문서 [MICRO_LIVE Current State](/Users/yumin/Documents/trading/docs/MICRO_LIVE_CURRENT_STATE.md)를 확인함
- [ ] live family는 `session_impulse_retest`
- [ ] live entry model은 `CONFIRM`
- [ ] live symbols는 `BTCUSDC,ETHUSDC,SOLUSDC,LINKUSDC,BNBUSDC,XRPUSDC,ADAUSDC,AVAXUSDC,BCHUSDC,LTCUSDC,NEARUSDC`
- [ ] 방향 계약은 모든 live symbol에 `LONG|SHORT`
- [ ] live sessions는 `dead_session,london,new_york`
- [ ] legacy `BTCUSDC + sweep_reversal + LIMIT`는 benchmark/context lens이고 현재 live route가 아님을 이해함
- [ ] tuned pacing은 `max_concurrent_positions=3`, `family_cluster_window=30m`, `max_same_family_entries=3`, `max_same_family_direction_exposures=3`, `loss_cooldown=60m/4 losses`, `saturday_risk_multiplier=1.0`
- [ ] `AUTO_TRADING_MICRO_LIVE_MAX_DAILY_NEW_ENTRIES=0`은 일일 상한이 꺼진 상태이며, 무제한 진입이 아니라 position cap / approval / safety / reconciliation 재평가를 계속 거친다는 뜻임을 이해함
- [ ] `GET /execution/safety-state`에서 `kill_switch_active == false`
- [ ] `GET /execution/safety-state`에서 `close_only_active == false`
- [ ] `POST /validation/report` 결과가 최소 `MANUAL_REVIEW` 이상이고, 운영자가 승인함
- [ ] `POST /operations/checklist` 결과가 신규 진입 가능 상태를 가리킴
- [ ] `GET /execution/operator-dashboard`에서 `recent_reconciliation_summary.healthy == true`
- [ ] `runtime_decision_band == AMBER_CONDITIONAL`
- [ ] `runtime_effective_action == conditional_micro_live_signoff`
- [ ] `runtime_allowed_reopen_scope == MICRO_LIVE_ONLY`
- [ ] `runtime_preflight_summary.status == READY_FOR_MICRO_LIVE`
- [ ] `runtime_operator_signoff_summary.status == ready_for_manual_micro_live_signoff`
- [ ] 후보가 `auto_trading_micro_live_allowed_symbols`, `auto_trading_micro_live_allowed_families`, `auto_trading_micro_live_allowed_entry_models`, `auto_trading_micro_live_allowed_sessions`, direction contract 안에 있음
- [ ] `.env`와 runtime `.env`의 MICRO_LIVE 계약이 `.env.example` 및 [MICRO_LIVE Current State](/Users/yumin/Documents/trading/docs/MICRO_LIVE_CURRENT_STATE.md)와 일치함
- [ ] `AUTO_TRADING_LIVE_LIQUIDITY_GATE_ENABLED=true`와 `AUTO_TRADING_LIVE_LIQUIDITY_GATE_FAIL_CLOSED=true`
- [ ] `runtime_self_heal_summary`에 반복 stale cleanup / stale unblock 이상 징후가 없음
- [ ] 운영 순서를 `preflight -> runtime guard -> synthetic canary -> signoff review -> order-intents(MICRO_LIVE) -> submit(live=true)`로만 따른다
- [ ] `run_micro_live_safety_drag_audit.py`가 현재 `.env` 기준으로 baseline 대비 drag를 수치화함
- [ ] `run_micro_live_safety_grid_search.py`의 `recommended`가 현재 `.env` pacing과 일치하거나, 차이가 있으면 그 이유를 기록함
- [ ] safety를 끈 raw top diagnostic을 live 설정으로 착각하지 않음
- [ ] live blocker가 있으면 `live_family_cluster_window_cap_reached`, `live_family_loss_cooldown_active`, `micro_live_position_cap_reached`를 분리해 해석함
- [ ] major macro blackout (`FOMC`, `CPI`, `NFP`) 일정이 현재 분기 기준으로 반영돼 있고, blackout 동안 신규 `MICRO_LIVE` 진입이 막히는 구조를 이해함
- [ ] blackout horizon이 부족하면 `scripts/build_micro_live_event_blackouts.py`로 계약 파일을 재생성하고 `AUTO_TRADING_MICRO_LIVE_EVENT_BLACKOUT_PATH`를 새 출력 파일에 맞춘 뒤 preflight/runtime guard를 다시 통과함
- [ ] `scripts/run_micro_live_runtime_guard.py --days 30`가 blocking failure 없이 통과함
- [ ] `scripts/run_micro_live_synthetic_canary.py --no-network`가 sizing/liquidity submit dry-run 경로를 통과함
- [ ] `scripts/run_live_order_lifecycle_report.py --days 30`에서 rejected/error 또는 submitted-without-entry-fill 이상을 검토함
- [ ] live intent가 있는데 제출이 없는 구간은 `scripts/run_micro_live_no_order_watchdog.py --days 3 --no-fail-exit`로 별도 확인하고, `validation_block_detail.primary_cause`가 sample/EV/win-rate/score/risk/session 중 무엇인지 분리함
- [ ] stale live submission, ledger mismatch, user-stream stale은 `scripts/run_live_reconciliation_watchdog.py --days 3 --no-fail-exit`로 별도 확인함
- [ ] worker 재시작 전에는 `scripts/run_micro_live_boot_check.py --days 3 --limit 200 --no-fail-exit`를 통과시킴
- [ ] `AUTO_TRADING_EXECUTION_MODE=MICRO_LIVE/LIVE`에서 `run_worker.py`가 boot check 실패 시 시작하지 않는 구조를 유지함
- [ ] `scripts/run_live_replay_parity_audit.py --all-live-symbols --days 3 --no-fail-exit`에서 active `parity_scope`가 현재 runtime인지 확인하고, 개별 심볼 ALERT/WATCH와 `flow_diagnosis.stage`, `order_flow_status`, `lookback_evaluation_summary`를 분리해 확인함
- [ ] `scripts/run_replay_validation_bridge.py --all-live-symbols --no-fail-exit`로 replay-backed validation bridge 후보를 audit-only로 확인함. `ev_r_lower_95`와 material slice warnings를 같이 확인하며, slice warning은 clean pass로 보지 않음. 이 결과만으로 live gate를 자동 개방하지 않음
- [ ] `scripts/run_micro_live_ops_heartbeat.py --no-fail-exit`가 scheduled guard report freshness와 최신 리포트 내부 상태 확인을 통과함. hard failure는 즉시 조치하고, `WATCH`는 no-order/replay bridge 등 운영상 확인이 필요한 상태로 분리함
- [ ] `scripts/run_micro_live_failure_drill.py --no-fail-exit`가 failure-contract drill을 통과하고, heartbeat의 `failure_drill` job도 `PASS`로 표시됨
- [ ] launchd macro calendar refresh가 `AUTO_TRADING_MICRO_LIVE_EVENT_BLACKOUT_PATH`에 지정된 live blackout 계약 파일을 갱신하도록 생성됐는지 확인함

MICRO_LIVE exit criteria:
- [ ] fee/slippage 포함 후 기대치 유지
- [ ] fill quality와 time failure 비율이 허용 범위 내
- [ ] critical incident 없음
- [ ] close-only / kill-switch / lock 동작 실전 검증 완료

## 7. LIVE 확대 기준
- [ ] family별 recent quality score가 안정적
- [ ] reconciliation mismatch가 누적되지 않음
- [ ] user-stream stale / missing stop / fill gap 사고가 해결됨
- [ ] threshold lineage / replay-backed approval 기준이 운영상 충분히 해석 가능
- [ ] operator runbook이 실제 운영 과정과 어긋나지 않음
- [ ] `runtime_decision_band == AMBER_CONDITIONAL` 또는 `GREEN_PROCEED`
- [ ] `runtime_effective_action == conditional_full_live_signoff` 또는 `proceed_to_operator_signoff`
- [ ] `runtime_allowed_reopen_scope == MICRO_LIVE_OR_LIVE`
- [ ] `runtime_preflight_summary.status == READY_FOR_MICRO_LIVE`
- [ ] `runtime_operator_signoff_summary.status == ready_for_manual_full_live_signoff` 또는 `ready_for_operator_signoff`
- [ ] `live_eligible_post_patch_closed_trade_count >= 30`
- [ ] `live_eligible_post_patch_sample_summary.replay_max_drawdown_r < 4.5`
- [ ] `live_eligible_post_patch_sample_summary.replay_p5_r >= -1.05`
- [ ] `live_eligible_post_patch_sample_summary.stop_loss_share < 0.40`
- [ ] `live_eligible_post_patch_sample_summary.worst_loss_streak < 5`
- [ ] `live_execution_post_patch_closed_trade_count >= 5`여서 더 이상 bootstrap proof가 아님
- [ ] `trend_proof_post_patch_closed_trade_count >= 5` 또는 추세장 proof 부재를 운영자가 명시적으로 받아들임
- [ ] `live_family_cluster_window_cap_reached` blocker 없음
- [ ] `live_family_loss_cooldown_active` blocker 없음
- [ ] PAPER lineage drill의 `family_cluster_guard_summary.active_families`가 비어 있음

## 8. 즉시 NO-GO 조건
- [ ] `validation/report`가 `NO_GO`
- [ ] `operations/checklist`가 신규 진입 차단 상태
- [ ] `GET /execution/safety-state`에 active global kill-switch 존재
- [ ] unresolved reconciliation critical mismatch 존재
- [ ] missing stop order on live position
- [ ] repeated user-stream stale
- [ ] exchange auth/order API degraded
- [ ] slippage anomaly / fee anomaly

## 9. 첫 라이브 세션 전 명령 순서
```bash
curl -s "http://127.0.0.1:8000/health/ready" | jq
curl -s "http://127.0.0.1:8000/execution/operator-dashboard?universe=usdc_perp_top30&days=7" | jq
curl -s "http://127.0.0.1:8000/execution/safety-state" | jq
curl -s -X POST "http://127.0.0.1:8000/validation/report?symbol=BTCUSDC" | jq
curl -s -X POST "http://127.0.0.1:8000/operations/checklist?symbol=BTCUSDC" | jq
curl -s "http://127.0.0.1:8000/alerts/metrics?days=7&write_report=false" | jq
```

자동 점검 스크립트:
```bash
./.venv/bin/python scripts/run_micro_live_preflight.py --symbol BTCUSDC --days 7
./.venv/bin/python scripts/run_micro_live_runtime_guard.py --days 30
./.venv/bin/python scripts/run_micro_live_synthetic_canary.py --no-network
./.venv/bin/python scripts/run_live_order_lifecycle_report.py --days 30
./.venv/bin/python scripts/run_micro_live_no_order_watchdog.py --days 3 --no-fail-exit
./.venv/bin/python scripts/run_live_reconciliation_watchdog.py --days 3 --no-fail-exit
./.venv/bin/python scripts/run_micro_live_boot_check.py --days 3 --limit 200 --no-fail-exit
./.venv/bin/python scripts/run_micro_live_safety_drag_audit.py --backtest-report reports/validation/micro_main_usdt_proxy_backtests/micro_main_usdt_proxy_backtest_20260515T175711Z.json --no-write-report
./.venv/bin/python scripts/run_micro_live_safety_grid_search.py --backtest-report reports/validation/micro_main_usdt_proxy_backtests/micro_main_usdt_proxy_backtest_20260515T175711Z.json --no-write-report
```

## 10. 운영 원칙
- live 전환은 기능 완성 여부가 아니라 `reconciliation / safety / operator visibility`가 충분한지로 판단한다.
- `MICRO_LIVE`는 검증 단계다. 수익 극대화 모드가 아니다.
- 현재 live 계약은 `session_impulse_retest + CONFIRM + 11개 core USDC symbols`다.
- `BTCUSDC + sweep_reversal + LIMIT`는 benchmark/legacy lens이며 live allowlist로 쓰지 않는다.
- `legacy` 전체 replay와 full `post-patch` cohort는 advisory truth로 유지한다. 실제 live go/no-go는 현재 live route와 safety/grid audit을 기준으로 분리해서 본다.
- safety를 끈 raw top diagnostic은 “무엇을 깎고 있는지”를 보기 위한 비교값이지 운영 설정이 아니다.
- `FULL LIVE` 확대는 `MICRO_LIVE` live fills/closes, reconciliation, slippage, forced exit, runtime parity가 따로 충분해진 뒤에만 검토한다.
- unresolved mismatch가 있으면 “조금 더 지켜본다”가 아니라 즉시 `close-only` 또는 `kill-switch`를 고려한다.
