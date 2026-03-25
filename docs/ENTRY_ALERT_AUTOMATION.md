# Entry Surface Automation

`notify_entry_surface.py` reads the live `/portfolio/budget` server surface and classifies rows into:

- `ACTIONABLE_ENTRY`
- `BLOCKED_SETUP`
- `RESEARCH_ONLY_SETUP`

The alert headline now starts with the same `approval_strip: approve -> align -> act` line exposed by `/portfolio/budget`, the `contract_trace` line repeats the same `approve / align / act` contract before appending raw runtime/playbook fields for debugging, an `edge_experiment` line carries the current split-test focus (`edge_state`, preferred entry timing, preferred execution style), and an `edge_evolution` line carries the current allocation/promotion posture (`evolution_state`, `recommended_action`, `allocation_bias`, `promotion_candidate_*`).

Read the alert as a compressed surface, not as the full experiment policy. The current runtime still enforces:

- one active split experiment at a time
- sample-target gating before stronger `promote / reduce / kill-review` interpretation
- regime dependency guarding before promotion is treated as general edge

It now also carries a `review_followup_ledger` line from the same portfolio surface. Read that line as packet history, not as a fresh recommendation:

- `generated`
  - the last packet generation status (`READY`, `NO_TARGET`, `NO_REVIEW_ACTION_AVAILABLE`, etc.)
- `decision`
  - the latest operator-confirmed follow-up transition if one was appended later
- `effective`
  - the most recent status after combining generation + later decision transitions
- `action`
  - the last packet's selected review action
- `entries`
  - how many recent packet generations exist in the current summary window
- `cmd`
  - the runnable `scripts/run_split_review_followup.py` command that produced the packet

Candidate rows still append row-level `edge=` and `split=` hints when the portfolio surface has symbol-specific experiment focus. The alert's own dedupe state file is separate from `review_followup_ledger`; the state file suppresses repeated notifications, while the ledger records split/evolution packet history across surfaces.

Operational reading rules:

- If the alert shows a preferred `entry_timing` and `execution_style` at the same time, do not open both experiments in parallel. Check `operator_action_priority.experiment_execution_policy` on dashboard or validation and execute only the active split.
- If the preferred branch looks better but the validation surface still says `sample_maturity_state=pre_directional`, `directional_only`, or `review_ready`, keep collecting closes before treating it as a rollout conclusion.
- If validation shows `regime_dependency_state=regime_dependent` or `edge_evolution_rule.regime_guard_state=promotion_blocked_by_regime_dependency`, treat the alert as regime-specific context only, not as a universal promotion signal.

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
