# Stage Monitor Automation

`ops_stage_board.py` and `notify_stage_change.py` are designed to run together.
`stage_monitor_tick.py` is the Python orchestrator that runs both in one process and is the preferred entrypoint for launchd.
Use the wrapper below so the stage snapshot is always written before the Discord notifier runs.
The stage snapshot now also carries per-surface `approve / align / act` summaries for `dashboard`, `validation`, and `checklist`, plus `edge_experiment_review`, `edge_evolution_rule`, `review_followup_ledger`, `top_operator_action_followup_command`, representative accepted/blocked candidate split focus, explicit `entry_timing_review_target` / `execution_style_review_target` lines, and composite readiness gates for `lineage`, `candidate`, `edge_sample`, and `all_ready`.
Those target lines now include the ready-to-run `scripts/run_split_review_followup.py` command, and the notifier message prints the same contract directly before the stage counters.
The launchd configuration now tracks lineage sample progress with `family_global` scope for `sweep_reversal` and `trend_continuation`, so `edge_sample_gate_ready` and `edge_sample_stall` are no longer pinned to `BTCUSDC` closes alone.
`notify_stage_change.py` now emits dedicated events when any readiness gate flips from `false -> true`, including a single `all_readiness_gates_ready` event when the full edge-proof stack is finally ready.

## Wrapper

```bash
chmod +x /Users/yumin/Documents/trading/scripts/run_stage_monitor_tick.sh
bash /Users/yumin/Documents/trading/scripts/run_stage_monitor_tick.sh
```

Direct Python entrypoint:

```bash
/Users/yumin/Documents/trading/.venv/bin/python /Users/yumin/Documents/trading/scripts/stage_monitor_tick.py
```

Environment variables:
- `STAGE_MONITOR_DISCORD_WEBHOOK_URL`
  - optional override for the Discord webhook
- `STAGE_MONITOR_DRY_RUN=1`
  - run the notifier in dry-run mode without sending Discord messages

Artifacts:
- current stage snapshot:
  - `/Users/yumin/Documents/trading/reports/operations/stage_monitor/current_stage.json`
- latest board output:
  - `/Users/yumin/Documents/trading/reports/operations/stage_monitor/latest_stage_board.json`
- last alert state:
  - `/Users/yumin/Documents/trading/reports/operations/stage_monitor/last_alert_state.json`

## launchd example

Use `launchd` when you want the monitor to run every few minutes while you are logged in on this Mac.

Repository plist:
- `/Users/yumin/Documents/trading/launchd/com.yumin.trading.stage-monitor.plist`

The plist does not hardcode the Discord webhook. Keep secrets out of the plist and inject the webhook with `launchctl setenv` or a shell export before you load it.

Set the webhook in your user launchd environment:

```bash
launchctl setenv STAGE_MONITOR_DISCORD_WEBHOOK_URL "https://discord.com/api/webhooks/..."
```

Optional dry-run mode:

```bash
launchctl setenv STAGE_MONITOR_DRY_RUN 1
```

If you want live Discord delivery, unset dry-run:

```bash
launchctl unsetenv STAGE_MONITOR_DRY_RUN
```

Current plist contents:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.yumin.trading.stage-monitor</string>

    <key>ProgramArguments</key>
    <array>
      <string>/Users/yumin/Documents/trading/.venv/bin/python</string>
      <string>/Users/yumin/Documents/trading/scripts/stage_monitor_tick.py</string>
      <string>--lineage-sample-scope</string>
      <string>family_global</string>
      <string>--lineage-families</string>
      <string>sweep_reversal,trend_continuation</string>
      <string>--lineage-proof-goal-closed-trades</string>
      <string>100</string>
      <string>--lineage-sample-days</string>
      <string>180</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/yumin/Documents/trading</string>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/yumin/Documents/trading/reports/operations/stage_monitor/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/yumin/Documents/trading/reports/operations/stage_monitor/launchd.err.log</string>
  </dict>
</plist>
```

Suggested path:
- `/Users/yumin/Library/LaunchAgents/com.yumin.trading.stage-monitor.plist`

Install and load:

```bash
cp /Users/yumin/Documents/trading/launchd/com.yumin.trading.stage-monitor.plist ~/Library/LaunchAgents/com.yumin.trading.stage-monitor.plist
launchctl load ~/Library/LaunchAgents/com.yumin.trading.stage-monitor.plist
launchctl start com.yumin.trading.stage-monitor
```

Unload:

```bash
launchctl unload ~/Library/LaunchAgents/com.yumin.trading.stage-monitor.plist
```

The previous shell-wrapper variant could fail under `~/Documents` with `Operation not permitted`.
The current plist runs Python directly to avoid that shell-level failure mode.
If you still see a `Documents` privacy denial, the blocker is the launch context rather than the stage monitor code.

Old shell-wrapper failure example:

```text
/bin/bash: /Users/yumin/Documents/trading/scripts/run_stage_monitor_tick.sh: Operation not permitted
```

When that happens, the stage alert code is fine; the blocker is the launch context. Use a runner with access to the workspace, or move the workspace out of `~/Documents` before relying on unattended launchd execution.

## cron example

Use `cron` when you want a simple repeating trigger.

Every 5 minutes on weekdays:

```cron
*/5 * * * 1-5 cd /Users/yumin/Documents/trading && STAGE_MONITOR_DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." /bin/bash /Users/yumin/Documents/trading/scripts/run_stage_monitor_tick.sh >> /Users/yumin/Documents/trading/reports/operations/stage_monitor/cron.log 2>&1
```

If you prefer to inspect without sending Discord alerts first:

```cron
*/5 * * * 1-5 cd /Users/yumin/Documents/trading && STAGE_MONITOR_DRY_RUN=1 /bin/bash /Users/yumin/Documents/trading/scripts/run_stage_monitor_tick.sh >> /Users/yumin/Documents/trading/reports/operations/stage_monitor/cron.log 2>&1
```

## Quick checks

Run once:

```bash
bash /Users/yumin/Documents/trading/scripts/run_stage_monitor_tick.sh
```

Run once in dry-run mode:

```bash
STAGE_MONITOR_DRY_RUN=1 /bin/bash /Users/yumin/Documents/trading/scripts/run_stage_monitor_tick.sh
```

Inspect the latest stage:

```bash
cat /Users/yumin/Documents/trading/reports/operations/stage_monitor/latest_stage_board.json
```

Inspect the last notifier state:

```bash
cat /Users/yumin/Documents/trading/reports/operations/stage_monitor/last_alert_state.json
```
