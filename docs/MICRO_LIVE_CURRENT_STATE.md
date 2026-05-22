# MICRO_LIVE Current State

Last updated: 2026-05-20 KST

This is the concise operator source for the current live canary shape. Whole-system snapshot stays in [CURRENT_SYSTEM_STATE.md](/Users/yumin/Documents/trading/docs/CURRENT_SYSTEM_STATE.md); detailed history stays in [SELF_CHECK_LOG.md](/Users/yumin/Documents/trading/docs/SELF_CHECK_LOG.md); daily procedures stay in [AUTO_TRADING_OPERATING_RUNBOOK.md](/Users/yumin/Documents/trading/docs/AUTO_TRADING_OPERATING_RUNBOOK.md).

## Live Route

- execution mode: `MICRO_LIVE`
- trade state: `MICRO_LIVE infrastructure running` / runtime close-only lock active
- strategy family: `session_impulse_retest`
- entry model: `CONFIRM`
- symbols: `ADAUSDT`, `ATOMUSDT`, `BTCUSDT`, `FETUSDT`, `INJUSDT`, `LINKUSDT`, `LTCUSDT`, `NEARUSDT`, `RUNEUSDT`, `SUIUSDT`, `ZECUSDT`
- directions: `ADAUSDT:LONG`, `BTCUSDT:LONG`, `INJUSDT:LONG`, `LINKUSDT:LONG`, `ATOMUSDT:SHORT`, `FETUSDT:SHORT`, `LTCUSDT:SHORT`, `NEARUSDT:SHORT`, `RUNEUSDT:SHORT`, `SUIUSDT:SHORT`, `ZECUSDT:SHORT`
- sessions: `dead_session`, `london`, `new_york`

`AUTO_TRADING_CLOSE_ONLY=false` in static config, but a runtime safety lock currently has `close_only_active=true`. Plain meaning: the workers can keep running and manage closes, but new entries are blocked until validation is realigned.

## Live Enablement Note

The configured route is `session_impulse_retest + CONFIRM + USDT 11 + structure_buffered_swing6_stop0.12_tpbuf0.08_pm_stop0.00r_advvol_any`, but it is not currently cleared for new MICRO_LIVE entries. Runtime protection remains mandatory: live stop precheck, mark-price stop guard before exchange SL submit, exchange protection orders, post-ACK SL/TP verification, reconciliation, and emergency flatten on SL protection failure or missing post-fill SL price stay enabled.

Earlier no-lookahead research found that some same-5m-bar assumptions were too optimistic. Treat this live state as controlled MICRO_LIVE operation, not proof that every research variant is production-safe.

Plain meaning: fresh live orders are paused. No current position or open order exists at this snapshot.

## Current Runtime Settings

- `AUTO_TRADING_EXECUTION_MODE=MICRO_LIVE`
- `AUTO_TRADING_CLOSE_ONLY=false`
- runtime safety lock: `close_only_active=true`
- `AUTO_TRADING_LIVE_RISK_PER_TRADE_PCT=0.005`
- `BINANCE_TRADE_LIVE_ENABLED=true`
- `AUTO_TRADING_ALLOWED_FAMILIES=session_impulse_retest`
- `AUTO_TRADING_MICRO_LIVE_ALLOWED_FAMILIES=session_impulse_retest`
- `AUTO_TRADING_MICRO_LIVE_ALLOWED_ENTRY_MODELS=CONFIRM`
- `AUTO_TRADING_MICRO_LIVE_MAX_CONCURRENT_POSITIONS=2`
- `AUTO_TRADING_MICRO_LIVE_MAX_DAILY_NEW_ENTRIES=0`
- `AUTO_TRADING_LIVE_FAMILY_CLUSTER_WINDOW_MINUTES=30`
- `AUTO_TRADING_LIVE_MAX_SAME_FAMILY_ENTRIES_PER_WINDOW=2`
- `AUTO_TRADING_LIVE_MAX_SAME_FAMILY_DIRECTION_EXPOSURES=2`
- `AUTO_TRADING_LIVE_RECENT_LOSS_COOLDOWN_MINUTES=60`
- `AUTO_TRADING_LIVE_RECENT_LOSS_TRIGGER_COUNT=4`
- `AUTO_TRADING_LIVE_BREAKEVEN_AFTER_PARTIAL_ENABLED=true`
- `AUTO_TRADING_LIVE_ADVERSE_VOLUME_EXIT_ENABLED=true`
- `AUTO_TRADING_LIVE_PROTECTION_VERIFY_AFTER_ATTACH_ENABLED=true`
- `AUTO_TRADING_LIVE_PROTECTION_VERIFY_FAIL_CLOSED=true`
- `AUTO_TRADING_LIVE_PROTECTION_VERIFY_ATTEMPTS=3`
- `AUTO_TRADING_LIVE_PROTECTION_VERIFY_SLEEP_SECONDS=0.5`
- `AUTO_TRADING_LIVE_TAKE_PROFIT_VERIFY_AFTER_ATTACH_ENABLED=true`
- `AUTO_TRADING_LIVE_STOP_MARK_PRICE_GUARD_ENABLED=true`
- `AUTO_TRADING_LIVE_MISSING_STOP_WATCHDOG_FLATTEN_ENABLED=true`
- `AUTO_TRADING_LIVE_MISSING_STOP_WATCHDOG_CANCEL_OPEN_ORDERS=true`
- `AUTO_TRADING_LIVE_UNEXPECTED_OPEN_ORDER_WATCHDOG_CANCEL_ENABLED=true`
- `AUTO_TRADING_LIVE_LIQUIDITY_GATE_PARTIAL_SUBMIT_ENABLED=true`
- `AUTO_TRADING_LIVE_LIQUIDITY_GATE_MIN_TRANCHE_TARGET_FRACTION=0.10`
- `SESSION_IMPULSE_RETEST_CORE_LIVE_SLOTS=29`
- `SESSION_IMPULSE_RETEST_EXIT_POLICY_NAME=structure_buffered_swing6_stop0.12_tpbuf0.08_pm_stop0.00r_advvol_any`
- `SESSION_IMPULSE_RETEST_EXIT_STOP_MODE=structure_floor`
- `SESSION_IMPULSE_RETEST_EXIT_TARGET_RR=2.5`
- `SESSION_IMPULSE_RETEST_SATURDAY_RISK_MULTIPLIER=1.0`

`MAX_DAILY_NEW_ENTRIES=0` means the daily cap is disabled. It does not force entries; fresh candidates still have to pass the live route gates.

`SESSION_IMPULSE_RETEST_CORE_LIVE_SLOTS=29` is a rollout-rank window, not a 29-symbol live universe. The live universe remains the 11-symbol allowlist above; slot 29 is required because the selected basket includes `ZECUSDT`, whose original USDT rollout rank is 29.

Live risk sizing uses Binance futures available balance when `AUTO_TRADING_LIVE_BALANCE_SYNC_ENABLED=true`, with `USDT,USDC` in the sync asset list. `AUTO_TRADING_LIVE_ACCOUNT_EQUITY_USDT` remains the fallback/reference value, not the primary sizing source while balance sync is enabled.

The configured SIR exit policy uses structure-buffered stops/targets, `2.5R` target reference, `35%` TP1 / `65%` TP2 split, stop-to-entry after partial, and adverse-volume exit management. This is active in runtime configuration for fresh MICRO_LIVE entries.

Important-zone exit settings are now wired into the runtime policy object and runtime guard, but they are explicitly disabled in the current live contract. Plain meaning: the code can now report and later test that mode cleanly, but the active bot is still using the validated structure-buffered exit, not an unapproved 1D/4H order-block/FVG exit.

The live liquidity gate is allowed to reduce an oversized entry into a smaller first tranche when the order is too large for current depth/volume, as long as the safe tranche is at least `10%` of the target and at least `10 USDT` notional. Hard liquidity failures such as unavailable depth or too-wide spread still block the submit.

The account-protection watchdog runs independently of fresh entries. If it finds an open live position with no matching exchange-side stop order, it submits a same-side closing market order and then cancels same-symbol open orders so an orphan TP cannot remain. If an entry fill reaches the protection attach step but no valid SL price is available, the submit path also immediately sends the emergency flatten. Missing TP alone stays a warning, because the stop is the mandatory protection layer.

Live protection audit, reconciliation watchdog, candidate readiness, and no-order watchdog are scheduled every 5 minutes. The no-order watchdog checks for the specific failure mode where a live-routable setup or submit-ready intent exists but no live submission follows.

## Shadow Exit Review

Important-zone exits remain research-only unless they are part of the current approved SIR candidate contract. The current applied candidate uses the structure-buffered exit policy listed above. The latest shadow review keeps the current live route unchanged: the tested important-zone candidates did not beat the configured comparison baseline, and the current live structure-buffered policy is not present in those older important-zone validation reports, so they are not direct replacement proof.

```bash
./.venv/bin/python scripts/run_sir_exit_shadow_review.py --write-report
```

Current promotion rule: same entries, at least 98% of baseline trade count, and candidate total R plus cost-stressed R must beat `legacy_full_2r` on every configured validation report.

## Paper Replacement Candidate

The current applied replacement candidate is an 11-symbol long/short mix after liquidity pruning, but its original positive report is now treated as advisory, not direct live proof:

- symbols: `ADAUSDT`, `ATOMUSDT`, `BTCUSDT`, `FETUSDT`, `INJUSDT`, `LINKUSDT`, `LTCUSDT`, `NEARUSDT`, `RUNEUSDT`, `SUIUSDT`, `ZECUSDT`
- portfolio-mix advisory replay: 428 trades, `+76.4013R`, EV `+0.1785R`, max DD `5.6355R`
- direct runtime USDT replay with the current live exit policy: 334 trades, `-57.6096R`, EV `-0.1725R`
- order frequency: 428 trades over roughly 5 years is about `0.23` trades/day, so this applied MICRO_LIVE route is not a 3-4 trades/day strategy. A quiet week can happen without implying the order path is broken.
- cost stress: extra `0.05R` per trade stays positive at `+55.0013R`; cost x2 stays positive at `+24.1212R`
- 170 USDT and 1000 USDT portfolio replay both had zero minimum-quantity rejects
- recommended paper capacity: max 2 concurrent positions, because it accepted 426/428 trades and stayed within 98% of the 3-position return with less exposure complexity

`ARBUSDT` was removed from the live allowlist because recent live liquidity-universe samples failed for ARB in every checked sample, mainly from spread/participation quality. A `DOGEUSDT` replacement was tested, but it only improved 5y return slightly versus simply dropping ARB while lowering EV, weakening cost stress, and requiring max 3 concurrent positions. The simpler 11-symbol route is the current recommendation.

`ATOMUSDT` is currently a liquidity `WATCH`, not a removal yet. Two latest 11-symbol samples blocked ATOM short with `SPLIT_REQUIRED / one_minute_participation_too_high` at the current small account size, while the other 10 symbols remained executable. The per-symbol live liquidity gate should skip ATOM while this condition persists. A no-ATOM 10-symbol replay was checked in memory: 397 trades, `+71.2466R`, EV `+0.1795R`, max DD `5.9195R`, and 170 USDT replay return `70.03%`; this is viable but gives up about `5.1547R` versus keeping ATOM, so the current recommendation is monitor first, remove only if the block persists across more sessions.

Latest short-window check at `2026-05-20 06:17 KST`: current-runtime expected orders `0`; recent 72h expected orders `1`, before the current runtime start, and that SUIUSDT candidate was blocked by `thesis_active_cap_reached` with replay outcome `-1.1325R`. Current no-signal diagnostics are dominated by `after_session_signal_window`, which means the system is waiting for a valid SIR setup window.

The no-order watchdog now includes the next approximate SIR observation window in the action text. At this snapshot it points to `2026-05-20 09:20-11:00 KST`; candidates still have to pass all filters inside that window.

This candidate remains configured, but MICRO_LIVE entries are paused by the runtime close-only lock. The latest safety state reports `new_entry_allowed=false`, no open positions, and no open orders.

The runtime guard now fails intentionally on `micro_live_backtest_contract_alignment` because it uses direct runtime reports before portfolio-mix advisory reports. The latest direct current-policy report has matching exit-policy name but negative EV, so it must block live entry approval.

## Required Checks

Use these after changes or before removing close-only. The latest runtime guard is expected to fail until the direct runtime 3y/5y validation passes:

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
- A/B legacy governance reports may still be useful as historical context, but they are not the production anchor for the current USDT 11 SIR route.
