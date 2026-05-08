# Prop Manual Signal Playbook

## Purpose

This playbook defines how `session_impulse_retest` signals should be read when the Binance account is auto-trading but a separate prop account is traded manually from Discord alerts.

## Discord Signal Format

`confirm` signal:

```text
[PROP SIGNAL] BTCUSDC LONG CONFIRM plan=sir_BTCUSDC_L_20260427T0600
entry=94500.0000 stop=94120.0000 tp1=94880.0000 tp2=95260.0000
invalidate=skip if not filled by 2026-04-27T06:12:00Z; skip if stop side breaks before fill
session_impulse_retest benchmark | win≈67.0% EV≈+0.65R | tier=core
```

`entry` fill:

```text
[PROP LIVE] BTCUSDC LONG filled
fill=94510.0000 qty=0.0020
entry=94500.0000 stop=94120.0000 tp1=94880.0000 tp2=95260.0000
manage=take partial near tp1, hold remainder toward tp2, time_stop≈40m
```

`tp/sl` exit:

```text
[PROP EXIT] BTCUSDC LONG target
fill=94880.0000 realized_r=0.83
reason=target_tp1
```

```text
[PROP EXIT] BTCUSDC LONG stop
fill=94120.0000 realized_r=-1.00
reason=stop_loss
```

## Manual Entry Template

### BTC Prop Template

- Product:
  - Prefer the prop account's BTC futures product, or the smallest BTC contract available.
- Direction:
  - Follow the Discord `LONG` / `SHORT`.
- Entry:
  - Only enter within the stated signal window.
  - If price has already moved materially beyond the stated entry, skip it.
- Stop:
  - Use the exact `stop=` from the alert.
- Targets:
  - Take first partial near `tp1`.
  - Hold remaining size toward `tp2`.
- Timeout:
  - If the signal is not filled by `valid_until`, cancel it.

### NQ / MNQ Prop Template

- Product:
  - Use `MNQ` first unless account size clearly supports `NQ`.
- Direction:
  - Only follow a dedicated NQ model signal.
  - Do **not** blindly copy a crypto signal into NQ.
- Entry:
  - Enter only inside the signaled entry window.
- Stop:
  - Hard stop at the stated invalidation level.
- Targets:
  - First scale at `tp1`, remainder toward `tp2`.
- Timeout:
  - Cancel if not filled by the stated expiry.

## Stop / Target / Invalidation Rules

- Pre-entry invalidation:
  - Skip the trade if the signal window expires before entry.
  - Skip the trade if price breaks through the stop side before entry.
- Post-entry risk:
  - Hard stop at `stop=`.
  - No widening the stop.
- Profit taking:
  - First partial near `tp1`.
  - Remainder toward `tp2`.
- Time stop:
  - If the strategy issues a time-stop instruction, respect it even if the trade is still open.

## Prop Risk Rules

- Prop account risk should be smaller than the Binance account risk.
- Default manual prop starting point:
  - `0.25%` to `0.50%` account risk per trade.
- If the prop firm has trailing drawdown or daily loss rules, size from those rules first, not from the Binance account size.

## NQ Backtest Status

- Current repo and local DB do not contain `NQ` / `MNQ` intraday data.
- A true NQ backtest needs an external data source with 1-minute history.
- Once 1-minute NQ data is available, the same micro-main research flow can be adapted for a futures-specific runner.
