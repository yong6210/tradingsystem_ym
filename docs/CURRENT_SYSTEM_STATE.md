# Current System State

Last updated: 2026-05-17 03:29 KST

This is the current operator snapshot for the whole repository/runtime. Detailed live-route parameters stay in [MICRO_LIVE_CURRENT_STATE.md](/Users/yumin/Documents/trading/docs/MICRO_LIVE_CURRENT_STATE.md); daily operating procedure stays in [AUTO_TRADING_OPERATING_RUNBOOK.md](/Users/yumin/Documents/trading/docs/AUTO_TRADING_OPERATING_RUNBOOK.md).

## Executive Summary

- Initial repository inspection: branch `main`; no tracked local changes were present before this documentation refresh.
- Runtime stack: running under launchd/watchdog with API, loop worker, and websocket worker active.
- API health: `/health/ready` is `ready`.
- Execution mode: `MICRO_LIVE`.
- Live route: `session_impulse_retest + CONFIRM` on the 16-symbol USDC route.
- Safety state: new entries allowed; kill switch off; close-only off.
- Exchange exposure: no open Binance positions, no open runtime orders, no current live submissions.
- Current order posture: wait for a fresh live-eligible SIR candidate. There is no current submit-ready gap.
- Ops heartbeat: `WATCH`, not `FAIL`. Hard failures are `0`; the only warning is `replay_validation_bridge=WATCH` because 5 expanded symbols are missing portfolio replay coverage in the audit-only bridge.

## Runtime Stack

Active processes observed:

- `watch_runtime_stack_tmp.sh`
- `uvicorn app.main:app --host 127.0.0.1 --port 8000`
- `run_worker.py --mode loop --sync-universe ...`
- `run_worker.py --ws-stream --ws-intervals 1m,5m,15m --ws-symbols <16 live symbols>`

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
- `market_data_1m=true`, fresh `16/16`
- `market_data_5m=true`, fresh `16/16`

## Live Contract

Current settings resolve to:

- `AUTO_TRADING_ENABLED=true`
- `AUTO_TRADING_EXECUTION_MODE=MICRO_LIVE`
- `BINANCE_TRADE_LIVE_ENABLED=true`
- `AUTO_TRADING_ALLOWED_FAMILIES=session_impulse_retest`
- `AUTO_TRADING_MICRO_LIVE_ALLOWED_ENTRY_MODELS=CONFIRM`
- `AUTO_TRADING_MICRO_LIVE_ALLOWED_SESSIONS=dead_session,london,new_york`
- `AUTO_TRADING_MICRO_LIVE_MAX_CONCURRENT_POSITIONS=3`
- `AUTO_TRADING_MICRO_LIVE_MAX_DAILY_NEW_ENTRIES=0`
- `AUTO_TRADING_LIVE_BALANCE_SYNC_ENABLED=true`
- `AUTO_TRADING_LIVE_LIQUIDITY_GATE_ENABLED=true`
- `AUTO_TRADING_LIVE_LIQUIDITY_GATE_FAIL_CLOSED=true`

Live symbols:

`BTCUSDC`, `ETHUSDC`, `SOLUSDC`, `LINKUSDC`, `BNBUSDC`, `XRPUSDC`, `ADAUSDC`, `AVAXUSDC`, `BCHUSDC`, `LTCUSDC`, `NEARUSDC`, `1000PEPEUSDC`, `ARBUSDC`, `1000SHIBUSDC`, `FILUSDC`, `DOGEUSDC`

Secondary/tracked SIR symbols are not live-routable unless the contract changes:

`SUIUSDC`, `AAVEUSDC`, `HBARUSDC`, `ZECUSDC`, `UNIUSDC`

## Current Order State

Current runtime state is open but idle:

- `new_entries_allowed=true`
- `deployment_go_no_go=GO`
- `playbook_action=continue_candidate_review_under_portfolio_caps`
- `approval_strip.order_route_approve_value=waiting_for_live_candidate`
- `approval_strip.order_route_approve_reason=Current live symbols have no fresh live-eligible candidate.`
- current-runtime live intents: `0`
- current-runtime live submissions: `0`
- open runtime orders: `0`
- open Binance positions: `0`

The dashboard still shows 4 recent historical intents in the 7-day window. Those are older `SKIP_SHADOW_ONLY` / rollout-readiness style records and are not current-runtime submit-ready gaps.

## Guard Snapshot

Latest checked reports:

- `run_micro_live_runtime_guard.py`: `PASS`
- `run_micro_live_boot_check.py`: `PASS`, blocking failures `0`
- `run_live_reconciliation_watchdog.py`: `OK`, reconciliation issues `0`
- `run_micro_live_synthetic_canary.py`: `PASS`, `no_live_order_sent=true`
- `run_session_impulse_retest_runtime_audit_report.py`: `PASS`, no hard route failures
- `run_micro_live_no_order_watchdog.py`: `OK/INFO`, only pre-restart advisory context
- `run_micro_live_ops_heartbeat.py`: `WATCH`, hard failures `0`, warning `1`
- `run_replay_validation_bridge.py`: `WATCH`, audit-only, live approval unchanged

Heartbeat warning detail:

- replay bridge decisions: `ELIGIBLE_FOR_RUNTIME_VALIDATION_BRIDGE=11`, `NOT_ELIGIBLE=5`
- blocker for the 5 non-eligible names: `replay_validation_portfolio_replay_missing`
- affected names: `1000PEPEUSDC`, `1000SHIBUSDC`, `ARBUSDC`, `DOGEUSDC`, `FILUSDC`

This warning is not an order-submit failure. It means the bridge audit has mixed evidence for part of the expanded route and should stay visible during live review.

## Portfolio And Scanner Context

The runtime gate is open, and portfolio review can proceed under caps. The current scanner/portfolio surfaces show context candidates, but they are not live route candidates:

- portfolio accepted candidates observed: `2`
- representative accepted symbols: `AVAXUSDC`, `NEARUSDC`
- representative family: `legacy_zone_plan`
- current live family: `session_impulse_retest`

Interpretation:

- `legacy_zone_plan` candidates are context-only under the current MICRO_LIVE route.
- `Trading entry surface` may show context rows, but current order authority remains `live_candidate_promotion_readiness`.
- Do not turn context-only scanner rows into live submit instructions.

## Storage And Report Roots

- Workspace: `/Users/yumin/Documents/trading`
- Runtime source copy: `/Users/yumin/Library/Application Support/trading/runtime_src`
- Runtime database: `/Users/yumin/Library/Application Support/trading/data/trading.db`
- Workspace `trading.db` is a symlink to the runtime database.
- Ops heartbeat reads durable runtime reports by default, even when invoked from the workspace.

When checking freshness, prefer the paths printed by heartbeat, because they may point into `runtime_src/reports` rather than workspace `reports`.

## Active Backlog

Implementation backlog is not the immediate blocker. The current operating priority is:

1. Keep runtime stack healthy and reports fresh.
2. Wait for a fresh `session_impulse_retest + CONFIRM` live candidate.
3. If a fresh candidate becomes `submit_ready` but submissions remain `0`, treat it as an active intent-to-submission bug.
4. Keep the replay bridge `WATCH` visible until the 5 expanded names have matching portfolio replay coverage or are intentionally removed/handled by policy.
5. Revisit optional contract pruning only after the first real MICRO_LIVE operating cycle produces live fills/closes.

## Quick Verification

```bash
curl -s "http://127.0.0.1:8000/health/ready" | jq
curl -s "http://127.0.0.1:8000/execution/safety-state" | jq
curl -s "http://127.0.0.1:8000/execution/operator-dashboard?symbol=BTCUSDC&universe=usdc_perp_top30&days=7&fast=true" | jq
./.venv/bin/python scripts/run_micro_live_boot_check.py --days 3 --no-fail-exit
./.venv/bin/python scripts/run_micro_live_ops_heartbeat.py --no-fail-exit
```
