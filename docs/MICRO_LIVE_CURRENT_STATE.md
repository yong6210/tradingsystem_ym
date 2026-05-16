# MICRO_LIVE Current State

Last updated: 2026-05-17 03:29 KST

This is the concise operator source for the current live canary shape. Whole-system snapshot stays in [CURRENT_SYSTEM_STATE.md](/Users/yumin/Documents/trading/docs/CURRENT_SYSTEM_STATE.md); detailed history stays in [SELF_CHECK_LOG.md](/Users/yumin/Documents/trading/docs/SELF_CHECK_LOG.md); daily procedures stay in [AUTO_TRADING_OPERATING_RUNBOOK.md](/Users/yumin/Documents/trading/docs/AUTO_TRADING_OPERATING_RUNBOOK.md).

## Live Route

- execution mode: `MICRO_LIVE`
- strategy family: `session_impulse_retest`
- entry model: `CONFIRM`
- symbols: `BTCUSDC`, `ETHUSDC`, `SOLUSDC`, `LINKUSDC`, `BNBUSDC`, `XRPUSDC`, `ADAUSDC`, `AVAXUSDC`, `BCHUSDC`, `LTCUSDC`, `NEARUSDC`, `1000PEPEUSDC`, `ARBUSDC`, `1000SHIBUSDC`, `FILUSDC`, `DOGEUSDC`
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

Live risk sizing now uses Binance futures available balance when `AUTO_TRADING_LIVE_BALANCE_SYNC_ENABLED=true`, preferring `USDC` then `USDT`. `AUTO_TRADING_LIVE_ACCOUNT_EQUITY_USDT` remains the fallback/reference value, not the primary sizing source while balance sync is enabled.

## Backtest Alignment

Baseline report:

- `reports/validation/micro_main_usdt_proxy_backtests/micro_main_usdt_proxy_backtest_20260516T160212Z.json`
- frequency: `closed=8828` over `1825` days, or `4.837` closed trades/day across the current 16-symbol live contract

Current safety/grid result:

- report: `reports/validation/micro_live_safety_drag_audits/micro_live_safety_grid_search_20260516T162903Z.md`
- evaluated cases: `7,683`
- deployable filter: `1 <= max_pos <= 3`, cluster brake active, same-direction brake active, loss cooldown active
- baseline: `closed=8828`, `total_r=6343.8982`, `ev_r=0.7186`, `win_rate=0.6764`
- current/recommended: `closed=8508`, `total_r=6013.8505`, `ev=0.7068`, `win=0.6732`
- drag vs baseline: `closed -320` (`-3.6248%`), `total_r -330.0477` (`-5.2026%`)

The raw top diagnostic can match the baseline by disabling safety/unlimited exposure. That is not a live canary setting.

Latest safety drag spot audit:

- report: `reports/validation/micro_live_safety_drag_audits/micro_live_safety_drag_audit_20260516T162755Z.md`
- baseline: `closed=8828`, `total_r=6343.8982`, `ev_r=0.7186`
- after replayable safety gates: `closed=8508`, `total_r=6013.8505`, `ev_r=0.7068`
- replayable drag: `closed -320` (`-3.6248%`), `total_r -330.0477` (`-5.2026%`)
- removed reasons: `micro_live_position_cap_reached=302`, `live_family_loss_cooldown_active=18`

Runtime guard must also show `micro_live_backtest_contract_alignment=PASS`. This check compares the current MICRO_LIVE allowlist, family, entry model, sessions, and long/short direction contract against the current SIR backtest source above. If this fails, the system has drifted away from the backtest contract even if the ordinary allowlist checks pass.

Runtime restarts sync the regular `micro_main_usdt_proxy_backtest_*.json` baseline files from workspace reports into durable runtime reports. Runtime replay surfaces and compare-only research searches choose the latest report that matches the current MICRO_LIVE symbol contract, not simply the newest filename or copy/mtime. `unseen`, `top*`, and broader experiment reports do not replace the 16-symbol live contract baseline unless the live contract is explicitly changed.

## Current Runtime Snapshot

As of 2026-05-17 03:29 KST, the runtime is aligned to the 16-symbol MICRO_LIVE route. The system is not blocked by a symbol-list contradiction, stale validation cache, missing direction contract, WS universe mismatch, macro blackout coverage gap, stale canary report, boot-check failure, reconciliation failure, safety lock, open exchange position, or Binance trading-rule mismatch.

Latest runtime check after the 16-symbol expansion:

- `/health/ready`: `ready`; worker loop/ws ok; 1m and 5m market data fresh for `16/16` live symbols.
- `/execution/safety-state`: `new_entries_allowed=true`, kill switch off, close-only off.
- `/execution/operator-dashboard`: `GO`, `go_runtime_gate_open`, `order_route_approve_value=waiting_for_live_candidate`.
- `/internal/binance/positions?open_only=true`: `count=0`.
- `run_micro_live_runtime_guard.py`: `PASS`, blocking failures `0`.
- `run_micro_live_boot_check.py`: `PASS`, blocking failures `0`.
- `run_live_reconciliation_watchdog.py`: `OK`, reconciliation issues `0`.
- `run_micro_live_synthetic_canary.py`: `PASS`, `no_live_order_sent=true`, live sizing uses Binance futures available balance.
- `run_session_impulse_retest_runtime_audit_report.py`: `PASS`, no hard route failures.
- `run_micro_live_no_order_watchdog.py`: `OK/INFO`, only pre-restart advisory context.
- `run_micro_live_ops_heartbeat.py`: `WATCH`, hard failures `0`, warning `1`.
- `run_replay_validation_bridge.py`: `WATCH`, audit-only mixed bridge evidence; live approval unchanged.
- `micro_live_backtest_contract_alignment`: `PASS`, source `micro_main_usdt_proxy_backtest_20260516T160212Z.json`, expected symbols `16`.
- `live_symbol_allowlist_alignment`: `PASS`, missing from global allowlist `none`.
- `live_direction_contract_coverage`: `PASS`, contract symbols `16`, missing `none`.
- `ws_universe_contains_live_symbols`: `PASS`, WS symbols `16`, missing live symbols `none`.
- `session_impulse_retest_live_rollout_window`: `PASS`, core live slots `16`.
- `macro_blackout_live_coverage`: `PASS`.
- `binance_rule_drift`: `PASS`.
- `candidate_available`: `PASS/WAIT`, no fresh live-routable SIR candidate is available right now.

Heartbeat `WATCH` detail:

- `replay_validation_bridge` is `WATCH` because bridge evidence is mixed.
- `11` symbols are `ELIGIBLE_FOR_RUNTIME_VALIDATION_BRIDGE`.
- `5` symbols are `NOT_ELIGIBLE` only because `replay_validation_portfolio_replay_missing`: `1000PEPEUSDC`, `1000SHIBUSDC`, `ARBUSDC`, `DOGEUSDC`, `FILUSDC`.
- This is an audit-only warning and does not mean an attempted live order failed.

## Current No-Order Interpretation

Interpretation:

- No current order is not the same as an order error. The route is open, but there is no fresh live-routable `session_impulse_retest + CONFIRM` candidate at this moment.
- If a fresh candidate appears and `submit_ready > 0` but `submissions=0`, treat that as an active intent-to-submission bug.
- If there is no accepted live-routable candidate, the correct state is wait/monitor.
- `execution_quality_low_coverage` and low live closed-sample outcome controls are advisory during SIR MICRO_LIVE bootstrap. They may add `outcome_approval_penalty.status=watch`, but they must not downgrade an otherwise valid SIR live bootstrap candidate to `SKIP_MANUAL_ONLY` until a material live execution sample exists.
- For SIR replay/runtime parity, read `runtime_observed_count` together with `observed_submit_ready_intent_count`, `observed_non_submit_intent_count`, and `observed_non_submit_reason_counts`. An observed plan with only non-submit intents explains why no order was sent; it is not the same as a fresh submit-ready gap.
- For no-order reports, read `runtime_age_minutes` before judging a 3-day window. Current-runtime scope resets on WS restart. Also compare `live_intents.total` with `distinct_plan_count`, because repeated blocked/shadow checks for the same plan are not separate backtest opportunities.
- Auxiliary SIR signals on `SUIUSDC`, `AAVEUSDC`, `HBARUSDC`, `ZECUSDC`, and `UNIUSDC` are shadow-only and are not part of the 16-symbol baseline contract.
- The selected expansion did not make the live route 31 symbols because only 5 of the selected expansion names currently have tradable Binance USDC perpetuals in this route: `1000PEPEUSDC`, `ARBUSDC`, `1000SHIBUSDC`, `FILUSDC`, and `DOGEUSDC`.
- The selected names that are USDT-only require a separate USDT live-route change before they can be traded live by this system.

## Required Checks

Use these before treating the route as ready:

```bash
./.venv/bin/python scripts/run_micro_live_runtime_guard.py --days 30 --no-fail-exit
./.venv/bin/python scripts/run_micro_live_boot_check.py --days 3 --limit 200 --no-fail-exit
./.venv/bin/python scripts/run_micro_live_synthetic_canary.py --symbol BTCUSDC --entry-model CONFIRM --direction long --stop-bps 50 --no-fail-exit
./.venv/bin/python scripts/run_micro_live_safety_drag_audit.py --backtest-report reports/validation/micro_main_usdt_proxy_backtests/micro_main_usdt_proxy_backtest_20260516T160212Z.json --no-write-report
./.venv/bin/python scripts/run_micro_live_safety_grid_search.py --backtest-report reports/validation/micro_main_usdt_proxy_backtests/micro_main_usdt_proxy_backtest_20260516T160212Z.json --no-write-report
```

## Known Limits

- Historical liquidity gate drag is not exact without historical order book snapshots.
- Backtest alignment does not guarantee live PnL; live fills, slippage, rejects, latency, and forced exits remain separate truth.
- `Trading entry surface alert` is reserved for live candidates or blocked live-routable candidates. Zero-live context-only surfaces should be labeled `Trading entry surface monitor` and are not order triggers. Live submit requires the current live route plus validation/operations/safety/liquidity approval.
