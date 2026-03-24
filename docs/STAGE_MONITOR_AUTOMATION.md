# Stage Monitor Automation

`ops_stage_board.py` and `notify_stage_change.py` are designed to run together.
Use the wrapper below so the stage snapshot is always written before the Discord notifier runs.
The stage snapshot now also carries per-surface `approve / align / act` summaries for `dashboard`, `validation`, and `checklist`, plus `edge_experiment_review`, `edge_evolution_rule`, `review_followup_ledger`, `top_operator_action_followup_command`, representative accepted/blocked candidate split focus, and explicit `entry_timing_review_target` / `execution_style_review_target` lines.
Those target lines now include the ready-to-run `scripts/run_split_review_followup.py` command, and the notifier message prints the same contract directly before the stage counters.

## Wrapper

```bash
chmod +x /Users/yumin/Documents/trading/scripts/run_stage_monitor_tick.sh
bash /Users/yumin/Documents/trading/scripts/run_stage_monitor_tick.sh
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
      <string>/bin/bash</string>
      <string>/Users/yumin/Documents/trading/scripts/run_stage_monitor_tick.sh</string>
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
