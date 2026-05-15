# Entry Surface Automation

`notify_entry_surface.py` reads the live `/portfolio/budget?fast=true` server surface and classifies rows into:

- `LIVE_ORDER_CANDIDATE`
- `CONTEXT_REVIEW_SETUP`
- `BLOCKED_SETUP`
- `RESEARCH_ONLY_SETUP`

`LIVE_ORDER_CANDIDATE` is the only section that should be read as a live-order candidate. It means the row matches the current live route contract: symbol, strategy family, entry model, direction, and session. `CONTEXT_REVIEW_SETUP` means the portfolio surface has an accepted candidate, but that candidate is outside the current live route and must not be treated as an automatic order trigger.

Discord dispatch is narrower than the saved report. The tick still writes the full surface to `latest_entry_alert_run.json`, but it only sends Discord when a live order candidate exists or when a live-routable candidate is blocked. Context-only/review-only changes are report-only so they are not mistaken for entry confirmation.

The alert headline starts with `live_order_candidates`, `review_candidates`, and `blocked_live_candidates` so the Discord preview is explicit. The Discord title follows the same split: live candidates become `[중요] ... 라이브 주문 후보 확인`, live-routable blocked candidates become `[주의] ... 라이브 주문 후보 차단`, and zero live/blocked candidates stay `[모니터링] ... 주문 후보 없음`. The second line always carries `order_truth=live_candidate_promotion_readiness`. The `approval_strip: approve -> align -> act` line still mirrors `/portfolio/budget`, the `contract_trace` line repeats the same `approve / align / act` contract before appending raw runtime/playbook fields for debugging, and `order_route_truth` shows the active live route contract used by the alert. The `edge_experiment` line carries the current split-test focus (`edge_state`, preferred entry timing, preferred execution style), and an `edge_evolution` line carries the current allocation/promotion posture (`evolution_state`, `recommended_action`, `allocation_bias`, `promotion_candidate_*`).

The JSON result also exposes the same counts at the top level as `entry_counts`, `live_order_candidates`, `blocked_live_order_candidates`, `context_review_setups`, `blocked_setups`, and `research_only_setups`. `snapshot.counts` remains the full source of truth, but operators and health checks should not need to open the nested snapshot just to verify whether an alert was suppressed because live candidates were zero.

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

Candidate rows still append row-level `edge=` and `split=` hints when the portfolio surface has symbol-specific experiment focus. Rows also carry `live_routable=true/false`. If `live_routable=false`, the row includes `route_reasons`, such as `strategy_family_not_live_route`, `entry_model_not_live_route`, `symbol_not_live_routable`, or `session_not_live_route`.

The alert's own dedupe state file is separate from `review_followup_ledger`; the state file suppresses repeated notifications, while the ledger records split/evolution packet history across surfaces. Dedupe intentionally uses a stable candidate identity: random reroute suffixes like `_r7a1fcc` are stripped from `plan_id`, and recently notified stable states are suppressed for `ENTRY_SURFACE_MIN_REPEAT_MINUTES` minutes by default.

The tick also uses a non-overlap lock. If a previous `/portfolio/budget` request is still running, the next tick exits with `reason=entry_surface_tick_already_running` instead of starting a second request. Source request failures such as `/portfolio/budget` timeouts are written as `reason=source_request_failed` in the latest run payload and do not dispatch Discord.

Operational reading rules:

- Treat `LIVE_ORDER_CANDIDATE=0` as "no live order candidate", even if `CONTEXT_REVIEW_SETUP` is non-zero.
- Treat `blocked_live_order_candidates>0` as "there was a live-routable candidate, but it was blocked before submission." It is not an entry fill and not a submitted order, but it is more important than context-only review.
- Treat `CONTEXT_REVIEW_SETUP` as validation/review context only. It can explain why the portfolio scanner is active, but it is not proof that an order should be submitted.
- If the alert shows a preferred `entry_timing` and `execution_style` at the same time, do not open both experiments in parallel. Check `operator_action_priority.experiment_execution_policy` on dashboard or validation and execute only the active split.
- If the preferred branch looks better but the validation surface still says `sample_maturity_state=pre_directional`, `directional_only`, or `review_ready`, keep collecting closes before treating it as a rollout conclusion.
- If validation shows `regime_dependency_state=regime_dependent` or `edge_evolution_rule.regime_guard_state=promotion_blocked_by_regime_dependency`, treat the alert as regime-specific context only, not as a universal promotion signal.

Use the wrapper below so runtime defaults, state file path, and the latest run artifact stay in one place.
The wrapper prefers `/Users/yumin/Documents/trading/.venv/bin/python`. If the script is run from a runtime source copy without `.venv`, it falls back to `$TRADING_RUNTIME_BASE/runtime_venv/bin/python`, then to `python3`.

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
- `ENTRY_SURFACE_MIN_REPEAT_MINUTES`
  - default: `360`
  - suppresses a recently delivered stable alert state even if transient plan ids changed
- `ENTRY_SURFACE_CHANNEL`
  - default: `discord`
  - allowed: `discord`, `system`
- `ENTRY_SURFACE_SYMBOL`
  - optional symbol pin, for example `BTCUSDC`
- `ENTRY_SURFACE_STATE_FILE`
  - optional override for the dedupe state file
- `ENTRY_SURFACE_LOCK_FILE`
  - optional override for the non-overlap lock file
  - default: `${ENTRY_SURFACE_STATE_FILE}.lock`
- `ENTRY_SURFACE_OUTPUT_FILE`
  - optional override for the latest run artifact
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
