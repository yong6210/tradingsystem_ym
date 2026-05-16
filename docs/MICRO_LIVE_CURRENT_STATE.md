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
