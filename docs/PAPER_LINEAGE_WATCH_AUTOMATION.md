# PAPER Lineage Watch Automation

`paper_lineage_watch_tick.py` is the unattended runner for lineage sample collection.
It wraps `watch_paper_candidate_drill.py` in a single-tick process so `NO_ELIGIBLE_CANDIDATE` is treated as a healthy idle outcome instead of a failing automation run.
The same tick now also runs `run_paper_exit_monitor.py`, so previously entered `PAPER` positions can emit `PARTIAL_EXIT` / `CLOSED` fills when TP, SL, or expiry conditions are reached.

Current defaults:
- family scope: legacy paper lineage only, currently `sweep_reversal`, `trend_continuation`
- symbol pin: none
- universe: legacy paper lineage universe, not the current MICRO_LIVE USDT 11 route
- cadence: every 15 minutes
- behavior: if an eligible candidate appears, submit it via `PAPER`
- close handling: after each watch tick, evaluate open `PAPER` lineage positions for TP/SL/expiry exits

## Manual run

```bash
/Users/yumin/Documents/trading/.venv/bin/python /Users/yumin/Documents/trading/scripts/paper_lineage_watch_tick.py
```

By default stdout is a compact one-line summary for launchd log hygiene.
Use `--stdout-mode json` when a manual run needs the full payload on stdout; the full latest payload is always written to `latest_launchd_run.json`.

Artifacts:
- latest automation run:
  - `/Users/yumin/Documents/trading/reports/operations/paper_candidate_watch/latest_launchd_run.json`
- markdown watch reports:
  - `/Users/yumin/Documents/trading/reports/operations/paper_candidate_watch/automation/`
- launchd stdout:
  - `/Users/yumin/Documents/trading/reports/operations/paper_candidate_watch/launchd.out.log`
- launchd stderr:
  - `/Users/yumin/Documents/trading/reports/operations/paper_candidate_watch/launchd.err.log`
- archived launchd log tails:
  - `/Users/yumin/Documents/trading/reports/operations/paper_candidate_watch/log_archive/`

## launchd

Repository plist:
- `/Users/yumin/Documents/trading/launchd/com.yumin.trading.paper-lineage-watch.plist`

Install:

```bash
mkdir -p /Users/yumin/Library/LaunchAgents
cp /Users/yumin/Documents/trading/launchd/com.yumin.trading.paper-lineage-watch.plist /Users/yumin/Library/LaunchAgents/com.yumin.trading.paper-lineage-watch.plist
launchctl bootstrap gui/$(id -u) /Users/yumin/Library/LaunchAgents/com.yumin.trading.paper-lineage-watch.plist
launchctl kickstart -k gui/$(id -u)/com.yumin.trading.paper-lineage-watch
```

Status:

```bash
launchctl print gui/$(id -u)/com.yumin.trading.paper-lineage-watch
```

Unload:

```bash
launchctl bootout gui/$(id -u)/com.yumin.trading.paper-lineage-watch
```

## Interpretation

- `tick_status=found_eligible_candidate`
  - an eligible lineage candidate appeared and the watcher attempted the PAPER submit path.
- `tick_status=no_eligible_candidate`
  - no eligible lineage candidate appeared during this tick; this is normal and still counted as a healthy run.
- `watch_process_return_code=0`
  - watcher found an eligible candidate.
- `watch_process_return_code=1`
  - watcher found no eligible candidate.
- `paper_exit_monitor.closed_events > 0`
  - at least one open `PAPER` position closed during the same tick.
- `paper_exit_monitor.partial_exit_events > 0`
  - at least one open `PAPER` position advanced to a partial exit during the same tick.

This automation does not replace stage readiness alerts.
It exists to keep accumulating universe-wide lineage closes so the stage monitor can eventually flip:
- `lineage_gate_ready`
- `candidate_gate_ready`
- `edge_sample_gate_ready`
- `all_readiness_gates_ready`
