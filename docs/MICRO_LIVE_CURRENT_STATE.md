# MICRO_LIVE Current State

Last updated: 2026-05-16 KST

This is the concise operator source for the current live canary shape. Detailed history stays in [SELF_CHECK_LOG.md](/Users/yumin/Documents/trading/docs/SELF_CHECK_LOG.md); daily procedures stay in [AUTO_TRADING_OPERATING_RUNBOOK.md](/Users/yumin/Documents/trading/docs/AUTO_TRADING_OPERATING_RUNBOOK.md).

## Live Route

- execution mode: `MICRO_LIVE`
- strategy family: `session_impulse_retest`
- entry model: `CONFIRM`
- symbols: `BTCUSDC`, `ETHUSDC`, `SOLUSDC`, `LINKUSDC`, `BNBUSDC`, `XRPUSDC`, `ADAUSDC`, `AVAXUSDC`, `BCHUSDC`, `LTCUSDC`, `NEARUSDC`
- directions: `LONG|SHORT` for every live symbol in the direction contract
- sessions: `dead_session`, `london`, `new_york`
- benchmark-only legacy lens: `BTCUSDC + sweep_reversal + LIMIT`
- context-only rows: legacy `SWEEP_CONFIRM`/`LIMIT` sweep rows, non-live symbols, and non-live families unless the contract is explicitly changed

## Tuned Pacing

- `AUTO_TRADING_MICRO_LIVE_MAX_CONCURRENT_POSITIONS=3`
- `AUTO_TRADING_MICRO_LIVE_MAX_DAILY_NEW_ENTRIES=0`
- `AUTO_TRADING_LIVE_FAMILY_CLUSTER_WINDOW_MINUTES=30`
- `AUTO_TRADING_LIVE_MAX_SAME_FAMILY_ENTRIES_PER_WINDOW=3`
- `AUTO_TRADING_LIVE_MAX_SAME_FAMILY_DIRECTION_EXPOSURES=3`
- `AUTO_TRADING_LIVE_RECENT_LOSS_COOLDOWN_MINUTES=60`
- `AUTO_TRADING_LIVE_RECENT_LOSS_TRIGGER_COUNT=4`
- `SESSION_IMPULSE_RETEST_SATURDAY_RISK_MULTIPLIER=1.0`

`MAX_DAILY_NEW_ENTRIES=0` means the daily cap is disabled. It does not mean unlimited entry: position cap, validation, operations checklist, kill/close-only switches, liquidity, macro blackout, exchange rules, sizing, and reconciliation still gate every submit.

## Backtest Alignment

Baseline report:

- `reports/validation/micro_main_usdt_proxy_backtests/micro_main_usdt_proxy_backtest_20260515T175711Z.json`

Current safety/grid result:

- report: `reports/validation/micro_live_safety_drag_audits/micro_live_safety_grid_search_20260515T183913Z.md`
- evaluated cases: `7,683`
- deployable filter: `1 <= max_pos <= 3`, cluster brake active, same-direction brake active, loss cooldown active
- baseline: `closed=4399`, `total_r=2826.3175`, `ev_r=0.6425`, `win_rate=0.6574`
- current/recommended: `closed=4323`, `total_r=2754.7242`, `ev=0.6372`, `win=0.6563`
- drag vs baseline: `closed -76` (`-1.7277%`), `total_r -71.5933` (`-2.5331%`)

The raw top diagnostic can match the baseline by disabling safety/unlimited exposure. That is not a live canary setting.

Runtime guard must also show `micro_live_backtest_contract_alignment=PASS`. This check compares the current MICRO_LIVE allowlist, family, entry model, sessions, and long/short direction contract against the current SIR backtest source above. If this fails, the system has drifted away from the backtest contract even if the ordinary allowlist checks pass.

Runtime restarts sync the regular `micro_main_usdt_proxy_backtest_*.json` baseline files from workspace reports into durable runtime reports. Runtime replay surfaces and compare-only research searches choose the latest report that matches the current MICRO_LIVE symbol contract, not simply the newest filename or copy/mtime. `unseen`, `top*`, and broader experiment reports do not replace the 11-symbol live contract baseline unless the live contract is explicitly changed.

## Current No-Order Interpretation

As of 2026-05-16 18:25 KST, runtime health and live route settings are aligned, but there have been no fresh `session_impulse_retest + CONFIRM` live candidates since the latest observed runtime restart at `2026-05-16 18:23:20 KST` (`2026-05-16T09:23:20Z`).

Latest runtime check after the backtest-contract guard, watchdog cleanup, replay baseline source-order cleanup, and preflight advisory-checklist cleanup:

- `/health/ready`: `ready`
- `run_micro_live_runtime_guard.py`: `PASS`, `micro_live_backtest_contract_alignment=PASS`, live intents `0`, submissions `0`
- `run_micro_live_preflight.py`: `READY_FOR_MICRO_LIVE`; validation `approval usable`, checklist advisory warnings only (`blocking_failures=0`, `manual_actions=0`)
- `check_runtime_stack.sh`: `WAIT/no_fresh_live_signal`, runtime 이후 expected/missed SIR trades `0/0`
- `run_micro_live_no_order_watchdog.py`: `OK/INFO`, `reason=sir_pre_restart_expected_orders_advisory`, current runtime expected orders `0`, 7-day lookback expected orders `12`, all pre-restart
- `run_live_replay_parity_audit.py`: `PASS`, current runtime window below evidence floor, `lookback_advisory=true`, replay source `micro_main_usdt_proxy_backtest_20260515T175711Z.json`
- `run_micro_live_ops_heartbeat.py`: `PASS`, warnings `0`, failures `0`; historical/lookback flow differences are retained as non-paging advisories
- `live_candidate_promotion_readiness`: `WAIT`, `reason=no_promotable_live_candidate`, live core symbols `11` all `NO_FRESH_LIVE_CANDIDATE`
- `live_candidate_promotion_readiness` now has a scheduled runtime report and ops-heartbeat freshness check; stale order-truth reports should show up as heartbeat issues instead of silently remaining old.
- `live_candidate_promotion_readiness` scope counts and blocker counts are computed from the full candidate set, not just the displayed `--limit` rows. `candidate_count=14` with displayed candidates `12` should still show `top_live_blockers.no_fresh_live_candidate=11`.
- `live_candidate_promotion_readiness` also treats live-contract symbols missing from the latest runtime candidate rows as `NO_FRESH_LIVE_CANDIDATE`, so the live scope should remain 11 symbols even when only a subset emitted recent audit rows.
- `run_micro_live_ops_heartbeat.py` now treats runtime-scoped reports generated before the current WS `started_at` as `WATCH/report_before_current_runtime_start`, even if the file mtime is fresh. The restart script refreshes those reports automatically before treating the heartbeat as current.
- `restart_runtime_stack_tmp.sh` now performs that refresh automatically after `/health/ready`: runtime guard, short no-order watchdog refresh, live candidate readiness, live replay parity, SIR runtime audit, entry surface, boot check, then ops heartbeat. If `report_before_current_runtime_start` remains after a scripted restart, inspect `~/Library/Application Support/trading/logs/post_restart_report_refresh.log`.
- `restart_runtime_stack_tmp.sh` now holds a single-run lock under `~/Library/Application Support/trading/locks/restart_runtime_stack_tmp.lock`, so manual and watchdog restarts cannot overlap and interleave source refresh/process kill/report refresh.
- Legacy `restart_runtime_stack.sh` is only a compatibility wrapper now. It delegates to `restart_runtime_stack_tmp.sh`, so it cannot bypass the durable runtime lock, source refresh, heartbeat path, or post-restart report refresh.
- loop worker startup now distinguishes `starting` from active first-sync work. During long first universe sync, heartbeat phase should move to `syncing_universe` so readiness does not look like a dead startup.
- runtime-stack watchdog treats market-data-only degraded checks during `starting`/`syncing_universe` as `market_data_warmup_grace` instead of immediately accumulating restart failures.
- `/health/ready` market-data freshness uses a live-symbol quorum, not BTC-only freshness. Current details should look like `ok:1m:fresh=N/12...`; individual stale symbols are informational unless the quorum falls below 3 fresh probe symbols.
- operator session brief launchd now runs from runtime authority (`runtime_venv` + `runtime_src`) and writes runtime artifacts; current runtime brief should read `ALIGNED_MONITOR`, not `DEPLOYMENT_REVIEW_REQUIRED`, when validation is `GO` and checklist manual review is advisory-only.
- auxiliary SIR signals exist on `SUIUSDC`, `AAVEUSDC`, `HBARUSDC`, but these are shadow-only and not part of the 11-symbol baseline contract
- validation payload cache TTL is 6 hours, so read-only preflight does not flip back to `validation unavailable` every 15 minutes when no validation refresh job is scheduled.

Recent no-order reports must be read in two layers:

- current runtime window: `live_intents=0`, `submit_ready=0`, `submissions=0`; this means there is no current submit failure yet.
- pre-restart lookback: valid backtest-condition candidates existed before the restart, but old gates skipped them. In the 7-day audit this was `12` expected SIR orders, with top reasons `session_impulse_retest_rollout_not_ready`, `rollout_session_not_allowed`, and `validation_do_not_deploy`.

The no-order watchdog now keeps this as `sir_pre_restart_expected_orders_advisory` instead of reporting a clean fresh-candidate wait. Because this is historical/pre-restart context rather than a current submit failure, it is `OK/INFO` with `historical_advisory=true`, not a paging `WATCH`. The live replay parity report also keeps lookback flow warnings visible with `lookback_advisory=true` when the current runtime window is thin but lookback flow shows missed/blocked opportunities. In that thin fresh-runtime case, parity keeps the current headline `PASS` and the lookback warning stays in `lookback_evaluation_summary`.

The ops heartbeat reads those flags as advisories. They appear in `advisory_count` and the report's `참고` line, while `overall_status` remains `PASS` and Discord does not page the operator.

Operator rule:

- If the report says `sir_pre_restart_expected_orders_advisory`, the issue is historical missed opportunity context, not a current exchange submit error.
- If a fresh candidate appears and `submit_ready > 0` but `submissions=0`, treat that as an active intent-to-submission bug.
- If `Trading entry surface alert` shows `live_order_candidates=0` with `context_only_outside_live_route`, that is not an entry confirmation. It only says non-live-route context rows are active.
- If a no-order watchdog notification is `WATCH` only, the Discord title should be `[모니터링] MICRO_LIVE 주문 흐름 관찰`, not `[운영] ... 확인 필요`.
- If a `confirm` subscription alert appears, read it as `signal-only no-order` unless it is accompanied by `LIVE_ORDER_CANDIDATE`, an order intent, submission, or fill. The Discord title should be `[모니터링] ... 주문 전 관찰 알림(주문 아님)`.
- If an operator session brief says `ALIGNED_MONITOR`, validation/checklist are not currently hard-blocking orders. `manual_review` in the kernel means operator attention/context-only monitoring unless paired with validation `NO_GO`, checklist blocking failures, or a live-order blocker.

## Required Checks

Use these before treating the route as ready:

```bash
./.venv/bin/python scripts/run_micro_live_runtime_guard.py --days 30 --no-fail-exit
./.venv/bin/python scripts/run_micro_live_synthetic_canary.py --symbol BTCUSDC --entry-model CONFIRM --direction long --stop-bps 50 --no-fail-exit
./.venv/bin/python scripts/run_micro_live_safety_drag_audit.py --backtest-report reports/validation/micro_main_usdt_proxy_backtests/micro_main_usdt_proxy_backtest_20260515T175711Z.json --no-write-report
./.venv/bin/python scripts/run_micro_live_safety_grid_search.py --backtest-report reports/validation/micro_main_usdt_proxy_backtests/micro_main_usdt_proxy_backtest_20260515T175711Z.json --no-write-report
```

## Known Limits

- Historical liquidity gate drag is not exact without historical order book snapshots.
- Backtest alignment does not guarantee live PnL; live fills, slippage, rejects, latency, and forced exits remain separate truth.
- `Trading entry surface alert` is not by itself an order trigger. Live submit requires the current live route plus validation/operations/safety/liquidity approval.
