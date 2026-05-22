# Current System State

Last updated: 2026-05-20 KST

This is the current operator snapshot for the whole repository/runtime. Detailed live-route parameters stay in [MICRO_LIVE_CURRENT_STATE.md](/Users/yumin/Documents/trading/docs/MICRO_LIVE_CURRENT_STATE.md); daily operating procedure stays in [AUTO_TRADING_OPERATING_RUNBOOK.md](/Users/yumin/Documents/trading/docs/AUTO_TRADING_OPERATING_RUNBOOK.md).

## Executive Summary

- Initial repository inspection: branch `main`; no tracked local changes were present before this documentation refresh.
- Runtime stack: running under launchd/watchdog with API, loop worker, and websocket worker active.
- API health: `/health/ready` is `ready`.
- Execution mode: `MICRO_LIVE`.
- Live route: `session_impulse_retest + CONFIRM` on the 11-symbol USDT long/short candidate route.
- Safety state: runtime close-only lock on; new entries blocked.
- Exchange exposure: no open Binance positions, no open runtime orders, no current live submissions after restart.
- Current order posture: MICRO_LIVE infrastructure is running, but new entries are intentionally paused while the backtest source-of-truth mismatch is resolved.
- Runtime guard: `FAIL` on `micro_live_backtest_contract_alignment`. The guard now prefers direct runtime USDT backtests over portfolio-mix advisory reports; the current live-exit direct report is 334 trades, EV `-0.1725R`.

## Runtime Stack

Active processes observed:

- `watch_runtime_stack_tmp.sh`
- `uvicorn app.main:app --host 127.0.0.1 --port 8000`
- `run_worker.py --mode loop --sync-universe ...`
- `run_worker.py --ws-stream --ws-intervals 1m,5m,15m --ws-symbols <11 live symbols>`

Active launchd labels observed:

- `com.yumin.trading.runtime-stack`
- `com.yumin.trading.entry-surface`
- `com.yumin.trading.operator-brief-shift-start`
- `com.yumin.trading.operator-brief-shift-end`

`/health/ready` currently reports:

- `db=true`
- `binance_rest=true`
- `event_backend=true`
- `worker_loop=true`
- `worker_ws=true`
- `market_data_1m=true`, fresh `11/11`
- `market_data_5m=true`, fresh `11/11`

## Live Contract

Current settings resolve to:

- `AUTO_TRADING_ENABLED=true`
- `AUTO_TRADING_EXECUTION_MODE=MICRO_LIVE`
- `BINANCE_TRADE_LIVE_ENABLED=true`
- `AUTO_TRADING_ALLOWED_FAMILIES=session_impulse_retest`
- `AUTO_TRADING_MICRO_LIVE_ALLOWED_ENTRY_MODELS=CONFIRM`
- `AUTO_TRADING_MICRO_LIVE_ALLOWED_SESSIONS=dead_session,london,new_york`
- `AUTO_TRADING_MICRO_LIVE_MAX_CONCURRENT_POSITIONS=2`
- `AUTO_TRADING_MICRO_LIVE_MAX_DAILY_NEW_ENTRIES=0`
- `AUTO_TRADING_LIVE_BALANCE_SYNC_ENABLED=true`
- `AUTO_TRADING_LIVE_LIQUIDITY_GATE_ENABLED=true`
- `AUTO_TRADING_LIVE_LIQUIDITY_GATE_FAIL_CLOSED=true`

Live symbols:

`ADAUSDT`, `ATOMUSDT`, `BTCUSDT`, `FETUSDT`, `INJUSDT`, `LINKUSDT`, `LTCUSDT`, `NEARUSDT`, `RUNEUSDT`, `SUIUSDT`, `ZECUSDT`

No secondary symbol route is live-routable unless the contract changes intentionally.

## Current Order State

Current runtime state is close-only and idle:

- `AUTO_TRADING_CLOSE_ONLY=false`
- runtime safety lock: `close_only_active=true`
- `AUTO_TRADING_LIVE_RISK_PER_TRADE_PCT=0.005`
- `new entries`: blocked by `close_only_active`
- `run_micro_live_runtime_guard.py`: `FAIL`
- guard detail: direct current live-exit USDT report `aggregate_closed=334`, `aggregate_ev_r=-0.1725`, required EV floor `0.10`
- current-runtime live intents since restart: `0`
- current-runtime live submissions since restart: `0`
- open runtime orders: `0`
- open Binance positions: `0`
- latest SIR opportunity report at `2026-05-20 06:17 KST`: current-runtime expected orders `0`; recent 72h lookback expected orders `1`, and that pre-restart SUIUSDT opportunity was blocked by `thesis_active_cap_reached` with replay outcome `-1.1325R`.
- before the close-only lock, current audit reason was `after_session_signal_window`, meaning the system was outside the SIR setup window. New entries are now blocked first by close-only until validation is realigned.

The dashboard still shows 4 recent historical intents in the 7-day window. Those are older `SKIP_SHADOW_ONLY` / rollout-readiness style records and are not current-runtime submit-ready gaps.

## Guard Snapshot

Latest checked reports:

- `run_micro_live_runtime_guard.py`: `FAIL`, blocking failure `micro_live_backtest_contract_alignment`
- `run_live_leverage_cap_sync.py`: `OK`, target leverage `10`, pending `0`, fail `0`
- `run_micro_live_boot_check.py`: `PASS`, blocking failures `0`
- `run_live_reconciliation_watchdog.py`: `OK`, reconciliation issues `0`
- `run_micro_live_synthetic_canary.py`: `PASS`, `no_live_order_sent=true`
- `run_session_impulse_retest_runtime_audit_report.py`: `PASS`, no hard route failures
- `run_micro_intrabar_portfolio_mix_config_dry_run.py`: `PASS`, no live authority, blocking failures `0`, warnings `0`
- `review_micro_intrabar_candidate_governance.py`: `RUNTIME_ACTIVE_OBSERVE`, reason `runtime_active_with_passing_governance_surfaces`
- `run_micro_live_no_order_watchdog.py`: `OK/INFO`, only pre-restart advisory context
- `run_micro_live_ops_heartbeat.py`: `PASS`, hard failures `0`, warnings `0`
- `run_replay_validation_bridge.py`: `PASS`, audit-only, live approval unchanged

Runtime guard detail:

- leverage sync stale was refreshed and now passes.
- runtime guard now prioritizes direct `micro_main_usdt_backtest` reports over the older portfolio-mix advisory report.
- live entry permission is currently blocked by the runtime close-only safety lock. After unlocking, it is still controlled by MICRO_LIVE route gates, liquidity gate, account protection gate, and exchange protection checks.
- SIR exit contract guard now also reports whether `important_zone` exits are enabled. Current runtime has important-zone exits explicitly off; the active applied exit remains the structure-buffered policy.
- installed LaunchAgents now use `micro_live_usdt_11`; entry-surface and live-candidate readiness are also capped at limit `11`.
- operator brief LaunchAgents now set `OPERATOR_BRIEF_SNAPSHOT_API_BASE_URL=http://127.0.0.1:8000`, so handoff briefs read the running API surface instead of accidentally mixing in stale workspace reports.
- `install_micro_live_ops_launchd.py` now rewrites generated script/log paths to the configured runtime `--working-dir`, so regenerated ops plists do not drift back to workspace script/log paths.
- current DB state has no active unexpired plans and no post-runtime-start order intents/submissions. Runtime audit is `PASS`; `ws_stream_active_route_suppressed` is the expected duplicate-route guard because websocket routing owns live routing.

## Portfolio And Scanner Context

The runtime stack is healthy, but new entries are intentionally locked. The current entry surface has no live order submissions:

- `LIVE_ORDER_CANDIDATE=0`
- `CONTEXT_REVIEW_SETUP=0`
- `BLOCKED_SETUP=0`
- current live family: `session_impulse_retest`

Interpretation:

- Fresh `session_impulse_retest + CONFIRM` candidates cannot be submitted while close-only is active. After unlock, they must match the 11-symbol/direction/session contract and pass safety checks.
- `Trading entry surface` may show context rows, but current order authority remains `live_candidate_promotion_readiness`.
- Do not turn context-only scanner rows into live submit instructions.

## Current Validation Finding

- The older 11-symbol portfolio-mix report still shows 428 trades, `+76.4013R`, EV `+0.1785R`, but it is not direct proof for the current runtime signal generator.
- A direct runtime USDT backtest using the current live exit policy produced 334 trades, `-57.6096R`, EV `-0.1725R`.
- Because of that mismatch, the recommended operating state is close-only until the live route is either changed to match the profitable candidate logic or replaced by a directly validated model.
- The important-zone TP/SL candidates tested so far did not beat the current structure-buffered exit and should not be promoted.

`ARBUSDT` is intentionally removed from the live allowlist. Recent live liquidity-universe samples showed ARB failing every checked sample, so the higher ARB-included theoretical backtest is not the best execution-quality route. `DOGEUSDT` was tested as a replacement, but the small return increase did not justify lower EV, weaker stress results, and max 3 concurrent positions.

Latest live liquidity samples show `ATOMUSDT` as a `WATCH`, not a permanent removal candidate yet: it failed the current 170 USDT sizing check with `SPLIT_REQUIRED / one_minute_participation_too_high`, while the other 10 symbols were executable. The runtime liquidity gate should skip ATOM entries while this persists. A no-ATOM 10-symbol replay remains viable but slightly weaker overall: 397 trades, `+71.2466R`, EV `+0.1795R`, max DD `5.9195R`, 170 USDT replay return `70.03%`. Keep ATOM under observation rather than removing it from the contract on only two post-prune samples.

## Storage And Report Roots

- Workspace: `/Users/yumin/Documents/trading`
- Runtime source copy: `/Users/yumin/Library/Application Support/trading/runtime_src`
- Runtime database: `/Users/yumin/Library/Application Support/trading/data/trading.db`
- Workspace `trading.db` is a symlink to the runtime database.
- Ops heartbeat reads durable runtime reports by default, even when invoked from the workspace.

When checking freshness, prefer the paths printed by heartbeat, because they may point into `runtime_src/reports` rather than workspace `reports`.

## Active Backlog

Implementation backlog is not the immediate blocker. The current operating priority is:

1. Keep runtime stack healthy and close-only active while validation is inconsistent.
2. Rebuild the live route so runtime signal generation and the profitable research report are the same thing, or replace the route.
3. Do not unlock new entries until direct 3y/5y runtime backtests pass the configured EV/trade-count floors.
4. Before any unlock, rerun runtime guard, boot check, synthetic canary, safety state, account protection audit, and live replay parity.
5. Revisit optional contract pruning only after the active direct-runtime model is profitable.

## Quick Verification

```bash
curl -s "http://127.0.0.1:8000/health/ready" | jq
curl -s "http://127.0.0.1:8000/execution/safety-state" | jq
curl -s "http://127.0.0.1:8000/execution/operator-dashboard?symbol=BTCUSDT&universe=micro_live_usdt_11&days=7&fast=true" | jq
./.venv/bin/python scripts/run_micro_live_boot_check.py --days 3 --no-fail-exit
./.venv/bin/python scripts/run_micro_live_ops_heartbeat.py --no-fail-exit
```
