# Operator Session Brief Automation

`notify_operator_session_brief.py` can already render a dry-run handoff message.
The handoff now carries the same `5-Second Operator Kernel` fields as the UI home top section: `kernel_verdict`, `money_leak_r`, `strongest_drag_source`, `outcome_control_tier`, `rollout_recommendation`, and the derived `candidate_surface_priority`.
It now also carries the same `Approval Strip` ordering as the UI home top section, so the brief headline and notifier first lines start with `approve -> align -> act`.
It now also carries `edge_experiment` focus from the funnel snapshot: `edge_state`, `entry_timing_focus`, and `execution_style_focus`, so split-test follow-up survives shift handoff.
It now also carries `edge_evolution` focus from the funnel snapshot: `evolution_state`, `recommended_action`, and `allocation_bias`, so reduction, promotion, and kill-review posture survives shift handoff instead of staying trapped inside validation only.
It now also carries representative accepted and blocked candidate focus from `portfolio_summary`, so the handoff preserves row-level `edge_experiment_focus` instead of only the top-level funnel hint.
It now also carries `entry_timing_review_target` and `execution_style_review_target`, so the handoff can say which `split review action -> candidate row` pairing should be reviewed next.
Those target lines now also include the ready-to-run `scripts/run_split_review_followup.py` command, so shift handoff can move straight from review target to review packet generation.
Candidate and review-target handoff lines render legacy `ACTIONABLE_ENTRY` source rows as `CONTEXT_REVIEW_SETUP`. Session brief candidates are review context only; they are not live order candidates. Treat live ordering truth as the entry surface `LIVE_ORDER_CANDIDATE` count and the runtime promotion route contract.
The brief now also carries `top_action_followup_command`, so if `operator_action_priority.top_action` is an edge-evolution review such as `reduce_baseline_allocation_review`, the handoff still exposes one runnable packet command instead of only the row-level split targets.
It now also carries `review_followup_ledger.last_status`, `last_action`, `recent_entry_count`, and `last_followup_command`, so the handoff shows whether the latest review packet actually resolved a runnable target or stalled at `NO_TARGET`.
The markdown brief now uses the same `approve -> align -> act` wording again inside `Surface Alignment`, so `dashboard`, `validation`, and `checklist` detail lines do not fall back to raw `deployment_go_no_go / playbook_action` phrasing.
The notifier detail lines now follow the same rule, so `dashboard`, `validation`, and `checklist` are summarized as per-surface `approve / align / act` lines instead of raw deployment and playbook dumps.
Use the wrapper below when you want a workspace-local manual run, so channel, brief mode, state file, and latest run artifact stay in one place.

The wrapper prefers `/Users/yumin/Documents/trading/.venv/bin/python` and falls back to `python3` if the virtualenv binary is not present. Installed `launchd` jobs do not use this wrapper; they run the durable runtime copy under `/Users/yumin/Library/Application Support/trading/runtime_src` with `/Users/yumin/Library/Application Support/trading/runtime_venv/bin/python`.
The notifier uses a non-overlap lock and a generation timeout. If a previous brief is still running, the next tick writes `reason=operator_session_brief_already_running` and exits without sending. If snapshot generation times out or fails, the latest artifact records `reason=brief_generation_failed` and the notifier does not dispatch.

## Wrapper

```bash
chmod +x /Users/yumin/Documents/trading/scripts/run_operator_session_brief_tick.sh
bash /Users/yumin/Documents/trading/scripts/run_operator_session_brief_tick.sh
```

## Environment Variables

- `OPERATOR_BRIEF_SYMBOL`
  - default: `BTCUSDC`
- `OPERATOR_BRIEF_UNIVERSE`
  - default: `usdc_perp_top30`
- `OPERATOR_BRIEF_DAYS`
  - default: `7`
- `OPERATOR_BRIEF_PORTFOLIO_LIMIT`
  - default: `5`
- `OPERATOR_BRIEF_INTENT_LIMIT`
  - default: `5`
- `OPERATOR_BRIEF_RECONCILE_LIMIT`
  - default: `5`
- `OPERATOR_BRIEF_CHANNEL`
  - default: `system`
  - allowed: `system`, `discord`
- `OPERATOR_BRIEF_MODE`
  - default: `shift-start`
  - allowed: `shift-start`, `shift-end`
- `OPERATOR_BRIEF_STATE_FILE`
  - optional override for dedupe state file
  - default: mode/channel별 `last_alert_state_<mode>_<channel>.json`
- `OPERATOR_BRIEF_LATEST_RUN_FILE`
  - optional override for the latest wrapper artifact
- `OPERATOR_BRIEF_LOCK_FILE`
  - optional override for the non-overlap lock file
  - default: mode별 `operator_session_brief_<mode>.lock`
- `OPERATOR_BRIEF_RUN_TIMEOUT_SECONDS`
  - default: `90`
  - maximum time allowed for `generate_operator_session_brief.py` before the notifier records a clean failure artifact
- `OPERATOR_BRIEF_DISCORD_WEBHOOK_URL`
  - optional Discord webhook override
- `OPERATOR_BRIEF_DRY_RUN=1`
  - render the message and latest artifact without sending
- `OPERATOR_BRIEF_ALLOW_LIVE_SEND=1`
  - required in addition to unsetting `OPERATOR_BRIEF_DRY_RUN` before any real external send is allowed
- `OPERATOR_BRIEF_FORCE_SEND=1`
  - bypass dedupe suppression for one run

## Artifacts

Workspace manual wrapper artifacts:

- latest shift-start wrapper payload:
  - `/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/latest_operator_session_brief_shift_start.json`
- latest shift-end wrapper payload:
  - `/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/latest_operator_session_brief_shift_end.json`
- dedupe state:
  - `/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/last_alert_state_shift_start_system.json`
  - `/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/last_alert_state_shift_end_system.json`
- non-overlap locks:
  - `/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/operator_session_brief_shift_start.lock`
  - `/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/operator_session_brief_shift_end.lock`
- generated markdown brief:
  - `/Users/yumin/Documents/trading/reports/operations/operator_session_briefs/`
- supporting divergence snapshot:
  - `/Users/yumin/Documents/trading/reports/operations/operator_surface_divergence/`

Installed launchd runtime artifacts:

- latest shift-start payload:
  - `/Users/yumin/Library/Application Support/trading/runtime_src/reports/operations/operator_session_briefs/latest_operator_session_brief_shift_start.json`
- latest shift-end payload:
  - `/Users/yumin/Library/Application Support/trading/runtime_src/reports/operations/operator_session_briefs/latest_operator_session_brief_shift_end.json`
- launchd stdout/stderr:
  - `/Users/yumin/Library/Application Support/trading/runtime_src/reports/operations/operator_session_briefs/launchd.shift_start.out.log`
  - `/Users/yumin/Library/Application Support/trading/runtime_src/reports/operations/operator_session_briefs/launchd.shift_start.err.log`
  - `/Users/yumin/Library/Application Support/trading/runtime_src/reports/operations/operator_session_briefs/launchd.shift_end.out.log`
  - `/Users/yumin/Library/Application Support/trading/runtime_src/reports/operations/operator_session_briefs/launchd.shift_end.err.log`

If live send is not allowed, the latest payload can show `delivery.reason=live_send_not_allowed` and no dedupe state file may be written. That is not unhealthy by itself; automation health should treat the latest payload as the freshness source and require the dedupe state only after an actual delivery.

## Quick Checks

Run once with default `shift-start`:

```bash
bash /Users/yumin/Documents/trading/scripts/run_operator_session_brief_tick.sh
```

Run `shift-start` in dry-run mode:

```bash
OPERATOR_BRIEF_DRY_RUN=1 /bin/bash /Users/yumin/Documents/trading/scripts/run_operator_session_brief_tick.sh
```

Run `shift-end` in dry-run mode:

```bash
OPERATOR_BRIEF_DRY_RUN=1 OPERATOR_BRIEF_MODE=shift-end /bin/bash /Users/yumin/Documents/trading/scripts/run_operator_session_brief_tick.sh
```

Force one send:

```bash
OPERATOR_BRIEF_FORCE_SEND=1 OPERATOR_BRIEF_ALLOW_LIVE_SEND=1 /bin/bash /Users/yumin/Documents/trading/scripts/run_operator_session_brief_tick.sh
```

Send only to Discord:

```bash
OPERATOR_BRIEF_CHANNEL=discord OPERATOR_BRIEF_DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." \
  /bin/bash /Users/yumin/Documents/trading/scripts/run_operator_session_brief_tick.sh
```

Inspect the latest wrapper payload:

```bash
cat /Users/yumin/Documents/trading/reports/operations/operator_session_briefs/latest_operator_session_brief_shift_start.json
```

Inspect the dedupe state:

```bash
cat /Users/yumin/Documents/trading/reports/operations/operator_session_briefs/last_alert_state_shift_start_system.json
```

Check launchd automation health against the installed runtime copy:

```bash
'/Users/yumin/Library/Application Support/trading/runtime_venv/bin/python' \
  '/Users/yumin/Library/Application Support/trading/runtime_src/scripts/check_operator_session_brief_automation.py' \
  --strict
```

Check delivery channel preflight:

```bash
'/Users/yumin/Library/Application Support/trading/runtime_venv/bin/python' \
  '/Users/yumin/Library/Application Support/trading/runtime_src/scripts/check_operator_session_brief_delivery_preflight.py' \
  --strict
```

## Cron Example

Weekday shift-start dry-run every 15 minutes:

```cron
*/15 * * * 1-5 cd /Users/yumin/Documents/trading && OPERATOR_BRIEF_DRY_RUN=1 OPERATOR_BRIEF_MODE=shift-start /bin/bash /Users/yumin/Documents/trading/scripts/run_operator_session_brief_tick.sh >> /Users/yumin/Documents/trading/reports/operations/operator_session_briefs/cron_shift_start.log 2>&1
```

Weekday shift-end dry-run every 15 minutes:

```cron
*/15 * * * 1-5 cd /Users/yumin/Documents/trading && OPERATOR_BRIEF_DRY_RUN=1 OPERATOR_BRIEF_MODE=shift-end /bin/bash /Users/yumin/Documents/trading/scripts/run_operator_session_brief_tick.sh >> /Users/yumin/Documents/trading/reports/operations/operator_session_briefs/cron_shift_end.log 2>&1
```

Weekday live system fanout:

```cron
*/15 * * * 1-5 cd /Users/yumin/Documents/trading && OPERATOR_BRIEF_CHANNEL=system /bin/bash /Users/yumin/Documents/trading/scripts/run_operator_session_brief_tick.sh >> /Users/yumin/Documents/trading/reports/operations/operator_session_briefs/cron_live.log 2>&1
```

## launchd Example

Use `launchd` when you want separate `shift-start` and `shift-end` handoff loops while you are logged in on this Mac.

Repository plists:
- `/Users/yumin/Documents/trading/launchd/com.yumin.trading.operator-brief-shift-start.plist`
- `/Users/yumin/Documents/trading/launchd/com.yumin.trading.operator-brief-shift-end.plist`

The plists call `notify_operator_session_brief.py --quiet` directly through the runtime virtualenv Python and only pin `OPERATOR_BRIEF_MODE`. Keep delivery secrets and delivery-mode toggles out of the plist and inject them through `launchctl setenv`.

Expected plist execution contract:

- python: `/Users/yumin/Library/Application Support/trading/runtime_venv/bin/python`
- script: `/Users/yumin/Library/Application Support/trading/runtime_src/scripts/notify_operator_session_brief.py`
- working directory: `/Users/yumin/Library/Application Support/trading/runtime_src`
- standard output/error: `/Users/yumin/Library/Application Support/trading/runtime_src/reports/operations/operator_session_briefs/launchd.*.log`

Set the shared channel in your user launchd environment:

```bash
launchctl setenv OPERATOR_BRIEF_CHANNEL system
```

Optional Discord override:

```bash
launchctl setenv OPERATOR_BRIEF_DISCORD_WEBHOOK_URL "https://discord.com/api/webhooks/..."
launchctl setenv OPERATOR_BRIEF_CHANNEL discord
```

Optional dry-run mode:

```bash
launchctl setenv OPERATOR_BRIEF_DRY_RUN 1
```

If you want live delivery, unset dry-run:

```bash
launchctl unsetenv OPERATOR_BRIEF_DRY_RUN
launchctl setenv OPERATOR_BRIEF_ALLOW_LIVE_SEND 1
```

If you want to disable live delivery again:

```bash
launchctl unsetenv OPERATOR_BRIEF_ALLOW_LIVE_SEND
launchctl setenv OPERATOR_BRIEF_DRY_RUN 1
```

Suggested paths:
- `/Users/yumin/Library/LaunchAgents/com.yumin.trading.operator-brief-shift-start.plist`
- `/Users/yumin/Library/LaunchAgents/com.yumin.trading.operator-brief-shift-end.plist`

Install and load:

```bash
cp /Users/yumin/Documents/trading/launchd/com.yumin.trading.operator-brief-shift-start.plist ~/Library/LaunchAgents/com.yumin.trading.operator-brief-shift-start.plist
cp /Users/yumin/Documents/trading/launchd/com.yumin.trading.operator-brief-shift-end.plist ~/Library/LaunchAgents/com.yumin.trading.operator-brief-shift-end.plist
launchctl bootout "gui/$(id -u)/com.yumin.trading.operator-brief-shift-start" 2>/dev/null || true
launchctl bootout "gui/$(id -u)/com.yumin.trading.operator-brief-shift-end" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.yumin.trading.operator-brief-shift-start.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.yumin.trading.operator-brief-shift-end.plist
launchctl enable "gui/$(id -u)/com.yumin.trading.operator-brief-shift-start"
launchctl enable "gui/$(id -u)/com.yumin.trading.operator-brief-shift-end"
launchctl kickstart -k "gui/$(id -u)/com.yumin.trading.operator-brief-shift-start"
launchctl kickstart -k "gui/$(id -u)/com.yumin.trading.operator-brief-shift-end"
```

Unload:

```bash
launchctl bootout "gui/$(id -u)/com.yumin.trading.operator-brief-shift-start"
launchctl bootout "gui/$(id -u)/com.yumin.trading.operator-brief-shift-end"
```

Artifacts:
- `/Users/yumin/Library/Application Support/trading/runtime_src/reports/operations/operator_session_briefs/launchd.shift_start.out.log`
- `/Users/yumin/Library/Application Support/trading/runtime_src/reports/operations/operator_session_briefs/launchd.shift_start.err.log`
- `/Users/yumin/Library/Application Support/trading/runtime_src/reports/operations/operator_session_briefs/launchd.shift_end.out.log`
- `/Users/yumin/Library/Application Support/trading/runtime_src/reports/operations/operator_session_briefs/launchd.shift_end.err.log`
- `/Users/yumin/Library/Application Support/trading/runtime_src/reports/operations/operator_session_briefs/operator_session_brief_automation_health_*.md`
- `/Users/yumin/Library/Application Support/trading/runtime_src/reports/operations/operator_session_briefs/operator_session_brief_delivery_preflight_*.md`
