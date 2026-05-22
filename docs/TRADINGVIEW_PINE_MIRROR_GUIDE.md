# TradingView Pine Mirror Guide

## Goal

Use a TradingView-native indicator that mirrors the server strategy's core context:

- HTF regime
- transition / risk state
- recent LP/FVG zones
- best current setup direction / grade / plan guide

This script is a mirror, not the execution source-of-truth.

## Authority boundaries

- `chart score != deployment approval`
- `chart plan != live order instruction`
- `/indicators/* operator_summary = runtime/portfolio truth summary`
- final rollout approval still comes from `POST /validation/report` and `POST /operations/checklist`

## Source of truth

Keep the server authoritative for:

- `GET /indicators/summary`
- `GET /indicators/chart`
- `GET /indicators/pine`
- `GET /plans/top`
- `GET /scanner/top`
- `POST /execution/plans/preview`
- `POST /execution/approve-plan`
- `POST /validation/report`
- `POST /operations/checklist`

The Pine script is for chart context and faster visual triage. Runtime tradeability should be read from `operator_summary`, and execution translation/approval should be read from the execution preview and approval APIs.

## Get the script

From the local API:

```bash
curl -s "http://127.0.0.1:8000/indicators/pine-script" -o trading_engine_v1_mirror.pine
```

Or from the repo file:

```bash
/Users/yumin/Documents/trading/scripts/tradingview/trading_engine_v1_mirror.pine
```

## Add it to TradingView

1. Open TradingView.
2. Open Pine Editor.
3. Paste the contents of `trading_engine_v1_mirror.pine`.
4. Save the script.
5. Click `Add to chart`.

## Recommended chart settings

- chart timeframe: `5m`
- script input `Regime timeframe`: `15`
- `Zone max age (bars)`: default `48` (4 hours on 5m), keep relatively short for scalp use
- `Show best setup plan`: enabled
- `Show dashboard`: enabled
- `Dashboard mode`: start with `Compact`, switch to `Detailed` only when debugging

## What the script shows

### Background

Background color reflects the current risk state:

- `green`: normal
- `yellow`: guarded
- `orange`: high friction / jump risk
- `red`: blocked / transition-confirmed

### Core lines

- `EMA21`
- `EMA55`
- `ATR upper/lower`
- best setup `entry / stop / tp1 / tp2 / tp3`

### Zones

- recent liquidity pool support / resistance zones
- recent bullish / bearish FVG zones
- zone age is deliberately capped so stale zones do not dominate scalp usage

### Dashboard

The table shows:

- regime
- bias
- risk
- momentum
- chart-side operator priority
- family
- why now
- blocked reason
- score breakdown
- best setup direction / grade / entry model
- approximate `Est. win` and `Est. EV`
- authority note (`mirror only, check scanner/ops`)

Recommended reading order in `Compact` mode:

1. `State`
2. `Bias`
3. `Setup`
4. `Chart-side operator priority`
5. `Entry`
6. `Edge`
7. `Zone`

`Chart-side operator priority` is still chart-side only. It is a mirror-side reading hint such as `HOLD`, `WAIT`, `RESEARCH`, `CONFIRM`, or `SETUP`, and it does not replace server-side `Top Operator Action`.

### Alerts

The script exposes three native TradingView alert conditions:

- `Trading Engine Mirror Long`
- `Trading Engine Mirror Short`
- `Trading Engine Mirror Blocked`

Use them as chart-side awareness only. Final server-side execution approval still comes from the API.

## How to use it with the server

1. Load the Pine script on a `5m` chart.
2. Use it to understand current context and the nearest setup.
3. Treat `Chart-side operator priority` as a chart-side proxy only:
   - `HOLD`: blocked on chart-side mirror, check server approval/runtime truth because server wins
   - `WAIT`: no chart-side setup yet
   - `RESEARCH`: range-style chart setup, not live approval
   - `CONFIRM`: guarded chart setup, confirm with scanner/ops first
   - `SETUP`: chart-side setup exists, but server still decides tradeability
4. Confirm actual tradable candidates with:

```bash
curl -s "http://127.0.0.1:8000/scanner/top?universe=micro_live_usdt_11&limit=11" | jq
```

5. Confirm the concrete plan with:

```bash
curl -s "http://127.0.0.1:8000/plans/top?symbol=BTCUSDT&tf=5m&limit=5&refresh=true" | jq
```

6. Read the runtime/portfolio truth summary with:

```bash
curl -s "http://127.0.0.1:8000/indicators/summary?symbol=BTCUSDT&refresh=true" | jq '.operator_summary'
```

7. Preview the execution contract and current approval with:

```bash
curl -s -X POST "http://127.0.0.1:8000/execution/plans/preview" -H "content-type: application/json" -d '{"plan_id":"<PLAN_ID>"}' | jq
curl -s -X POST "http://127.0.0.1:8000/execution/approve-plan" -H "content-type: application/json" -d '{"plan_id":"<PLAN_ID>"}' | jq
```

8. Use validation and ops gates before trusting live execution:

```bash
curl -s -X POST "http://127.0.0.1:8000/validation/report?symbol=BTCUSDT" | jq
curl -s -X POST "http://127.0.0.1:8000/operations/checklist?symbol=BTCUSDT&universe=micro_live_usdt_11" | jq
```

## TradingView -> Server Read Order

Read the chart first, but confirm runtime truth and approval on the server in this order.

For the full operator session flow after chart triage, follow [docs/AUTO_TRADING_OPERATING_RUNBOOK.md](/Users/yumin/Documents/trading/docs/AUTO_TRADING_OPERATING_RUNBOOK.md).

1. `GET /execution/operator-ui`
   - `5-Second Operator Kernel`
   - `Decision Summary`
   - `Top Operator Action`
   - `Top Opportunity / Top Blocker`
   - `Current Operating State`
2. `GET /execution/operator-dashboard`
   - runtime and portfolio truth summary
   - execution / family / mode / advisory summaries
   - reconciliation / open order / open position checks
3. `POST /validation/report`
   - deployment and playbook language
   - execution / family / mode / alpha-research evidence
   - operator action priority summary
4. `POST /operations/checklist`
   - final operational review
   - deployment/playbook alignment
   - non-blocking warnings before rollout

When you move from TradingView to the operator surfaces, read them in the same order: 5-Second Operator Kernel, Decision Summary, Top Operator Action, Top Opportunity / Top Blocker, and Current Operating State before dropping into plans, guidance, and detailed operations sections.

1. `5-Second Operator Kernel`
2. `Decision Summary`
3. `Top Operator Action`
4. `Top Opportunity / Top Blocker`
5. `Current Operating State`

## How to read chart-side Operator Priority

`Chart-side operator priority` inside the Pine mirror is still chart-side only. It is a proxy hint, not the server's `Top Operator Action`.

- `HOLD`: blocked on chart-side mirror, so check `operator-ui` and `validation/report` before trusting any setup
- `WAIT`: no chart-side setup yet, so keep monitoring `operator-dashboard`
- `RESEARCH`: treat as chart-side research only, then confirm with server summaries and alpha-research surfaces
- `CONFIRM`: guarded chart setup, so confirm with `scanner/top`, `operator-ui`, and approval surfaces
- `SETUP`: chart-side setup exists, but the server still decides tradeability and approval

Example: the chart shows `CONFIRM`, but the server-side `Top Operator Action` says `review_execution_drag_before_expansion`. In that case, keep the chart setup as context only and follow the server-side review first.

`RESEARCH` inside the Pine mirror means a chart-side research queue hint, not live approval.
If the chart shows `RESEARCH`, treat it as a prompt to check the server-side alpha-research next step rather than a trade permission.
Example: the chart shows `RESEARCH`, and the server-side `Alpha-Research Next Step` says `softening_review`. Treat the chart as a research queue hint, then continue the actual research progression on the server.

Recommended server-side follow-up for `RESEARCH`:

1. `GET /execution/operator-ui`
   - read `Current Operating State`
   - read `Alpha-Research Next Step`
2. `POST /validation/report`
   - read `alpha_research_pipeline_summary`
   - read `operator_action_priority_summary`
3. `GET /validation/alpha-research`
   - read evidence, softening review, and promotion watchlist

Chart-side `RESEARCH` says "study this setup on the server", not "trade this setup now".
`Top Operator Action` is not a live submit instruction. `Alpha-Research Next Step` is not trade approval. Chart-side `RESEARCH` is not a permission to enter.

If the chart-side priority and the server disagree, the server wins.

## Important limitation

TradingView Pine cannot pull the server's live JSON payload directly.

So this script is:

- a native TradingView mirror
- an approximation of the server strategy
- intentionally not used as the final execution engine
- allowed to provide chart-side operator-priority hints, but not final rollout approval

If the Pine script and the server disagree, follow the server.
