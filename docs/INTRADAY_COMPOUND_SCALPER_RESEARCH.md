# Intraday Compound Scalper Research

Last updated: 2026-05-29 KST

## Purpose

This document defines the research-only 15m/30m long-short family added for compound-style crypto intraday trading.

Family name: `intraday_compound_scalper`

This family is not live authority. It does not change `MICRO_LIVE` allowlists, validation approval, operations checklist, close-only, liquidity, exchange-rule, sizing, or reconciliation gates.

## Why This Exists

The current `session_impulse_retest` route is intentionally sparse and is not designed for frequent 15m/30m compounding. A separate intraday family is needed so higher-cadence long/short ideas can be tested without weakening the current live safety contract.

## Signal Contract

The strategy uses completed 15m/30m candles only.

Execution assumption:

- Signal is evaluated at the completed signal bar close.
- Entry is at the next bar open.
- If stop and target both touch inside the same bar, the backtest assumes the stop happened first.
- Fee and slippage are charged on both entry and exit.

Long setup:

1. Fast EMA is above slow EMA.
2. Slow EMA slope is positive.
3. Price either breaks the prior range high or pulls back to fast EMA and reclaims.
4. Candle body, close location, and volume factor confirm the move.
5. Stop distance must fit the configured min/max stop bounds.

Short setup is the mirrored version.

## Exit Contract

- Initial stop uses the larger of ATR stop and recent structure stop.
- Target is fixed by `target_rr`.
- Breakeven stop can activate after `breakeven_rr`.
- Time exit closes the trade after `max_hold_bars`.

This is deliberately simple. The first goal is to find whether the family has any post-cost edge before adding adaptive exits.

## Backtest Command

```bash
./.venv/bin/python scripts/run_intraday_compound_scalper_backtest.py \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT \
  --days 365 \
  --intervals 15m,30m \
  --write-report
```

Default output:

- `reports/validation/intraday_compound_scalper/latest.json`
- timestamped JSON in the same directory

## Promotion Gate

Before this family can be considered for paper/live routing, require at minimum:

1. Direct 3y/5y no-lookahead report.
2. Post-cost EV `>= 0.10R`.
3. Profit factor `>= 1.25`.
4. Max drawdown acceptable relative to total R.
5. Symbol-level positive contribution is not concentrated in one coin only.
6. Separate 15m and 30m summaries are not both dependent on the same overfit parameter set.
7. Replay-to-runtime parity path is implemented before any live authority.

Until those pass, this remains research-only.
