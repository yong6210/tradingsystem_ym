# MICRO_LIVE Current State

Last updated: 2026-05-19 KST

This is the concise operator source for the current live canary shape. Whole-system snapshot stays in [CURRENT_SYSTEM_STATE.md](/Users/yumin/Documents/trading/docs/CURRENT_SYSTEM_STATE.md); detailed history stays in [SELF_CHECK_LOG.md](/Users/yumin/Documents/trading/docs/SELF_CHECK_LOG.md); daily procedures stay in [AUTO_TRADING_OPERATING_RUNBOOK.md](/Users/yumin/Documents/trading/docs/AUTO_TRADING_OPERATING_RUNBOOK.md).

## Live Route

- execution mode: `MICRO_LIVE`
- trade state: `LIVE_ENTRIES_ENABLED`
- strategy family: `session_impulse_retest`
- entry model: `CONFIRM`
- symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, `XRPUSDT`, `ADAUSDT`, `AVAXUSDT`, `LINKUSDT`, `DOGEUSDT`, `BCHUSDT`, `LTCUSDT`, `NEARUSDT`, `FILUSDT`, `DOTUSDT`, `ATOMUSDT`, `ETCUSDT`, `HBARUSDT`, `AAVEUSDT`, `UNIUSDT`, `SUIUSDT`, `INJUSDT`, `FETUSDT`, `ARBUSDT`, `APTUSDT`, `RUNEUSDT`, `PENDLEUSDT`, `ICPUSDT`, `XLMUSDT`, `ZECUSDT`, `QNTUSDT`, `DASHUSDT`
- directions: `LONG|SHORT` for every live symbol in the direction contract
- sessions: `dead_session`, `london`, `new_york`

`AUTO_TRADING_CLOSE_ONLY=false` opens new entries when a fresh `session_impulse_retest` candidate passes the live approval, liquidity, sizing, stop precheck, and account-protection gates. It does not force an entry.

## Live Enablement Note

The current live route is operator-enabled on the proven `session_impulse_retest` family with the `legacy_full_2r` exit shape. Runtime protection remains mandatory: live stop precheck, exchange protection orders, reconciliation, and emergency flatten on protection failure stay enabled.

Earlier no-lookahead research found that some same-5m-bar assumptions were too optimistic. Treat this live state as controlled MICRO_LIVE operation, not proof that every research variant is production-safe.

Plain meaning: entries are allowed, but live fills, stop attachment, latency, and replay/live parity are still the source of truth.

## Current Runtime Settings

- `AUTO_TRADING_EXECUTION_MODE=MICRO_LIVE`
- `AUTO_TRADING_CLOSE_ONLY=false`
- `BINANCE_TRADE_LIVE_ENABLED=true`
- `AUTO_TRADING_ALLOWED_FAMILIES=session_impulse_retest`
- `AUTO_TRADING_MICRO_LIVE_ALLOWED_FAMILIES=session_impulse_retest`
- `AUTO_TRADING_MICRO_LIVE_ALLOWED_ENTRY_MODELS=CONFIRM`
- `AUTO_TRADING_MICRO_LIVE_MAX_CONCURRENT_POSITIONS=3`
- `AUTO_TRADING_MICRO_LIVE_MAX_DAILY_NEW_ENTRIES=0`
- `AUTO_TRADING_LIVE_BREAKEVEN_AFTER_PARTIAL_ENABLED=false`
- `SESSION_IMPULSE_RETEST_EXIT_POLICY_NAME=legacy_full_2r`
- `SESSION_IMPULSE_RETEST_EXIT_STOP_MODE=legacy`
- `SESSION_IMPULSE_RETEST_EXIT_TARGET_RR=2.0`

`MAX_DAILY_NEW_ENTRIES=0` means the daily cap is disabled. It does not force entries; fresh candidates still have to pass the live route gates.

Live risk sizing uses Binance futures available balance when `AUTO_TRADING_LIVE_BALANCE_SYNC_ENABLED=true`, with `USDT,USDC` in the sync asset list. `AUTO_TRADING_LIVE_ACCOUNT_EQUITY_USDT` remains the fallback/reference value, not the primary sizing source while balance sync is enabled.

The configured SIR exit policy is full-target `2R`. If no explicit split levels are present, runtime plans use a single full-size take-profit at the 2R target instead of the older `1R 35% + 2R 65%` default split.

## Required Checks

Use these before treating the route as ready again:

```bash
./.venv/bin/python scripts/run_micro_live_runtime_guard.py --days 30 --no-fail-exit
./.venv/bin/python scripts/run_micro_live_boot_check.py --days 3 --limit 200 --no-fail-exit
./.venv/bin/python scripts/run_micro_live_synthetic_canary.py --symbol BTCUSDT --entry-model CONFIRM --direction long --stop-bps 50 --no-fail-exit
./.venv/bin/python scripts/run_micro_main_exit_policy_search.py --max-policies 14 --stage1-symbols BTCUSDT,ETHUSDT,SOLUSDT --stage1-days 180 --stage1-min-trades 10 --stage2-days 365 --stage2-min-trades 30 --stage2-top 10 --write-report
```

## Next Research Direction

Continue validating these before scaling SIR exposure:

- after-close retest/continuation: signal is confirmed at the 5m close, then entry is only allowed after that close.
- true intrabar simulation: use only information that would have been known inside the developing 5m candle.
- structure-first entries: key levels, order-block/FVG/volume-node context, and support/resistance exits must still be tested under the same no-lookahead rule.

Any future 3y/5y report must state whether 1m entries were searched only after the 5m setup candle became actionable.

## Known Limits

- Historical liquidity gate drag is not exact without historical order book snapshots.
- Backtest alignment does not guarantee live PnL; live fills, slippage, rejects, latency, and forced exits remain separate truth.
- A/B legacy governance reports may still be useful as historical context, but they are not the production anchor for the current USDT 31 SIR route.
