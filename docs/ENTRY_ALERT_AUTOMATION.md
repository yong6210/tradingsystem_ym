# Entry Surface Automation

`notify_entry_surface.py` reads the live `/portfolio/budget` server surface and classifies rows into:

- `ACTIONABLE_ENTRY`
- `BLOCKED_SETUP`
- `RESEARCH_ONLY_SETUP`

The alert headline now starts with the same `approval_strip: approve -> align -> act` line exposed by `/portfolio/budget`, the `contract_trace` line repeats the same `approve / align / act` contract before appending raw runtime/playbook fields for debugging, and an `edge_experiment` line carries the current split-test focus (`edge_state`, preferred entry timing, preferred execution style). Candidate rows now also append row-level `edge=` and `split=` hints when the portfolio surface has symbol-specific experiment focus.

Use the wrapper below so runtime defaults, state file path, and the latest run artifact stay in one place.
The wrapper prefers `/Users/yumin/Documents/trading/.venv/bin/python` and falls back to `python3` if the virtualenv binary is not present.

## Wrapper

```bash
chmod +x /Users/yumin/Documents/trading/scripts/run_entry_surface_tick.sh
bash /Users/yumin/Documents/trading/scripts/run_entry_surface_tick.sh
```

## Environment Variables

- `ENTRY_SURFACE_BASE_URL`
  - default: `http://127.0.0.1:8000`
- `ENTRY_SURFACE_UNIVERSE`
  - default: `usdc_perp_top30`
- `ENTRY_SURFACE_LIMIT`
  - default: `20`
- `ENTRY_SURFACE_MAX_PER_STATUS`
  - default: `3`
- `ENTRY_SURFACE_CHANNEL`
  - default: `discord`
  - allowed: `discord`, `system`
- `ENTRY_SURFACE_SYMBOL`
  - optional symbol pin, for example `BTCUSDC`
- `ENTRY_SURFACE_STATE_FILE`
  - optional override for the dedupe state file
- `ENTRY_SURFACE_DISCORD_WEBHOOK_URL`
  - optional override for the Discord webhook
- `ENTRY_SURFACE_DRY_RUN=1`
  - render the message and latest artifact without sending Discord
- `ENTRY_SURFACE_FORCE_SEND=1`
  - bypass dedupe suppression for one run

## Artifacts

- latest run payload:
  - `/Users/yumin/Documents/trading/reports/operations/entry_surface/latest_entry_alert_run.json`
- dedupe state:
  - `/Users/yumin/Documents/trading/reports/operations/entry_surface/last_alert_state.json`

## Quick Checks

Run once:

```bash
bash /Users/yumin/Documents/trading/scripts/run_entry_surface_tick.sh
```

Run once in dry-run mode:

```bash
ENTRY_SURFACE_DRY_RUN=1 /bin/bash /Users/yumin/Documents/trading/scripts/run_entry_surface_tick.sh
```

Pin one symbol only:

```bash
ENTRY_SURFACE_SYMBOL=BTCUSDC /bin/bash /Users/yumin/Documents/trading/scripts/run_entry_surface_tick.sh
```

Force one send even if the state is unchanged:

```bash
ENTRY_SURFACE_FORCE_SEND=1 /bin/bash /Users/yumin/Documents/trading/scripts/run_entry_surface_tick.sh
```

Inspect the latest run payload:

```bash
cat /Users/yumin/Documents/trading/reports/operations/entry_surface/latest_entry_alert_run.json
```

Inspect the dedupe state:

```bash
cat /Users/yumin/Documents/trading/reports/operations/entry_surface/last_alert_state.json
```

## Cron Example

Every 5 minutes on weekdays:

```cron
*/5 * * * 1-5 cd /Users/yumin/Documents/trading && ENTRY_SURFACE_DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." /bin/bash /Users/yumin/Documents/trading/scripts/run_entry_surface_tick.sh >> /Users/yumin/Documents/trading/reports/operations/entry_surface/cron.log 2>&1
```

Dry-run first:

```cron
*/5 * * * 1-5 cd /Users/yumin/Documents/trading && ENTRY_SURFACE_DRY_RUN=1 /bin/bash /Users/yumin/Documents/trading/scripts/run_entry_surface_tick.sh >> /Users/yumin/Documents/trading/reports/operations/entry_surface/cron.log 2>&1
```
