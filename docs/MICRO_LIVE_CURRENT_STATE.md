# MICRO_LIVE Current State

Last updated: 2026-05-18 20:36 KST

This is the concise operator source for the current live canary shape. Whole-system snapshot stays in [CURRENT_SYSTEM_STATE.md](/Users/yumin/Documents/trading/docs/CURRENT_SYSTEM_STATE.md); detailed history stays in [SELF_CHECK_LOG.md](/Users/yumin/Documents/trading/docs/SELF_CHECK_LOG.md); daily procedures stay in [AUTO_TRADING_OPERATING_RUNBOOK.md](/Users/yumin/Documents/trading/docs/AUTO_TRADING_OPERATING_RUNBOOK.md).

## Live Route

- execution mode: `MICRO_LIVE`
- trade state: `CLOSE_ONLY`
- strategy family: `session_impulse_retest`
- entry model: `CONFIRM`
- symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, `XRPUSDT`, `ADAUSDT`, `AVAXUSDT`, `LINKUSDT`, `DOGEUSDT`, `BCHUSDT`, `LTCUSDT`, `NEARUSDT`, `FILUSDT`, `DOTUSDT`, `ATOMUSDT`, `ETCUSDT`, `HBARUSDT`, `AAVEUSDT`, `UNIUSDT`, `SUIUSDT`, `INJUSDT`, `FETUSDT`, `ARBUSDT`, `APTUSDT`, `RUNEUSDT`, `PENDLEUSDT`, `ICPUSDT`, `XLMUSDT`, `ZECUSDT`, `QNTUSDT`, `DASHUSDT`
- directions: `LONG|SHORT` for every live symbol in the direction contract
- sessions: `dead_session`, `london`, `new_york`

`AUTO_TRADING_CLOSE_ONLY=true` is the current recommended runtime state. It blocks new entries while keeping the stack available for position protection, reconciliation, and reduce-only cleanup.

## Why Close-Only

The SIR backtest was corrected on 2026-05-18 to avoid same-5m-bar lookahead. Before the correction, a completed 5m candle could create a signal while the 1m entry search still started at that 5m candle's open time. Live trading only knows that completed 5m candle after it closes, so those same-bar entries were not realistically tradable.

After the correction, the quick 31-symbol USDT check changed from positive to negative:

- report: `reports/validation/micro_main_exit_policy_search/micro_main_exit_policy_search_20260518T112504Z.json`
- current live-style split policy: `closed=279`, `total_r=-134.6996`, `ev=-0.4828`, `win=0.2760`
- best stage2 candidate in that run: `closed=205`, `total_r=-62.7606`, `ev=-0.3061`, `win=0.4049`

Plain meaning: the old optimistic SIR result should not be trusted for live enablement. The no-order problem was not just "no fresh signal"; the previous backtest protocol was too generous versus live timing.

## Current Runtime Settings

- `AUTO_TRADING_EXECUTION_MODE=MICRO_LIVE`
- `AUTO_TRADING_CLOSE_ONLY=true`
- `BINANCE_TRADE_LIVE_ENABLED=true`
- `AUTO_TRADING_ALLOWED_FAMILIES=session_impulse_retest`
- `AUTO_TRADING_MICRO_LIVE_ALLOWED_FAMILIES=session_impulse_retest`
- `AUTO_TRADING_MICRO_LIVE_ALLOWED_ENTRY_MODELS=CONFIRM`
- `AUTO_TRADING_MICRO_LIVE_MAX_CONCURRENT_POSITIONS=3`
- `AUTO_TRADING_MICRO_LIVE_MAX_DAILY_NEW_ENTRIES=0`
- `AUTO_TRADING_LIVE_BREAKEVEN_AFTER_PARTIAL_ENABLED=false`
- `SESSION_IMPULSE_RETEST_EXIT_POLICY_NAME=structure_buffered_swing6_stop0.12_tpbuf0.08`
- `SESSION_IMPULSE_RETEST_EXIT_STOP_MODE=structure_floor`

`MAX_DAILY_NEW_ENTRIES=0` means the daily cap is disabled. It does not override close-only. With close-only on, new entries are blocked regardless of candidate quality.

Live risk sizing uses Binance futures available balance when `AUTO_TRADING_LIVE_BALANCE_SYNC_ENABLED=true`, with `USDT,USDC` in the sync asset list. `AUTO_TRADING_LIVE_ACCOUNT_EQUITY_USDT` remains the fallback/reference value, not the primary sizing source while balance sync is enabled.

The configured SIR exit policy is structure-buffered, but it is not a reason to re-enable entries by itself. For a long, SL is placed beyond the recent swing low with an ATR buffer and TP is placed slightly before the structure target. For a short, the same idea is mirrored above swing highs and before support targets.

## Required Checks

Use these before treating the route as ready again:

```bash
./.venv/bin/python scripts/run_micro_live_runtime_guard.py --days 30 --no-fail-exit
./.venv/bin/python scripts/run_micro_live_boot_check.py --days 3 --limit 200 --no-fail-exit
./.venv/bin/python scripts/run_micro_live_synthetic_canary.py --symbol BTCUSDT --entry-model CONFIRM --direction long --stop-bps 50 --no-fail-exit
./.venv/bin/python scripts/run_micro_main_exit_policy_search.py --max-policies 14 --stage1-symbols BTCUSDT,ETHUSDT,SOLUSDT --stage1-days 180 --stage1-min-trades 10 --stage2-days 365 --stage2-min-trades 30 --stage2-top 10 --write-report
```

## Next Research Direction

Do not re-enable new SIR entries until one of these passes no-lookahead testing:

- after-close retest/continuation: signal is confirmed at the 5m close, then entry is only allowed after that close.
- true intrabar simulation: use only information that would have been known inside the developing 5m candle.
- structure-first entries: key levels, order-block/FVG/volume-node context, and support/resistance exits must still be tested under the same no-lookahead rule.

Any future 3y/5y report must state whether 1m entries were searched only after the 5m setup candle became actionable.

## Known Limits

- Historical liquidity gate drag is not exact without historical order book snapshots.
- Backtest alignment does not guarantee live PnL; live fills, slippage, rejects, latency, and forced exits remain separate truth.
- A/B legacy governance reports may still be useful as historical context, but they are not the production anchor for the current USDT 31 SIR route.
