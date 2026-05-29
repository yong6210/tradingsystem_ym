# Trading Engine v1

Verification-first trading engine that separates chart context, runtime candidate ranking, deployment approval, and live execution truth.
The current live posture is verification-first: runtime candidates can be surfaced across the configured MICRO_LIVE families, but live order authority still comes from validation, operations checklist, safety, and liquidity gates.

Primary audience: operators first, contributors second.

## What This System Is

Trading Engine v1 is a verification-first trading engine for operator-led automated trading.

- It treats `POST /validation/report` and `POST /operations/checklist` as the final approval surfaces.
- It treats scanner, portfolio, and operator surfaces as runtime decision support, not order authority by themselves.
- It currently operates the `session_impulse_retest` MICRO_LIVE route while keeping legacy A/B language as research context only.
- It tracks execution quality, fills, positions, alerts, and reconciliation as first-class operational signals.
- It keeps quality-gate near-miss candidates in a research backlog via `/validation/alpha-research` instead of silently dropping them.

If you only remember one rule: chart and scanner views explain what the engine sees, but rollout approval still comes from validation plus operations checklist.

## Session Impulse Retest Runtime Status

As of `2026-05-20`, the active MICRO_LIVE route is **USDT 11 symbols + `session_impulse_retest` + `CONFIRM` + structure-buffered exits**.

Current `session_impulse_retest` live universe:

- `ADAUSDT`, `ATOMUSDT`, `BTCUSDT`, `FETUSDT`, `INJUSDT`, `LINKUSDT`, `LTCUSDT`, `NEARUSDT`, `RUNEUSDT`, `SUIUSDT`, `ZECUSDT`

Important operating rules for this family:

- `session_impulse_retest` runtime audits are recorded only for tracked symbols in the family allowlist.
- `session_impulse_retest` only accepts a 1m retest entry within 3 minutes of the 5m setup bar. The 2026-05-10 3-year loss attribution showed retests after 3 minutes were consistently negative across years, so late retests are no longer eligible for live or replay entries.
- If stop distance is already high (`risk_atr >= 1.0`), the 1m retest must arrive within 2 minutes. The 2026-05-10 loss replay showed high-risk retests that only appeared on minute 3 had negative contribution.
- `/health/ready` now checks:
  - API dependencies
  - disk free space for the runtime database path
  - `worker_loop` fresh heartbeat, `ok` status, and live PID
  - `worker_ws` fresh heartbeat, `ok` status, live PID, and no-message timeout
  - fresh `1m` and `5m` candles for the current live symbol set
- `worker_ws` heartbeat includes processed message count, reconnect count, ingest errors, and skipped reverse-timestamp candles.
- `session_impulse_retest` runtime diagnosis should be read from the audit table, not guessed from scanner output alone.

Primary runtime scripts:

- stack status:
  - [/Users/yumin/Documents/trading/scripts/check_runtime_stack.sh](/Users/yumin/Documents/trading/scripts/check_runtime_stack.sh)
  - uses `~/Library/Application Support/trading/runtime_venv` + `~/Library/Application Support/trading/runtime_src` automatically when that durable runtime exists, so diagnostics still work when the workspace `.venv` or source tree is slow to read
- stack restart:
  - [/Users/yumin/Documents/trading/scripts/restart_runtime_stack.sh](/Users/yumin/Documents/trading/scripts/restart_runtime_stack.sh)
  - clears stale worker heartbeats and exits non-zero unless `/health/ready` reaches `ready`
- durable stack restart:
  - [/Users/yumin/Documents/trading/scripts/restart_runtime_stack_tmp.sh](/Users/yumin/Documents/trading/scripts/restart_runtime_stack_tmp.sh)
  - starts API, loop worker, and WS worker from `~/Library/Application Support/trading`, using the durable DB, reports, archives, logs, and heartbeats there
  - rotates `trading_api.log`, `trading_worker_loop.log`, and `trading_worker_ws.log` before restart when a log exceeds `TRADING_LOG_ROTATE_MAX_BYTES` (default `104857600`) and keeps `TRADING_LOG_ROTATE_KEEP` rotated files (default `5`)
- durable stack bootstrap:
  - [/Users/yumin/Documents/trading/scripts/bootstrap_durable_runtime.sh](/Users/yumin/Documents/trading/scripts/bootstrap_durable_runtime.sh)
  - creates the durable venv/source/data/report layout without installing the package editable into the workspace
- durable stack watchdog:
  - [/Users/yumin/Documents/trading/scripts/watch_runtime_stack_tmp.sh](/Users/yumin/Documents/trading/scripts/watch_runtime_stack_tmp.sh)
  - intended for LaunchAgent `com.yumin.trading.runtime-stack`; it restarts the durable stack only after repeated `/health/ready` failures
- LaunchAgent install:
  - [/Users/yumin/Documents/trading/scripts/install_runtime_stack_launchd.sh](/Users/yumin/Documents/trading/scripts/install_runtime_stack_launchd.sh)
  - installs `com.yumin.trading.runtime-stack` and moves legacy noisy LaunchAgents into `~/Library/LaunchAgents.disabled/...`
- runtime scripts default to `PYDANTIC_DISABLE_PLUGINS=1` and `PYTHONDONTWRITEBYTECODE=1` to avoid slow startup scans and dirty tracked pycache files.
- recent family runtime audits:
  - [/Users/yumin/Documents/trading/scripts/run_session_impulse_retest_runtime_audit_report.py](/Users/yumin/Documents/trading/scripts/run_session_impulse_retest_runtime_audit_report.py)
- live candidate promotion readiness:
  - [/Users/yumin/Documents/trading/scripts/run_live_candidate_promotion_readiness.py](/Users/yumin/Documents/trading/scripts/run_live_candidate_promotion_readiness.py)
  - contract: [LIVE_CANDIDATE_READINESS_CONTRACT.md](/Users/yumin/Documents/trading/docs/LIVE_CANDIDATE_READINESS_CONTRACT.md)
  - compresses existing runtime audits and order-intent blockers into compare-only states such as `GATE_BLOCKED`, `SHADOW_SIGNAL_ONLY`, and `SUBMIT_READY_GAP`; it supports `--symbol ADAUSDT`, prints latest evidence timestamps plus `fresh`/`recent`/`stale`/`old` freshness labels, separates headline evidence from overall latest evidence, adds `promotion_decision` / `attention_flags` / `operator_review_items`, and never expands live authority
- `/execution/operator-ui` reads the dashboard through `fast=true` and renders live candidate readiness even when heavier validation/checklist/scanner surfaces are temporarily slow; slow optional surfaces show `source_unavailable` fallback text instead of blocking the whole page.
- When a symbol is selected, `/execution/operator-ui` shows both selected-symbol readiness and `live_candidate_promotion_readiness_global` so a local `WAIT` state cannot hide a global `BLOCKED` promotion gate.

Recommended checks:

```bash
cd /Users/yumin/Documents/trading
bash scripts/check_runtime_stack.sh
PYTHONPATH="$PWD" .venv/bin/python scripts/run_live_candidate_promotion_readiness.py --compact --no-write-report
PYTHONPATH="$PWD" .venv/bin/python scripts/run_live_candidate_promotion_readiness.py --symbol ADAUSDT --compact --no-write-report
PYTHONPATH="$PWD" .venv/bin/python scripts/run_session_impulse_retest_runtime_audit_report.py --hours 24 --limit 50
PYTHONPATH="$PWD" .venv/bin/python scripts/run_micro_main_usdt_proxy_backtest.py --days 1095 --write-report --write-loss-analysis
```

Latest 3-year USDT proxy validation after the 2026-05-10 loss-attribution hardening:

- strategy replay: `4399` closed trades, `+2815.8915R`, EV `+0.6401R`, win rate `65.67%`
- yearly portfolio replay with `1%` risk, `10x` cap, max `2` concurrent positions:
  - year 1: `+787.14%`, max drawdown `4.82%`
  - year 2: `+976.36%`, max drawdown `10.93%`
  - year 3: `+815.18%`, max drawdown `4.48%`

Interpretation guide for `session_impulse_retest` audits:

- `phase=refresh`
  - `signal_generated`: a fresh `session_impulse_retest` runtime plan was created
  - `no_fresh_candidates`: runtime evaluated the symbol but found no fresh family setup
  - `skipped_by_gate`: gate blocked plan generation before family routing
  - `insufficient_candles`: market data was not sufficient
- `phase=auto_route`
  - `submitted`: intent was created and submit was attempted
  - `intent_blocked`: intent existed but approval/submit policy blocked execution
  - `recent_intent_cooldown_active`: family cooldown suppressed duplicate intent creation
  - `no_session_impulse_retest_plan`: no active family plan existed at route time
  - `ws_stream_active_route_suppressed`: sync/manual route was intentionally suppressed because the WS worker is already responsible for routing
  - `intent_creation_failed` / `submit_error`: runtime failure in downstream order path

Current debugging principle:

- if `refresh=no_fresh_candidates` and `auto_route=no_session_impulse_retest_plan`, treat it as a **true no-setup window**
- if `refresh=signal_generated` but there is no corresponding `auto_route=submitted` or `intent_blocked`, treat it as a **runtime bug until proven otherwise**
- `run_live_candidate_promotion_readiness.py` uses the current WS worker `started_at` as its active window when available, and shows older 24h blockers only as `lookback_context`. Use `--lookback-only` when you intentionally want the full historical window to drive the headline.

## Strategy Lens

- Decision order: `state -> location -> liquidity -> reaction -> execution`.
- HTF location and liquidity come first. Lower-timeframe structure only refines execution.
- `OB/FVG` are execution zones, not standalone alpha.
- `BOS/CHoCH` are reaction evidence, not primary signals.
- `session box / opening range` are session liquidity references, not standalone entry triggers.
- `/scanner/top` and `/portfolio/budget` may expose `reaction_evidence`, `location_reference`, and `session_liquidity_reference` as compare-only readability aliases.
- The live source of truth remains `reaction_classification`, `reaction_input`, `strategy_family`, `strategy_grade`, and `recommended_risk_r`.

Final rollout approval still comes from `POST /validation/report` plus `POST /operations/checklist`.

## Current Live Contract

The canonical summary is [MICRO_LIVE Current State](/Users/yumin/Documents/trading/docs/MICRO_LIVE_CURRENT_STATE.md).

Current live route:

- execution mode: `MICRO_LIVE`
- strategy family: `session_impulse_retest`
- entry model: `CONFIRM`
- live symbols: `ADAUSDT`, `ATOMUSDT`, `BTCUSDT`, `FETUSDT`, `INJUSDT`, `LINKUSDT`, `LTCUSDT`, `NEARUSDT`, `RUNEUSDT`, `SUIUSDT`, `ZECUSDT`
- sessions: `dead_session`, `london`, `new_york`
- tuned pacing: `max_concurrent_positions=2`, `max_daily_new_entries=0` meaning no daily cap, `family_cluster_window=30m`, `max_same_family_entries=2`, `max_same_family_direction_exposures=2`, `loss_cooldown=60m/4 losses`, `saturday_risk_multiplier=1.0`, `leverage_cap=10x`

`ARBUSDT` was removed from the active allowlist after repeated live liquidity checks showed poor execution quality. The active replay-alignment report is `reports/operations/micro_intrabar_long_short_portfolio_mix_review_drop_arb/latest.json`.

The older `BTCUSDC + sweep_reversal + LIMIT` path is now a benchmark/legacy execution lens, not the current live allowlist. Do not mix benchmark counts with the live route when diagnosing order flow.

Backtest alignment for the current route:

- latest route details and required checks are maintained in [MICRO_LIVE Current State](/Users/yumin/Documents/trading/docs/MICRO_LIVE_CURRENT_STATE.md).
- historical USDT proxy reports are research context only unless they state no-lookahead entry timing and match the current live contract.

Live submit still requires validation, operations checklist, kill/close-only checks, liquidity, macro blackout, exchange rules, sizing, and reconciliation approval. `Trading entry surface alert` is not by itself an order trigger.

## What We Tried So Far

This project has already gone through several operating-contract revisions. The important part is not just the latest contract, but why earlier versions were rejected.

1. Global pooled sample as the main guide
- We first leaned on large global `LINEAGE_GLOBAL` post-patch samples.
- That looked better in the middle of the process, but it mixed symbols, entry types, and execution paths that were not the actual live contract.
- Conclusion: useful for research truth, not sufficient for live go/no-go.

2. Live-eligible proxy subset
- We split out a `limit_only` proxy subset.
- This improved interpretability and removed weak `CONFIRM` paths from the main live lens.
- Problem: it still included alt-heavy symbols and overstated how good the actual BTC/ETH execution contract was.

3. Actual BTC/ETH execution subset
- We then carved out `BTCUSDC/ETHUSDC` actual execution proof as a separate lane.
- This was the right move because it exposed the real issue: BTC/ETH execution quality was much thinner and weaker than the proxy suggested.
- Conclusion: actual execution must stay separate and cannot be replaced by proxy stats.

4. BTC/ETH trend proof lane
- We added a dedicated `trend_continuation + LIMIT` proof lane because the system looked too biased toward `range / sweep_reversal`.
- This addressed the concern that the engine might be blind to trend environments.
- Result so far: trend proof is still too thin and not yet a valid live contract.

5. Historical advisory lanes
- We added `historical_execution_contract_proof_summary` as a closed-lineage advisory lane.
- We added `historical_walk_forward_execution_contract_proof_summary` as a candle-by-candle contract-faithful advisory lane.
- We added a larger raw strategy replay lane for BTC/ETH to get much faster evidence than live execution alone.
- Conclusion: historical lanes are essential for strategy shaping, but they do not replace actual live execution proof.

6. ETH reduction and BTC preference
- We tested broader BTC/ETH live subsets, then narrowed to:
  - `BTCUSDC LONG|SHORT + ETHUSDC SHORT only`
  - `BTCUSDC only`
  - `BTCUSDC SHORT only`
- `BTCUSDC SHORT only` looked numerically stronger, but we explicitly rejected it as the live contract because it hard-coded a directional bet and threw away valid long setups.
- Earlier decision at that stage: keep `BTCUSDC LONG|SHORT`, but treat `short-bias` as advisory evidence rather than a hard operating rule. This has since been superseded by the current `session_impulse_retest + CONFIRM` USDT 11-symbol route.

7. Reliability and observability work
- We fixed repeated stage snapshot regressions where empty runtime summaries overwrote valid ones.
- We isolated tests from the real `trading.db`.
- We added stale sample cleanup, stale duplicate/reentry unblock logic, and self-heal summaries.
- We made stage, board, and notify surfaces show why candidates are blocked rather than hiding that under vague `not ready` language.

8. Earlier live canary execution setup
- We initially switched the runtime from `PAPER` toward a narrow `MICRO_LIVE` canary: `BTCUSDC + sweep_reversal + LIMIT`.
- We replaced the old notional shortcut with stop-distance risk sizing (`RISK_PCT`) so live quantity scales off `entry -> SL` distance.
- That narrow route is now a benchmark/legacy lens. The current live route and pacing are summarized in [MICRO_LIVE Current State](/Users/yumin/Documents/trading/docs/MICRO_LIVE_CURRENT_STATE.md).
- We removed the old `1 daily new entry` throttle and now rely on `one open position at a time` plus re-approval after each close as the primary pacing rule.

9. Runtime telemetry and shadow-only sizing observation
- We added runtime signal telemetry directly into plan validity so replay features and live plans can be compared on the same axes.
- We added `runtime_signal_shadow_tilt`, but kept it observation-only.
- That means the engine now logs whether a setup looks like a `weak long` or `strong short` according to the telemetry, without yet changing real live size.

10. Macro-event blackout instead of headline parsing
- We explicitly rejected news-NLP or headline interpretation as a first implementation.
- Instead, we added deterministic blackout windows for major U.S. macro releases (`FOMC`, `CPI`, `NFP`).
- This keeps the system simple and directly targets the part replay cannot faithfully simulate: event-time slippage and order-book distortion.

11. Exchange readiness and real connectivity
- We verified Binance API auth, user-stream startup, and position sync on the real exchange path.
- We aligned the exchange-side BTC contract to `isolated 6x` for the canary.
- At this point, the remaining unknowns are not API wiring but repeatable contract-faithful closes, real stop behavior, time-failure behavior, and reconciliation quality under actual live execution.

12. Contract-faithful funnel diagnostics
- We found that the dashboard was mixing broad BTC execution history with the current live contract and was therefore exaggerating the apparent fill bottleneck.
- We added an `active_contract` summary so the operator surface now shows a separate `BTCUSDC + sweep_reversal + LIMIT` execution/funnel lens.
- We also fixed an opportunity-capture misclassification where empty blocked-mix buckets could still read as `quality_blocking`.
- Current interpretation: the active contract is not presently bottlenecked by `submit_to_fill`; it is bottlenecked by `selection_shortfall` and a still-thin closed-trade sample.

## Historical Evidence And Operating Interpretation

Large-sample historical replay was used to shape the contract. The key comparisons were:

- `BTCUSDC + sweep_reversal + LIMIT`:
  - `2,858`
  - win rate `47.55%`
  - EV `+0.3274R`
  - PF `1.7925`
  - `stop_loss_share 63.51%`
  - `maxDD 15.2R`
- `BTCUSDC SHORT only + sweep_reversal + LIMIT`:
  - `1,463`
  - win rate `48.67%`
  - EV `+0.3583R`
  - PF `1.8976`
  - `stop_loss_share 62.41%`
  - `maxDD 12.6R`

Interpretation:

- `BTCUSDC SHORT only` is numerically stronger
- but the improvement is not large enough to justify forcing the system into one direction
- therefore that historical canary stayed `BTCUSDC LONG|SHORT` at the time
- `BTC short-bias` remains useful as research guidance, not as hard live policy

## Historical Concerns

These are the real engineering and strategy concerns at this point.

1. Execution mismatch
- historical and proxy lanes were good enough to choose the contract
- the hard problem now is real execution quality on the chosen contract
- broad execution-quality readout is still weak (`fill_rate 10.34%`, `terminal_exit_ratio 1.00`, `time_failure_ratio 0.6667`)
- but the contract-faithful lens is less bad (`plan_fill_rate 0.6667`, `submitted_to_fill_rate 1.00`, `terminal_exit_ratio 1.00`, `operational_forced_exit_ratio 0.5000`, `time_failure_ratio 0.5000`) and should now be treated as the primary execution readout for this canary
- the current contract-faithful raw counts are still tiny (`matured_plans=3`, `submitted=2`, `closed=2`), so classification quality matters more than any one headline ratio
- the one unfilled matured plan currently points to `not_reached_entry / expired_without_touch`, with only `2.4972bps` minimum miss distance over `14` observed bars and `77.0404bps` average favorable follow-through after the miss; this is better read as an unresolved entry-reach / placement observation than as a submit→fill failure
- the remaining live problem is therefore narrower: too little contract-faithful activity, too-thin after-cost closes, and still-unsettled forced-exit quality, not a proven generic fill-collapse of the chosen contract

2. Thin canary sample
- the contract is already narrowed, but actual live closed-trade evidence is still only `3/100` toward the current proof goal
- because of that, current sample messaging must stay conservative and operational

3. Candidate scarcity and structural blockage
- the current dashboard still shows `accepted_candidate_count=0` and `blocked_candidate_count=10`
- this means the system is live-ready but still waiting for contract-faithful, approval-clearing BTC candidates
- in practice, evidence will accumulate slowly unless real BTC limit setups start flowing through the current guardrails
- on the current active-contract lens the dominant bottleneck is `selection_shortfall`, which means the immediate issue is sparse eligible flow, not a measured collapse between submit and fill
- in the current active-contract lookback window that scarcity is showing up as `runtime_candidates=0` rather than a large blocked mix, so this is not yet evidence that the live gates themselves are too tight
- the current recent-intent split also says the same thing: `recent_intent_count=10` at the broad runtime level, but `active_contract_recent_intent_count=0` for the live contract itself
- the current flow cadence summary is therefore best read as `no_recent_active_contract_flow`, not as proof that gates or execution logic are malfunctioning
- the new promotion shadow counter says the same thing more explicitly: recent BTC plans still exist, but most recent `LIMIT` plans are being rejected before contract promotion (`runtime promoted 3` vs `replay hits 117` in the same 30-day comparison window)
- the new reaction-unavailable diagnostics narrow the cause further: the current BTC runtime is usually failing before scoring because the reaction classifier has either no recent exact level sweep (`no_recent_level_sweep`) or too few post-sweep bars (`insufficient_post_sweep_bars`) in its 5-bar event window
- generation diagnostics now also expose `reaction_shadow_zone_band_counts`, a shadow-only counter that compares exact-level reaction detection versus a relaxed zone-band sweep threshold before any live policy changes
- replay comparison says the same thing more sharply: live is currently observing `0.0` active-contract intents per week against a replay baseline of `35.021` expected candidates per week, so the next task is to determine whether this is normal sparsity or a live-vs-replay flow mismatch

4. Sample interpretation drift
- `full truth`, `live proxy`, `actual execution`, `historical execution`, and `historical strategy proof` are different lanes
- mixing them produces false confidence
- now there is another distinction to preserve: `strategy proof` versus `live operating validation`
- the latter is about fills, stops, reconciliation, and runtime drift, not about rediscovering the strategy from scratch

5. News handling is intentionally narrow
- the engine still does not interpret headlines or macro text directly
- it now has major-event blackout windows plus market-structure shock filters
- that is the right tradeoff for now, but the blackout schedule itself must be maintained and reviewed

Operator interpretation rule:

- use the broad BTC execution lens for general runtime-health warnings
- use the active-contract lens for canary diagnosis and contract policy decisions
- if the two disagree, do not loosen or tighten the live contract until denominator definitions, blocked-reason mix, forced-exit causes, and the after-cost closed-trade sample are reviewed together

Current canary diagnosis:

- do not read benchmark/legacy BTC metrics as current SIR live-route truth
- the current `session_impulse_retest + CONFIRM` canary is mainly constrained by route eligibility, live safety gates, liquidity, and still-thin live execution evidence
- use the safety drag audit and grid search before changing pacing gates
- keep sizing conservative and review blocked-reason mix plus forced-exit cause split before changing placement or rollout policy

## Open Problems

These are the concrete problems still left to solve.

- Continue accumulating additional `MICRO_LIVE` SIR route fills and closes until the after-cost sample is no longer thin
- Measure real stop behavior, stale-limit behavior, and reconciliation quality on actual exchange events
- Keep separating terminal exits from operational forced exits so `planned_stop_loss` does not get misread as an operational failure
- Keep tracking `flow_cadence` so we can tell the difference between normal strategy sparsity and an abnormally quiet live pipeline
- Compare live route cadence against replay cadence before changing gates; the next question is whether quiet flow is normal scarcity or a live-vs-replay flow gap
- Break operational forced exits down by concrete cause (`time_failure`, reconciliation/safety/manual causes) and decide whether exit quality is degrading or just sample-noisy
- Keep collecting `expired_without_touch` reach diagnostics and post-miss follow-through (`MFE/MAE`) before changing limit placement or entry offsets
- Determine whether after-cost results stay negative or recover once live route closes move beyond the current very thin sample
- Keep broad execution health and current-route execution health separate; do not let pooled BTC metrics overwrite the live route diagnosis
- Keep macro blackout schedules current so event-time risk control stays deterministic
- Decide when the canary has enough closed trades to loosen caps or claim that live operation is actually stable
- Keep using historical replay for shaping and comparison, but do not let it overwrite live operating truth

## Current Operating Rule

Until those problems are resolved, the rule is:

- live route: `session_impulse_retest + CONFIRM + 16 USDC perpetual symbols`
- execution mode: `MICRO_LIVE` canary
- direction: `LONG|SHORT` based on the setup, not a hard-coded directional bias
- sizing: stop-distance `RISK_PCT` sizing with a small canary account assumption
- operational pacing: `3` concurrent positions max, no daily entry cap, family/direction/loss cooldown pacing as documented in [MICRO_LIVE Current State](/Users/yumin/Documents/trading/docs/MICRO_LIVE_CURRENT_STATE.md)
- event policy: major `FOMC/CPI/NFP` blackout windows block new entries
- benchmark lens: `BTCUSDC + sweep_reversal + LIMIT` is advisory only
- `trend_continuation`: proof lane only
- `SWEEP_CONFIRM`/legacy `LIMIT` rows: context-only unless the live contract is explicitly changed

## Start Here

See `Quick Start` below for copy-paste startup requests.

1. `docs/CURRENT_SYSTEM_STATE.md`
   Read the current whole-system snapshot first when taking over the runtime, then use `docs/MICRO_LIVE_CURRENT_STATE.md` for the live-route contract.
2. `GET /health/ready`
   Check database, exchange connectivity, and event backend readiness before looking at trading surfaces.
3. `GET /execution/operator-dashboard`
   See runtime funnel, safety state, recent intents, orders, positions, reconciliation, and portfolio summary in one payload.
4. `GET /portfolio/budget`
   Review exposure headroom, blocked reasons, accepted candidates, and alpha research backlog.
5. `POST /validation/report`
   Generate the deployment approval summary, validation stack, and research outputs for a symbol.
6. `POST /operations/checklist`
   Convert validation plus runtime evidence into operator-facing go/no-go and playbook language.

## Authority Map

| Surface | Use it for | Not the final source of truth for |
| --- | --- | --- |
| `GET /indicators/*` and TradingView mirror | chart context, setup triage, operator-readable summaries | deployment approval, live order authority |
| `GET /scanner/top` | ranked runtime candidates after scanner/runtime filters | final rollout approval |
| `GET /portfolio/budget` | exposure headroom, blocked reasons, thesis overlap, alpha research backlog | exchange state or final deployment sign-off |
| `GET /execution/operator-dashboard` and `GET /execution/operator-ui` | runtime operating picture across safety, funnel, orders, positions, reconciliation | historical validation approval |
| `POST /validation/report` | deployment approval summary, validation/research evidence, approval topline | current exchange/order state |
| `POST /operations/checklist` | operator go/no-go, blocking evidence, playbook action | chart context or strategy discovery |
| intents, submissions, fills, positions, reconciliation | live execution and state transition truth | strategy approval policy |

## Runtime Lifecycle

```mermaid
flowchart TD
  A["Market Data"] --> B["Zone Engine"]
  B --> C["Plan Engine"]
  C --> D["Scanner Ranking"]
  D --> E["Portfolio Overlay"]
  E --> F["Execution Approval"]
  F --> G["Order Intents"]
  G --> H["Exchange Submission"]
  H --> I["Fills And Positions"]
  I --> J["Outcomes"]
  J --> K["Validation"]
  K --> L["Operations Checklist"]
```

1. Market data is refreshed and stored, then zone and plan engines generate execution candidates.
2. Scanner/runtime ranking adds expectations, family routing, sizing, mode policy, session guidance, and compare-only readability aliases.
3. Portfolio overlay applies thesis dedupe, correlation/exposure caps, and quality-gate filtering.
4. Execution preview and approval convert a plan into an executable contract with rollout-aware checks and outcome-aware approval downgrade hints.
5. Runtime sizing can reduce live risk allowance when execution degradation or post-cost bucket outcomes deteriorate.
6. Portfolio overlay can bias accepted candidate ordering toward stronger family/regime/session post-cost outcome buckets without changing hard blocks.
7. Intents, submissions, fills, positions, reconciliation, and outcomes track live execution truth.
8. Validation, checklist, alerts, and operator surfaces turn runtime and historical evidence into deployment language, including `outcome_control_trace`.

## Outcome Funnel

`generated plans -> scanner candidates -> portfolio accepted -> approval passed -> intents created -> submitted -> filled -> positions closed -> profitable -> net profitable after cost`

The funnel matters because candidate quality is only useful if it survives portfolio filtering, approval, execution friction, and post-cost outcome review.

## Money Funnel

`generated expected R -> submitted expected R -> filled expected R -> closed expected R -> raw realized R -> post-cost realized R`

- `score_to_outcome_funnel` now carries `money_funnel` so count conversion and R conversion can be read together.
- `score_to_outcome_funnel_summary.operating_kpis` now promotes the funnel into an operator KPI layer: `runtime_to_accepted`, `submitted_to_filled`, `filled_to_closed`, `closed_to_post_cost_profitable`, and `closed_trades_per_day`.
- `expected_ev_at_recommended_size_r` is the first expected-R proxy when available; otherwise the engine falls back to `expected_ev_r x recommended_risk_r`.
- This layer is explanatory and does not replace approval, sizing, or live execution truth.

## Key Capabilities

### Core Runtime

- Zone, plan, outcome, and execution persistence model
- Strategy-family routing, scoring, expectations, and sizing
- Runtime scanner and indicator surfaces for operator review

### Risk And Portfolio Controls

- Risk gate (`OPEN` / `THROTTLED` / `CLOSED`)
- Operating lock (`daily` / `session`) and strategy mode policy (`A_ONLY` / `A_PLUS_B` / `RESEARCH`)
- Portfolio overlay with total, directional, and cluster caps
- Outcome-aware risk allowance clamp on `recommended_risk_r`
- Outcome-aware portfolio ordering bias on accepted candidates
- Thesis fingerprint and dedupe across plans, scanner, and portfolio
- Alpha research backlog for quality near-miss candidates

### Execution And Fills

- Execution preview and approval contracts
- Order intents, submissions, fills, and position state machine
- Binance order, user-stream, and position synchronization
- Execution reconciliation and execution quality reporting

### Validation And Deployment Governance

- Validation report with deployment approval summary and playbook mapping
- Operations checklist with runtime blocking evidence
- Outcome-first control trace across approval, sizing, and portfolio ordering
- Strategy validation, lock/thesis checks, and experimental comparison surfaces
- PBO/DSR, stress validation, and replay lineage for promotion and deployment review

### Alerts And Reliability

- Validation alert fanout with shared deployment/playbook language
- Subscription-based lifecycle alerts
- Retry queue, backoff, circuit breaker, dead-letter replay, and SLO metrics

### Integrations

- TradingView webhook and Pine mirror bridge
- Operator UI and operator dashboard
- Optional Redis, Kafka, WebSocket, Postgres, and TimescaleDB integration path

## Execution Degradation Loop

`execution quality -> degradation detection -> advisory flag -> validation/checklist language -> rollout suggestion`

- Execution degradation is an operator intervention signal, not standalone order authority.
- Quality drift should tighten rollout language before it is allowed to distort strategy interpretation.
- Rollout suggestion remains compare-only and does not auto-edit family rollout policy.

## Outcome-First Control Loop

`execution degradation + post-cost outcome -> approval penalty -> risk allowance clamp -> portfolio ordering bias -> outcome_control_trace`

- Approval can expose `outcome_approval_penalty` and downgrade `APPROVED_AUTO` to `APPROVED_MANUAL` when execution drag and weak post-cost conversion align.
- Candidate rows can expose `strategy_sizing.outcome_risk_adjustment` to show when live risk allowance was reduced.
- Portfolio accepted candidates can expose `outcome_bias` to show whether ordering moved toward or away from a bucket.
- Validation, checklist, and dashboard summarize the same chain through `outcome_control_trace`; this is explanation, not a new source of truth.

## Outcome Attribution

`closed expected R proxy + raw realized R + post-cost realized R -> strategy component + execution component + condition component`

- `outcome_attribution` is a post-trade decomposition helper that separates strategy expectation, execution drag, and condition drift without creating a new approval authority.
- It also exposes `fill_capture_gap_r` so missed fill conversion can be read as a money leak instead of only a count leak.
- This layer is advisory-only and should be read together with `money_funnel`, not in isolation.

## Edge Experiment Review

`money_funnel windows + entry_timing split + execution_style split -> true_edge_ratio + edge_decay_rate + preferred experiment branch`

- `edge_experiment_review` turns the same post-cost funnel into `true_edge_ratio`, `recent/prior` edge windows, and compare-only next-test guidance.
- `entry_timing_experiment` compares `early_limit` versus `reaction_confirmed`; `execution_style_experiment` compares `passive_limit` versus `market` when both branches have coverage.
- It now also emits `sample_maturity_state`, `next_sample_target_closed_trades`, and `regime_dependency_state`, so operators can separate directional evidence from durable edge and see when the weakest regime is still lagging.
- It also emits `edge_proof_goal_closed_trades=100`, `remaining_closed_trades_to_edge_proof_goal`, `edge_proof_posture`, and `daily_edge_kpis`, so thin samples are not mistaken for proven edge.
- It also emits `operating_discipline`, which keeps the framework/edge distinction explicit: `framework_quality_state=framework_ready`, `system_mode=operate_and_experiment`, `current_system_identity=edge_proof_engine`, `next_system_stage=post_first_verified_edge`, `resilience_claim=harder_to_fail_from_self_deception`, `fail_safe_claim=false`, `realized_edge_dependency_domains=[market_edge, execution_quality, operating_discipline]`, `evaluation_focus=after_cost_edge_only`, `primary_goal=find_first_verified_edge`, `improvement_priority=prove_single_edge_before_density_or_strategy_expansion`, `profit_claim_allowed=false`, `structure_change_review_allowed=false`, `loss_driven_rewrite_allowed=false`, `rollout_expansion_allowed=false`, `alpha_generator_review_allowed=false`, `signal_density_control_review_allowed=false`, `execution_strategy_automation_review_allowed=false`, and `multi_strategy_expansion_review_allowed=false` until proof posture is genuinely reviewable and regime stability is confirmed.
- It also emits `experiment_sequence`, which fixes the research order as `entry_timing (early_limit vs reaction_confirmed) -> execution_style (passive_limit vs market) -> exit optimization`; exit review stays deferred until both split baselines are locked and the exit-review floor is reached.
- The current first-edge live spec for the A anchor is documented in [docs/A_STRATEGY_EXPERIMENT_SPEC_V1.md](/Users/yumin/Documents/trading/docs/A_STRATEGY_EXPERIMENT_SPEC_V1.md); it keeps `sweep_reversal` as the first live target, uses `early_limit` vs `reaction_confirmed` as the initial split, and leaves exit ideas in shadow-only mode until sequencing explicitly opens exit optimization.
- The post-proof scaling contract is documented in [docs/EDGE_PROOF_CAPITAL_SCALE_CONTRACT.md](/Users/yumin/Documents/trading/docs/EDGE_PROOF_CAPITAL_SCALE_CONTRACT.md); it defines a conservative `1.00x -> 1.10x -> 1.25x -> 1.50x` family scale curve, freeze/reduce rules, and the order between proof scaling and `capital_allocator`.
- This layer is advisory-only and is meant to answer "what should we test next?" before anyone rewrites the strategy structure.

Framework quality and edge proof are different claims. The framework can be structurally ready while the edge is still unproven; until `edge_proof_posture.state == edge_claim_ready`, treat the system as `operate_and_experiment`, not profit-proven, and judge it on after-cost closed-trade edge rather than architecture completeness. The framework is designed to make self-deception failure harder, not to make the system fail-safe; realized results still depend on market edge, execution quality, and operating discipline.

## Edge Evolution Rule

`edge_experiment_review + rollout_recommendation + strategy_lifecycle + kill_condition_automation -> edge_evolution_rule`

- `edge_evolution_rule` turns split-test evidence into advisory-only `promote / reduce / research_only / kill-review` language without mutating rollout or safety state by itself.
- It exists to answer "when should we reduce baseline allocation, keep research-only, or escalate a preferred branch into promotion review?" after the raw split evidence is already visible.
- `promote / reduce / kill-review` wording is only interpretable after real split observation has produced enough closed post-cost trades; if the sample is still thin, this layer should stay in `insufficient_sample` or `research_only` posture.
- The rule now also emits `recommendation_strength` and `closed_loop_confirmation_state`, so operator surfaces can distinguish a first-pass advisory from a direction that was re-confirmed after a prior review packet and newer closed trades.
- It also emits `regime_guard_state`, so preferred-branch promotion can be explicitly blocked when the edge still looks regime-dependent.

## Review Followup Ledger

`run_split_review_followup -> review_followup_ledger -> validation/dashboard/checklist/ui/handoff`

- `review_followup_ledger` records both split/evolution review packet generation events and later operator decision transitions, so operator surfaces can read recent `last_generated_status + last_decision_status + last_effective_status + last_action + followup_command` instead of only the current recommendation.
- The ledger summary now separates `last_generated_status`, `last_decision_status`, and `last_effective_status`, plus `recent_packets`, `latest_action_streak`, and `fresh_ready_packet_count`, so surfaces can tell the difference between packet generation, later operator confirmation, and simple packet repetition.
- `operator_action_priority` now also exposes `experiment_execution_policy` and `deferred_experiment_actions`, so the system keeps only one split experiment active at a time instead of opening entry-timing and execution-style experiments in parallel.
- This closes the loop between `operator_action_priority`, a runnable `scripts/run_split_review_followup.py` command, and recent packet history without creating a new approval authority.

## Outcome-Aware Rollout Recommendation

`family outcome + family execution + mode advisory + current rollout policy -> rollout_recommendation`

- Validation, checklist, and dashboard can expose `rollout_recommendation` as an operator-facing suggestion layer.
- Recommendation values are `expand`, `hold`, `reduce`, `research_only`.
- `current_policy` and `suggested_policy_delta` are shown together so rollout review stays explicit.
- This layer is advisory-only and does not auto-change rollout policy rows.

## Strategy Lifecycle

`alpha research + rollout recommendation + family execution + post-cost outcome -> strategy_lifecycle`

- Lifecycle states are `research`, `probation`, `production`, `degraded`, and `retired`.
- `transition_bias` is limited to `promote`, `hold`, `degrade`, `retire`, and `observe`.
- Validation, checklist, and dashboard can expose `strategy_lifecycle_summary` as a governance posture layer.
- This layer is advisory-only and does not directly change approval, sizing, candidate ranking, or rollout policy rows.

## Multi Strategy AB Expansion

`raw strategy_family + strategy_mode + family guardrails -> multi_strategy_ab`

- Raw `strategy_family` remains the source of truth. The A/B layer is an additive operating overlay, not a family replacement.
- First-wave mapping is `sweep_reversal -> a_reversal`, `trend_continuation -> b_continuation`, and `range_rotation -> research_only_sidecar`.
- `A` remains the current production anchor. `B` is available as a first-wave secondary family but stays guarded until thin-sample, execution, rollout, and lifecycle guardrails clear.
- `/scanner/top` and `/portfolio/budget` may expose `strategy_cluster`, `strategy_cluster_status`, and `multi_strategy_overlay` as compare-only A/B coexistence fields.
- Validation, checklist, and dashboard can expose `multi_strategy_ab_summary` as the compare-only family coexistence layer.
- This layer is advisory-only and does not directly change approval, sizing, candidate ranking, or rollout policy rows.

## B Continuation Activation

`multi_strategy_ab + rollout / lifecycle / clearance / reopen context -> b_continuation_activation`

- `b_continuation_activation` is the B-family operating posture layer for first-wave activation, not a new approval or rollout authority.
- States are limited to `research_only`, `blocked`, `guarded_probation`, and `activation_ready`.
- `/scanner/top` and `/portfolio/budget` may expose `b_continuation_activation` on `trend_continuation` rows so operators can read whether B is still compare-only, blocked by hard guardrails, or approaching guarded activation.
- Validation, checklist, and dashboard can expose `b_continuation_activation_summary` as the shared first-wave B activation layer.
- This layer is advisory-only and does not directly change approval, sizing, candidate ranking, or rollout policy rows.

## B Continuation Edge Validation

`raw trend_continuation family + condition split / activation posture / cluster balance / capital allocator -> b_continuation_edge_validation`

- `b_continuation_edge_validation` is the compare-only B diversification evidence layer. It does not replace raw family accounting, activation posture, approval, or rollout authority.
- States are limited to `validated_edge`, `fragile_edge`, `insufficient_edge`, and `insufficient_sample`.
- `family_post_cost_rate` is the first-wave primary metric. `family_post_cost_ev` remains optional until a stable family-level scalar exists.
- `a_b_correlation_proxy` and `drawdown_contribution_state` are first-wave proxy language, not exact covariance or realized portfolio attribution.
- Validation, checklist, and dashboard can expose `b_continuation_edge_validation_summary` as the shared verdict for whether raw `trend_continuation` still offers usable diversification value.
- This layer is advisory-only and does not directly change activation posture, approval, sizing, candidate ranking, or rollout policy rows.

## Strategy Cluster Balance

`multi_strategy_ab + b_continuation_activation + capital_allocator + current family mix -> strategy_cluster_balance`

- `strategy_cluster_balance` is the compare-only A/B mix posture layer. It does not replace raw `strategy_family`, approval, or rollout authority.
- States are limited to `research_only_mix`, `a_concentrated`, `guarded_rebalance`, and `balanced_mix`.
- `/scanner/top` and `/portfolio/budget` may expose `strategy_cluster_balance` on candidate rows so operators can read whether a row is still anchor-preserve, diversification-candidate, guardrail-limited, or balanced-support.
- Validation, checklist, and dashboard can expose `strategy_cluster_balance_summary` as the shared A/B cluster mix layer.
- This layer is advisory-only and does not directly change approval, sizing, candidate ranking, or rollout policy rows.

## A Strategy Post-Cost Edge Validation

`raw sweep_reversal family + family execution / outcome control / condition split / alpha research -> a_strategy_post_cost_edge_validation`

- `a_strategy_post_cost_edge_validation` is the compare-only A-anchor evidence layer. It does not replace raw family accounting, approval, or rollout authority.
- States are limited to `validated_edge`, `fragile_edge`, `insufficient_edge`, and `insufficient_sample`.
- `family_post_cost_rate` is the first-wave primary metric. `family_post_cost_ev` remains optional until a stable family-level scalar exists.
- Validation, checklist, and dashboard can expose `a_strategy_post_cost_edge_validation_summary` as the shared verdict for whether `sweep_reversal` still supports the current anchor posture.
- This layer is advisory-only and does not directly change approval, sizing, candidate ranking, or rollout policy rows.

## Strategy Family Edge Review

`closed plans + baseline cost adjustment + peer-family comparison -> strategy_family_edge_review`

- `strategy_family_edge_review` is the actual-money family review helper for `sweep_reversal` versus `trend_continuation`.
- It reads closed plans, applies the same baseline cost adjustment used by stress validation, and compresses the result into `validated_edge / fragile_edge / insufficient_edge / insufficient_sample`.
- `sweep_reversal` is read as the current `A anchor`; `trend_continuation` is read as the current `B diversification` candidate.
- Use [run_strategy_family_edge_review.py](/Users/yumin/Documents/trading/scripts/run_strategy_family_edge_review.py) for repeatable A/B reviews and [LIVE_ALPHA_OPERATING_ROUTINE.md](/Users/yumin/Documents/trading/docs/LIVE_ALPHA_OPERATING_ROUTINE.md) for daily, weekly, and monthly cadence.
- Reports are written to `reports/validation/edge_reviews/`.

## Live Alpha Operating Review

`a_anchor review + b_diversification review + monthly projection proxy -> live_alpha_operating_review`

- `live_alpha_operating_review` is the top-level real-money operating summary for the current A/B stack.
- It reuses the same post-cost family review logic, then adds a combined 30-day R projection proxy and observed monthly post-cost breakdown.
- The monthly projection is intentionally approximate and stays in R units. It is a review aid, not a sizing authority.
- Use [run_live_alpha_operating_review.py](/Users/yumin/Documents/trading/scripts/run_live_alpha_operating_review.py) for the combined review and [LIVE_ALPHA_OPERATING_ROUTINE.md](/Users/yumin/Documents/trading/docs/LIVE_ALPHA_OPERATING_ROUTINE.md) for cadence.
- Reports are written to `reports/validation/live_alpha_reviews/`.

## Replay Evidence Review

`historical closed plans + stress replay lineage + replay assessment -> replay_evidence_review`

- `replay_evidence_review` is the historical replay-proxy context layer for a single symbol.
- It reuses A/B family edge review, then adds stress replay lineage and replay assessment so historical evidence can be read without pretending it is live confidence.
- The payload is intentionally marked `do_not_treat_as_live_confidence=true`.
- Use [run_replay_evidence_review.py](/Users/yumin/Documents/trading/scripts/run_replay_evidence_review.py) for symbol-level replay context and keep it separate from [run_live_alpha_operating_review.py](/Users/yumin/Documents/trading/scripts/run_live_alpha_operating_review.py).
- Reports are written to `reports/validation/replay_evidence_reviews/`.

## Promotion Governance

`strategy_lifecycle + rollout_recommendation + positive_evidence_expansion + condition split -> promotion_governance`

- States are `promotable`, `hold`, and `defer`.
- `promotion_bias` is limited to `consider_promote`, `hold`, and `defer`.
- `target_posture` is limited to `probation`, `production`, and `keep_current`.
- Validation, checklist, and dashboard can expose `promotion_governance_summary` as a compare-only promotion review layer.
- This layer is advisory-only and does not directly change approval, sizing, candidate ranking, or rollout policy rows.

## Promotion Review Queue

`promotion_governance + strategy_lifecycle + positive_evidence_expansion + capital_allocator -> promotion_review_queue`

- `promotion_governance` remains the family-level review decision. `promotion_review_queue` is the cross-family ordering layer.
- Review actions are limited to `promote_review`, `defer_review`, and `hold_monitor`.
- Validation, checklist, and dashboard can expose `promotion_review_queue_summary` as a compare-only queue for what to review first across families.
- This layer is advisory-only and does not directly change approval, sizing, candidate ranking, or rollout policy rows.

## Promotion Remediation Queue

`promotion_governance + promotion_review_queue + family execution / rollout / lifecycle / condition drag -> promotion_remediation_queue`

- `promotion_governance` remains the family-level review decision, and `promotion_review_queue` remains the cross-family review ordering layer. `promotion_remediation_queue` is the cross-family guardrail-clearing ordering layer.
- Remediation actions are limited to `execution_remediation`, `policy_remediation`, `condition_remediation`, and `observe_guardrail`.
- Validation, checklist, and dashboard can expose `promotion_remediation_queue_summary` as a compare-only queue for what guardrail should be cleared first before promotion review reopens.
- This layer is advisory-only and does not directly change approval, sizing, candidate ranking, or rollout policy rows.

## Promotion Clearance Tracker

`promotion_governance + promotion_remediation_queue + family execution / rollout / condition state -> promotion_clearance_tracker`

- `promotion_governance` remains the family review decision, and `promotion_remediation_queue` remains the cross-family guardrail-clearing ordering layer. `promotion_clearance_tracker` is the family-level progress tracking layer for whether those guardrails are still blocked, partially cleared, or ready for review re-open.
- Clearance states are limited to `blocked`, `partial_clear`, `clearance_ready`, and `observe_only`.
- Validation, checklist, and dashboard can expose `promotion_clearance_tracker_summary` as a compare-only tracking layer for remaining versus cleared guardrail domains.
- This layer is advisory-only and does not directly change approval, sizing, candidate ranking, or rollout policy rows.

## Promotion Reopen Queue

`promotion_clearance_tracker + promotion_governance + promotion_review_queue + promotion_remediation_queue -> promotion_reopen_queue`

- `promotion_clearance_tracker` remains the family progress tracking layer, and `promotion_reopen_queue` is the cross-family review re-open ordering layer.
- Reopen actions are limited to `reopen_review`, `continue_clearance`, and `observe_reopen`.
- Validation, checklist, and dashboard can expose `promotion_reopen_queue_summary` as a compare-only queue for what promotion review can be reopened first versus what still needs clearance work.
- This layer is advisory-only and does not directly change approval, sizing, candidate ranking, or rollout policy rows.

## Promotion Decision Brief

`promotion_reopen_queue + promotion_clearance_tracker + promotion_governance + promotion_review_queue + promotion_remediation_queue -> promotion_decision_brief`

- `promotion_reopen_queue` remains the cross-family ordering layer, and `promotion_decision_brief` is the single-family case compression layer.
- Brief states are limited to `reopen_candidate`, `clearance_required`, and `observe_case`.
- Validation, checklist, and dashboard can expose `promotion_decision_brief_summary` as a compare-only summary for how the current headline family should be read right now.
- This layer is advisory-only and does not directly change approval, sizing, candidate ranking, or rollout policy rows.

## Auto Promotion Rollout Execution

`promotion_decision_brief + promotion_reopen_queue + promotion_clearance_tracker + rollout_recommendation -> auto_promotion_rollout_execution`

- `auto_promotion_rollout_execution` is a compare-only execution candidate contract, not a direct live authority.
- Execution stages are limited to `advisory_only`, `dry_run_execution`, `semi_auto_candidate`, and `auto_execution_blocked`.
- First implementation only allows audit-only dry-run wording and operator-confirmable proposal execution wording; direct approval, sizing, or rollout DB auto-write remains out of scope.
- Validation, checklist, and dashboard can expose `auto_promotion_rollout_execution_summary` as the shared semi-auto readiness layer.

## Promotion Lifecycle History

`promotion_decision_brief + promotion_reopen_queue + promotion_clearance_tracker + auto_promotion_rollout_execution -> promotion_lifecycle_history`

- `promotion_lifecycle_history` is a compare-only lineage layer, not a new approval or rollout authority.
- First implementation stores immutable append-only events for lifecycle transition, review queue, remediation, clearance, reopen readiness, and auto-execution stage changes, then exposes only recent aggregate history.
- Validation, checklist, and dashboard can expose `promotion_lifecycle_history_summary` as the shared durable context for `history_unavailable`, `history_accumulating`, `history_stable`, and `history_attention_required`.
- Persistence failure is soft-fail only; it must not change approval, sizing, scanner ranking, candidate rows, or rollout DB authority.

## Research Promotion Operating Loop

`alpha_research_pipeline + promotion stack + promotion_lifecycle_history -> research_promotion_operating_loop`

- `research_promotion_operating_loop` is a compare-only loop language that connects research backlog, shadow testing, probation readiness, and promotion followthrough without creating new live authority.
- States are limited to `research_backlog`, `shadow_test_ready`, `probation_candidate`, and `promotion_followthrough`.
- Validation, checklist, and dashboard can expose `research_promotion_operating_loop_summary` as the shared bridge between alpha research actions and promotion path review.
- Thin sample, manual review, and `history_attention_required` keep this layer from jumping straight to probation or promotion wording.

## Positive Evidence Expansion

`rollout recommendation + strategy lifecycle + family post-cost outcome + family execution -> positive_evidence_expansion`

- States are `expandable`, `hold`, and `not_ready`.
- `expansion_bias` is limited to `consider_expand`, `hold`, and `do_not_expand`.
- Validation, checklist, and dashboard can expose `positive_evidence_expansion_summary` as a controlled positive review layer.
- This layer is compare-only and does not directly change approval, sizing, candidate ranking, or rollout policy rows.

## Outcome Bucket Granularity

`family outcome + volatility / cost / liquidity condition split -> outcome_bucket_granularity`

- `family` remains the headline. `volatility_condition`, `cost_condition`, and `liquidity_condition` are only supporting condition buckets.
- Validation, checklist, and dashboard can expose `outcome_bucket_granularity_summary` as a compare-only condition split layer.
- `liquidity_condition` is based on a liquidity proxy, not a raw order-book depth measurement.
- This layer is informational and does not directly change approval, sizing, candidate ranking, or rollout policy rows.

## Opportunity Capture

`runtime candidates + acceptance + submission + fill + close -> opportunity_capture`

- Validation, checklist, and dashboard can expose `opportunity_capture` as a throughput explanation layer.
- It summarizes `trades_per_day`, `capture_rates`, `capture_gap`, `blocked_mix`, and a `dominant_bottleneck`.
- `family_focus` is the headline; `regime_modifier` and `session_modifier` are only modifiers.
- This layer is advisory-only and does not auto-relax quality gates, approval, sizing, or rollout policy.

## Outcome-Aware Capital Allocator

`family outcome + execution quality + mode context + current active risk -> capital_allocator`

- `recommended_risk_r` remains the sizing source of truth. `allocated_risk_r` is a portfolio-only allowance layer applied after sizing.
- The allocator is family-first. `regime` and `session` only act as modifiers and cannot overturn a thin-sample guardrail.
- `/portfolio/budget` can expose `capital_allocator`, `allocation_weight`, `allocated_risk_r`, and `capital_pressure` on candidate rows.
- Validation, checklist, and dashboard summarize the same family tilt through `capital_allocator_summary`; this is a scarce-capital layer, not approval authority.

## Capture-Aware Operator Priority

`opportunity_capture + execution / mode / research stack -> operator_action_priority`

- `operator_action_priority` now keeps the existing urgent control ordering, then translates throughput bottlenecks into action families such as `selection_review`, `rollout_review`, `execution_review`, and `observe`.
- `priority_source`, `action_family`, and `capture_context` let operators see whether the top review item came from playbook/execution controls or from capture-aware throughput context.
- `experiment_context` also carries representative accepted/blocked candidate focus plus `entry_timing_target` / `execution_style_target`, so split-test follow-up points at a concrete row instead of staying abstract.
- `thin_activity_window` is treated as `observe`, not as an automatic negative verdict or threshold-relaxation trigger.

## Operator Surfaces

- `GET /execution/operator-dashboard`
  Runtime source for safety state, funnel, recent intents, open orders, positions, reconciliation, alert summary, and execution quality summary.
  It now also exposes `approval_strip_summary`, so the runtime dashboard itself can be read with the same `approve -> align -> act` vocabulary as validation, checklist, the operator UI, and session handoff.
  It also surfaces `signal_funnel.operator_action_priority` with capture-aware review order, `signal_funnel.outcome_control_trace`, `signal_funnel.edge_experiment_review`, `signal_funnel.edge_evolution_rule`, `signal_funnel.rollout_recommendation`, `signal_funnel.strategy_lifecycle`, `signal_funnel.promotion_governance`, `signal_funnel.promotion_review_queue`, `signal_funnel.promotion_remediation_queue`, `signal_funnel.promotion_clearance_tracker`, `signal_funnel.promotion_reopen_queue`, `signal_funnel.promotion_decision_brief`, `signal_funnel.auto_promotion_rollout_execution`, `signal_funnel.promotion_lifecycle_history`, `signal_funnel.research_promotion_operating_loop`, `signal_funnel.multi_strategy_ab_expansion`, `signal_funnel.b_continuation_activation`, `signal_funnel.execution_friction_measurement`, `signal_funnel.forward_stress_regime_validation`, `signal_funnel.kill_condition_automation`, `signal_funnel.strategy_cluster_balance`, `signal_funnel.opportunity_capture`, `signal_funnel.capital_allocator`, recent intent `outcome_approval_penalty`, and trimmed portfolio candidate drill-down rows.
- `GET /execution/operator-ui`
  Browser operator surface backed by the same runtime payloads, intended for day-to-day operating review.
  It now surfaces `5-Second Operator Kernel` at the top of the home section, so operators can read `money_funnel -> outcome_attribution -> outcome_control_trace -> rollout` before dropping into the broader review stack.
  It now replaces the older `Decision Summary + Approval Divergence` split with a single `Approval Strip`, so operators read `approve -> align -> act` immediately under the kernel.
  It now groups `A/B Strategy Posture`, `Promotion Operating Stack`, `Promotion Case Inspector`, and `Alpha Research Inspector` under `Deferred Research / Promotion Stack`, which stays collapsed by default whenever the kernel verdict is `hold`, `manual_review`, or `watch`.
  It now treats `Top Opportunity`, `Portfolio Candidate Drilldown`, and `Portfolio Candidate Inspector` as context-only surfaces whenever the kernel verdict is `hold`, `manual_review`, or `watch`, so approval/alignment/checklist interpretation stays first.
  `Current Operating State` now acts as the broader `Expanded Operating Context` follow-up layer, and it stays collapsed under strong kernel verdicts until the operator finishes the approval strip read.
  It now exposes `Experiment Routing` inside `Current Operating State` and `Approval Alignment Inspector`, so the preferred entry/execution split is tied to a representative candidate row before any follow-up review is opened.
  It also surfaces an `A/B Strategy Posture` home-section panel so operators can read `multi_strategy_ab_expansion`, `b_continuation_activation`, and `strategy_cluster_balance` together without dropping into raw dashboard JSON.
  The same home section now includes `Promotion Operating Stack`, which compresses `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`, `promotion_clearance_tracker`, `promotion_reopen_queue`, `promotion_decision_brief`, `auto_promotion_rollout_execution`, `promotion_lifecycle_history`, and `research_promotion_operating_loop` into a single operator review surface.
  It also includes `Promotion Case Inspector`, which re-compresses the current headline promotion family into target posture, write scope, remaining guardrails, cleared guardrails, and next-move language.
  It also includes `Validation / Checklist Review Stack`, which lines up validation top-level summaries and checklist item statuses for rollout, edge experiments, edge evolution, A/B posture, promotion stack, opportunity capture, and capital allocation without requiring raw payload inspection, and now reads those top lines in the same `approve -> align -> act` vocabulary instead of raw `GO/NO_GO + playbook` wording.
  It also includes `Validation Case Inspector`, which re-compresses the current symbol validation case into money funnel, outcome attribution, edge experiments, edge evolution, outcome control, rollout, lifecycle, A/B posture, condition split, capture, allocator, and next-move language, while carrying the same validation `approve -> align -> act` strip inside the card.
  It also includes `Runtime Quality Inspector`, which re-compresses recent validation alerts, retry queue pressure, execution quality, and reconciliation health into a single runtime operating-quality card, and now labels the latest alert in `Approve / Act` terms so quality escalation wording matches the rest of the operator stack.
  It also includes `Signal Funnel Inspector`, which re-compresses the current hard gate, softening queue, rollout block, family/regime/session bottlenecks, money funnel, outcome attribution, edge experiment review, and edge evolution rule into a single funnel review card.
  It also includes `Alpha Research Inspector`, which re-compresses research backlog, recommended research action, top shadow experiment, softening review, and promotion watchlist into one home-section research card.
  It also includes `Kill Condition Inspector`, which re-compresses `signal_funnel.kill_condition_automation` into stop-review verdict, trigger axis, write scope, manual-override state, and current lock posture before any live stop is armed.
  It also includes `Policy / Lock Inspector`, which re-compresses kill switch, close-only, active locks, matching locks, and rollout policies into a single home-section policy card.
  It also includes `Intent / Exposure Inspector`, which re-compresses recent intents, open orders, open positions, and the current live exposure queue into a single home-section activity card.
  It also includes `Mode / Deployment Inspector`, which re-compresses execution mode, entry gate, dashboard/checklist/validation deployment posture, rollout recommendation, and mode advisory into a single home-section deployment card.
  It also includes `Approval Alignment Inspector`, which re-compresses dashboard/checklist/validation/candidate/operator-priority alignment into a single home-section approval card.
  It also includes `Data Freshness / Source Inspector`, which re-compresses generated timestamps, report windows, and source/report-path readiness for dashboard, validation, checklist, and execution-quality surfaces.
  It now also includes `Portfolio Candidate Drilldown` and `Checklist Evidence Drilldown`, so accepted/blocked candidate overlays and checklist evidence can be reviewed directly from the home section instead of through raw JSON blobs.
  It also includes a dedicated `Portfolio Candidate Inspector`, which expands one representative accepted row and one representative blocked row into risk, outcome bias, edge focus, allocator, A/B posture, session, and reaction evidence cards.
  It also includes `Report Navigation`, which exposes local validation/checklist/execution-quality report paths as file links for deeper review after the home-section summary.
  For repeatable browser inspection and dry-run divergence capture, use [docs/OPERATOR_UI_HOME_INSPECTION_CHECKLIST.md](/Users/yumin/Documents/trading/docs/OPERATOR_UI_HOME_INSPECTION_CHECKLIST.md), [scripts/collect_operator_surface_divergence_snapshot.py](/Users/yumin/Documents/trading/scripts/collect_operator_surface_divergence_snapshot.py), [scripts/generate_operator_session_brief.py](/Users/yumin/Documents/trading/scripts/generate_operator_session_brief.py), [scripts/notify_operator_session_brief.py](/Users/yumin/Documents/trading/scripts/notify_operator_session_brief.py), [scripts/check_operator_session_brief_automation.py](/Users/yumin/Documents/trading/scripts/check_operator_session_brief_automation.py), and [scripts/check_operator_session_brief_delivery_preflight.py](/Users/yumin/Documents/trading/scripts/check_operator_session_brief_delivery_preflight.py). The notifier supports `system` or `discord` delivery plus separate `shift-start` and `shift-end` handoff formats, now carries both the derived `candidate_surface_priority` field and an `Approval Strip` summary alongside the rest of the `5-Second Operator Kernel`, includes top-level `edge_experiment` focus (`edge_state`, preferred entry timing, preferred execution style), and also preserves representative accepted/blocked row `edge_experiment_focus` so split-test follow-up survives handoff at candidate level. Live delivery requires both `OPERATOR_BRIEF_DRY_RUN` unset and `OPERATOR_BRIEF_ALLOW_LIVE_SEND=1`. [docs/OPERATOR_SESSION_BRIEF_AUTOMATION.md](/Users/yumin/Documents/trading/docs/OPERATOR_SESSION_BRIEF_AUTOMATION.md) documents the tick wrapper, cron examples, launchd plists, automation health checks, and delivery preflight for split shift handoff loops.
- `GET /portfolio/budget`
  Exposure, headroom, blocked reasons, accepted candidates, and `alpha_research_candidates`.
  It now also exposes top-candidate `edge_experiment_review`, top-level `edge_evolution_rule`, and focus-symbol `review_followup_ledger`, so entry alerts and portfolio review can carry the same split-test focus, current allocation/promotion posture, and latest review packet carryover state as validation and drill surfaces.
  Accepted and blocked candidate rows may include `strategy_family`, `strategy_cluster`, `strategy_cluster_status`, `multi_strategy_overlay`, `b_continuation_activation`, `strategy_cluster_balance`, `strategy_sizing.outcome_risk_adjustment`, `outcome_bias`, `edge_experiment_focus`, and `capital_allocator` with `allocated_risk_r`.
- `POST /validation/report`
  Deployment approval summary plus the full validation and research stack for one symbol.
  It now also exposes `approval_strip_summary`, so validation topline can be read with the same `approve -> align -> act` vocabulary as the operator UI and session handoff.
  It also includes `operator_action_priority_summary` with `priority_source`, `action_family`, and `capture_context`, plus `outcome_control_trace_summary` to explain how outcome-first controls are tightening approval, sizing, and ordering.
  It now also includes `money_funnel` and `outcome_attribution_summary` so expected-R leakage and closed-trade post-cost attribution can be read directly from the same validation surface.
  `multi_strategy_ab_summary` is the compare-only A/B coexistence layer for `A remains anchor`, `B available but guarded`, and research-only sidecar language.
  `b_continuation_activation_summary` is the compare-only first-wave B posture layer for whether `trend_continuation` should stay research-only, clear blockers, remain guarded probation, or be reviewed for guarded activation.
  `execution_friction_measurement_summary` is the compare-only execution drag verdict layer for whether measured fill conversion, slippage, latency, fee drag, reconciliation, and coverage are still within current live-confidence tolerance.
  `forward_stress_regime_validation_summary` is the compare-only generalization confidence layer for whether current walk-forward proxy, stress evidence, replay lineage, and regime/session split still support the existing validation posture.
  `kill_condition_automation_summary` is the compare-only stop-review layer for whether current risk, friction, generalization, reconciliation, and manual-override context justify throttle, close-only, or kill-switch review.
  `b_continuation_edge_validation_summary` is the compare-only B diversification evidence layer for whether raw `trend_continuation` still has enough post-cost support and low-enough overlap to justify guarded B confidence.
  `strategy_cluster_balance_summary` is the compare-only A/B mix posture layer for whether the current runtime still looks A-concentrated, is building guarded B diversification, or is already balanced enough to hold.
  `a_strategy_post_cost_edge_validation_summary` is the compare-only A-anchor evidence layer for whether raw `sweep_reversal` still has enough post-cost support to justify the current anchor confidence.
  `rollout_recommendation_summary` is the compare-only recommendation layer for family rollout review.
  `strategy_lifecycle_summary` is the compare-only governance posture layer for family promotion, probation, degradation, and retirement language.
  `promotion_review_queue_summary` is the compare-only cross-family ordering layer for what promotion review should be looked at first.
  `promotion_remediation_queue_summary` is the compare-only cross-family guardrail-clearing queue for what should be fixed first before promotion review reopens.
  `promotion_clearance_tracker_summary` is the compare-only family progress tracker for what guardrail domains remain blocked versus already cleared.
  `promotion_reopen_queue_summary` is the compare-only cross-family review re-open queue for what can be revisited first once clearance improves.
  `promotion_decision_brief_summary` is the compare-only single-family case brief for how the current headline promotion case should be read right now.
  `promotion_lifecycle_history_summary` is the compare-only durable lineage layer for what actually changed over recent promotion, remediation, clearance, reopen, and auto-execution events.
  `research_promotion_operating_loop_summary` is the compare-only operating bridge for whether a family is still in research backlog, ready for shadow testing, approaching probation review, or already in promotion followthrough.
  `positive_evidence_expansion_summary` is the compare-only controlled positive review layer for families that may be ready for expansion review.
  `outcome_bucket_granularity_summary` is the compare-only condition split layer for volatility, cost, and liquidity proxy buckets under the family headline.
  `opportunity_capture_summary` is the compare-only throughput explanation layer for scarcity, blocking, and fill bottlenecks.
  `capital_allocator_summary` explains how family-level scarce capital tilt changes portfolio allowance without changing approval authority.
- `POST /operations/checklist`
  Operator go/no-go and playbook action based on validation, runtime, and alert evidence.
  It now also exposes `approval_strip_summary`, so the checklist topline uses the same `approve -> align -> act` vocabulary as validation, the operator UI, and session handoff.
  It includes `outcome_control_trace`, `money_funnel`, `outcome_attribution`, `rollout_recommendation`, `strategy_lifecycle`, `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`, `promotion_clearance_tracker`, `promotion_reopen_queue`, `promotion_decision_brief`, `auto_promotion_rollout_execution`, `promotion_lifecycle_history`, `research_promotion_operating_loop`, `multi_strategy_ab_expansion`, `b_continuation_activation`, `execution_friction_measurement`, `forward_stress_regime_validation`, `kill_condition_automation`, `b_continuation_edge_validation`, `strategy_cluster_balance`, `a_strategy_post_cost_edge_validation`, `positive_evidence_expansion`, `outcome_bucket_granularity`, `opportunity_capture`, and `capital_allocator` as operator-facing review items.
  `money_funnel` and `outcome_attribution` stay advisory-only inside the checklist: they are there to expose expected-R leakage and post-cost drag decomposition without creating a second approval authority.
- `GET /validation/alpha-research`
  Research backlog for quality-gate near-miss candidates prioritized by reason, family, regime, and session.

`GET /scanner/top` and `GET /portfolio/budget` may include `reaction_evidence`, `location_reference`, `session_liquidity_reference`, `strategy_cluster`, `strategy_cluster_status`, `multi_strategy_overlay`, `b_continuation_activation`, and `strategy_cluster_balance`.
These are compare-only readability aliases for operators. They do not replace `reaction_classification`, `reaction_input`, `strategy_family`, `strategy_grade`, or `recommended_risk_r`.

## API Quick Path

- `GET /health/ready`
  First readiness check before using any operator surface.
- `GET /execution/operator-dashboard?symbol=BTCUSDT&universe=micro_live_usdt_11&days=7`
  Main runtime operating payload.
- `GET /execution/operator-ui?symbol=BTCUSDT&universe=micro_live_usdt_11&days=7`
  Browser operator surface.
- `GET /portfolio/budget?universe=micro_live_usdt_11&limit=11&write_report=true`
  Portfolio headroom and blocked-reason review.
- `POST /validation/report?symbol=BTCUSDT`
  Final deployment approval summary and research outputs.
- `POST /operations/checklist?symbol=BTCUSDT&universe=micro_live_usdt_11`
  Final operator checklist and playbook output.
- `GET /validation/alpha-research?universe=micro_live_usdt_11&symbol=BTCUSDT&write_report=true`
  Quality near-miss research backlog.
- `POST /execution/plans/preview`
  Preview executable contract for a plan before approval.
- `POST /execution/approve-plan`
  Get rollout-aware approval result for a plan.
- `POST /alerts/test`
  Send an operator alert smoke test through the configured alert pipeline.
  The response now also carries `approval_strip_summary`, so manual alert drills can be read in the same `approve -> align -> act` vocabulary before falling back to raw deployment/playbook debug fields.

## Full API Catalog

Read surfaces are separated from execution mutations, operational controls, and internal/background endpoints.

### Runtime Read Surfaces

- `GET /health/live`
- `GET /health/ready`
- `GET /zones`
- `GET /plans/top`
- `GET /scanner/top`
- `GET /portfolio/budget`
- `GET /indicators/summary`
- `GET /indicators/chart`
- `GET /indicators/pine`
- `GET /indicators/pine-script`
- `GET /execution/operator-ui`
- `GET /execution/operator-dashboard`
- `GET /execution/quality`
- `GET /execution/safety-state`
- `GET /alerts/metrics`
- `GET /metrics/strategy`

### Execution Actions

- `POST /execution/plans/preview`
- `POST /execution/approve-plan`
- `POST /execution/order-intents`
- `POST /execution/submit`
- `POST /execution/reconcile`
- `POST /tv/webhook`

### Operational Controls And Operator Actions

- `POST /execution/control/kill-switch`
- `POST /execution/control/close-only`
- `POST /execution/control/kill-condition/apply`
- `POST /execution/control/rollout-policy`
- `POST /operations/checklist`
- `POST /alerts/subscribe`
- `POST /alerts/test`

### Validation And Research

- `GET /validation/feature-importance`
- `GET /validation/feature-calibration`
- `GET /validation/importance-calibration`
- `GET /validation/pbo-dsr/artifact-store`
- `GET /validation/pbo-dsr/trial-writer`
- `GET /validation/pbo-dsr/threshold-runner`
- `GET /validation/pbo-dsr`
- `GET /validation/scalp-experiment`
- `GET /validation/alpha-research`
- `GET /validation/stress-replay-assessment`
- `GET /validation/stress-replay-lineage`
- `GET /validation/stress-replay-runner-contract`
- `GET /validation/stress-replay-lineage-writer`
- `GET /validation/stress-replay-output-artifacts`
- `POST /validation/stress-replay-worker/prototype`
- `POST /validation/report`

### Internal, Exchange, And Background

- `GET /internal/alerts/retry-queue/status`
- `POST /internal/alerts/retry-queue/process`
- `POST /internal/alerts/retry-queue/dead-letter/requeue`
- `POST /internal/execution/fills`
- `POST /internal/demo/bootstrap`
- `POST /internal/binance/sync`
- `POST /internal/binance/sync-universe`
- `POST /internal/binance/order`
- `GET /internal/binance/order`
- `DELETE /internal/binance/order`
- `POST /internal/binance/user-stream/listen-key`
- `PUT /internal/binance/user-stream/listen-key`
- `DELETE /internal/binance/user-stream/listen-key`
- `POST /internal/binance/user-stream/process`
- `POST /internal/binance/user-stream/event`
- `POST /internal/binance/positions/sync`
- `GET /internal/binance/positions`
- `POST /internal/events/reprocess`
- `GET /internal/events/outbox/status`

## Docs Index

### System Planning

Start with `docs/PLAN.md` for the project map, then `docs/CONTEXT_NOTE.md` for operating constraints.

- `docs/CURRENT_SYSTEM_STATE.md`
- `docs/PLAN.md`
- `docs/CONTEXT_NOTE.md`
- `docs/CHECKLIST.md`
- `docs/README_DOC_SYNC_POLICY.md`
- `docs/UPGRADE_ROADMAP_VNEXT.md`
- `docs/SELF_CHECK_LOG.md`

### Strategy And Validation

Start with `docs/STRATEGY_V2_BLUEPRINT.md` for the strategy lens, then `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md` for live operator rules, `docs/STRATEGY_OPERATING_MANUAL.md` for the runtime model, and `docs/STRATEGY_V2_ACCEPTANCE_REJECTION_SPEC.md` for reaction semantics.

- `docs/STRATEGY_V2_BLUEPRINT.md`
- `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md`
- `docs/STRATEGY_OPERATING_MANUAL.md`
- `docs/STRATEGY_V2_ACCEPTANCE_REJECTION_SPEC.md`
- `docs/STRATEGY_V2_VALIDATION_PROTOCOL.md`
- `docs/STRATEGY_V2_IMPLEMENTATION_CHECKLIST.md`
- `docs/STRATEGY_V2_TRANSITION_REGIME_SPEC.md`
- `docs/STRATEGY_V2_THESIS_FINGERPRINT_SPEC.md`
- `docs/STRATEGY_V2_EXIT_EVENT_SCHEMA.md`
- `docs/STRATEGY_V2_PBO_DSR_DESIGN.md`
- `docs/INTRADAY_COMPOUND_SCALPER_RESEARCH.md`

### Operations

Start with `docs/AUTO_TRADING_OPERATING_RUNBOOK.md` for daily operations, then `docs/AUTO_TRADING_LIVE_GO_LIVE_CHECKLIST.md` before live changes.
If you use TradingView during triage, pair this runbook with `docs/TRADINGVIEW_PINE_MIRROR_GUIDE.md` for mirror-only usage and chart-side limits.

- `docs/AUTO_TRADING_OPERATING_RUNBOOK.md`
- `docs/LIVE_ALPHA_OPERATING_ROUTINE.md`
- `docs/AUTO_TRADING_LIVE_GO_LIVE_CHECKLIST.md`
- `docs/AUTO_TRADING_INCIDENT_DRILL_PLAYBOOK.md`

### TradingView

Start with `docs/TRADINGVIEW_PINE_MIRROR_GUIDE.md` for mirror setup and context-surface usage.
After chart triage, move into `docs/AUTO_TRADING_OPERATING_RUNBOOK.md` for the full server-side operator flow.

- `docs/TRADINGVIEW_PINE_MIRROR_GUIDE.md`

## Quick Start

Create a local environment and start the API:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
```

For a safe local/runtime configuration baseline, copy [.env.example](/Users/yumin/Documents/trading/.env.example) to `.env` and fill only the secrets and live toggles you intentionally need. The example keeps actual Binance live submit disabled by default while documenting the current MICRO_LIVE route and tuned pacing.

Run the baseline test suite:

```bash
pytest -q -rs
```

Try two requests immediately after the server starts:

```bash
curl -s "http://127.0.0.1:8000/health/ready" | jq
curl -s "http://127.0.0.1:8000/execution/operator-dashboard?symbol=BTCUSDT&universe=micro_live_usdt_11&days=7" | jq
```

If you need live Binance user-stream or integration extras:

```bash
pip install -e '.[integration]'
```

## Ops Commands

Near-100 hardening plan:

- [docs/MICRO_LIVE_NEAR_100_HARDENING_PLAN.md](/Users/yumin/Documents/trading/docs/MICRO_LIVE_NEAR_100_HARDENING_PLAN.md)

Current MICRO_LIVE route and pacing:

- [docs/CURRENT_SYSTEM_STATE.md](/Users/yumin/Documents/trading/docs/CURRENT_SYSTEM_STATE.md)
- [docs/MICRO_LIVE_CURRENT_STATE.md](/Users/yumin/Documents/trading/docs/MICRO_LIVE_CURRENT_STATE.md)

MICRO_LIVE preflight:

```bash
./.venv/bin/python scripts/run_micro_live_preflight.py --symbol BTCUSDT --days 7 --request-timeout 20
```

The current MICRO_LIVE setup must keep `.env` allowlists, direction contracts, strategy-family allowlists, entry-model allowlists, worker WS universe, event-blackout coverage, and fail-closed liquidity gates aligned before live orders are allowed.
The preflight output now includes `approval_surfaces`, `edge_experiment_review`, `edge_evolution_rule`, `review_followup_ledger`, `config_drift_checks`, and representative accepted/blocked candidate split focus, so dashboard, validation, checklist, runtime config drift, the current entry/execution hypothesis, the current allocation/promotion posture, and the latest packet carryover state can be read together before final live sign-off.
Use `--check-binance-rules` when you want the same run to fetch Binance `exchangeInfo` and verify current live symbol quantity/tick rules.
When split review targets are available, the preflight `next_steps` now also prints a ready-to-run `scripts/run_split_review_followup.py` command for the current symbol.

Macro blackout contract refresh, when the configured horizon is stale or missing:

```bash
./.venv/bin/python scripts/build_micro_live_event_blackouts.py \
  --years 2026,2027 \
  --output reports/validation/contracts/micro_live_event_blackouts_major_us_macro_auto.json
```

If `--symbols`, `--families`, and `--entry-models` are omitted, the builder uses the current MICRO_LIVE settings. It parses the official Fed FOMC page, then tries the official BLS CPI/Employment Situation pages and BLS calendar ICS. If BLS blocks automated access, it can recover missing windows from the currently configured fallback contract and reports `PASS_WITH_WARNINGS` instead of overwriting silently.
After generating a refreshed contract, point `AUTO_TRADING_MICRO_LIVE_EVENT_BLACKOUT_PATH` at that output before rerunning preflight/runtime guard.

Fast runtime guard without the slower local API surfaces:

```bash
./.venv/bin/python scripts/run_micro_live_runtime_guard.py --days 30
```

This guard fails on blocking config drift, expired/too-short macro blackout horizon, live allowlist/worker-universe mismatch, or missing fail-closed liquidity protection, and also summarizes whether recent live intents were blocked before submission.

Live order lifecycle report:

```bash
./.venv/bin/python scripts/run_live_order_lifecycle_report.py --days 30
```

This report joins intent, submission, fill, and Binance ledger rows so "no trade" can be separated into no signal, approval blocked, submit skipped, submitted without fill, rejected/error, open after entry, or closed.

Dry-run the MICRO_LIVE submit path through sizing and liquidity checks without placing an order:

```bash
./.venv/bin/python scripts/run_micro_live_synthetic_canary.py --no-network
```

No-order watchdog for periods where live intents accumulate but no live order is submitted:

```bash
./.venv/bin/python scripts/run_micro_live_no_order_watchdog.py --days 3 --no-fail-exit
```

Add `--notify` to send a concise Discord/system alert when the watchdog detects live intents without live submissions. Cooldown is state-file based, so repeated identical alerts are suppressed by default.
When the WS worker has restarted, the watchdog evaluates the active no-order alert from `runtime_started_at` so stale pre-restart blockers do not fire as new runtime failures, but it also includes `lookback_lifecycle_summary` for the full `--days` window. This keeps "runtime is currently clean" separate from "what happened over the last 3 days." The watchdog also writes `latest.md` and `latest.json` beside timestamped reports, and it only records notification cooldown after confirmed delivery.

Live reconciliation watchdog for stale submissions, ledger mismatches, user-stream gaps, or fresh critical reconciliation events:

```bash
./.venv/bin/python scripts/run_live_reconciliation_watchdog.py --days 3 --no-fail-exit
```

Add `--notify` for concise Discord/system alerts. This is the check that catches "submitted locally, but exchange/user-stream state did not settle" before it becomes a silent execution gap.

Boot check before starting or restarting the live worker:

```bash
./.venv/bin/python scripts/run_micro_live_boot_check.py --days 3 --limit 200 --no-fail-exit
```

This composes runtime guard, reconciliation watchdog, and the synthetic submit canary. It never sends a live order.
When `AUTO_TRADING_EXECUTION_MODE` is `MICRO_LIVE` or `LIVE`, [scripts/run_worker.py](/Users/yumin/Documents/trading/scripts/run_worker.py) now runs this boot check before starting. Use `--skip-boot-check` only for an explicit emergency/debug bypass.

Binance trading-rule drift snapshot:

```bash
./.venv/bin/python scripts/run_binance_rule_drift_snapshot.py
```

This snapshots each live symbol's `quantity_step`, `min_quantity`, `tick_size`, precision, status, and contract type from Binance `exchangeInfo`, then compares against the latest saved snapshot.

Live-vs-replay parity audit:

```bash
./.venv/bin/python scripts/run_live_replay_parity_audit.py --symbol BTCUSDT --days 30 --no-fail-exit
./.venv/bin/python scripts/run_live_replay_parity_audit.py --all-live-symbols --days 3 --no-fail-exit
```

This compares live active-contract cadence against the operator-dashboard replay flow baseline and attaches recent live intent/submission block reasons. It computes the active-contract cadence and replay baseline directly from local DB/files first, then falls back to the local API, so the audit is not dependent on the web server being up. `--all-live-symbols` aggregates the current 11-symbol live universe. When a WS worker `started_at` heartbeat exists, the active parity window defaults to `runtime_since_ws_start`; the full `--days` window remains in `lookback_evaluation_summary`. Use `--lookback-only` when you intentionally want the historical window as the headline. A runtime window with fewer than two expected replay candidates and no live intent/submission is treated as candidate wait, not a current flow warning. Portfolio `ALERT` is reserved for aggregate flow shortfall or material per-symbol shortfall; short non-runtime per-symbol windows with fewer than two expected replay candidates are `WATCH` unless an intent-to-submission or exchange reject/error problem is present. Portfolio `WATCH` reasons separate thin live flow (`portfolio_symbol_live_flow_watch_thin_window`) from order-gate waiting (`portfolio_symbol_order_flow_blocked_or_waiting`) and mixed cases (`portfolio_symbol_live_flow_and_order_gate_watch`). Each symbol also gets a `flow_diagnosis.stage`, such as `signal_or_plan_generation_gap`, `approval_gate_blocked`, `intent_to_submission_gap`, or `exchange_submission_rejected_or_error`. A symbol can be `WATCH` even when replay cadence is sufficient if all recent intents are blocked before order submission. The audit writes timestamped reports plus `latest.md` and `latest.json` for stable operator reads.

When an intent is blocked by `validation_do_not_deploy`, the approval snapshot and lifecycle reports include `validation_block_detail.primary_cause` plus `root_causes`, so the operator can distinguish missing validation sample, non-positive expectancy, zero/missing win rate, score floor failure, risk-gate closure, and runtime candidate blocks without reading raw logs.

Replay validation bridge audit:

```bash
./.venv/bin/python scripts/run_replay_validation_bridge.py --all-live-symbols --no-fail-exit
```

This is audit-only and does not change live approval. It checks whether the current replay cache clears conservative bridge floors before any manual review of replay-backed MICRO_LIVE sampling. The bridge now requires both headline expectancy and a non-negative `ev_r_lower_95`, and it adds material slice diagnostics for `direction`, `strategy_family`, and `entry_model`. `ELIGIBLE_FOR_MANUAL_BRIDGE_REVIEW_WITH_SLICE_WARNINGS` is not a clean approval; it means the aggregate passed but at least one material slice needs manual review first. The default action remains to keep the validation gate closed unless an operator explicitly reviews the bridge output.
The bridge writes `latest.md` and `latest.json` beside timestamped reports for stable operator reads. Operational timestamp reports and latest/state aliases are written with atomic replace where these guards are on the live operating path, so interrupted runs should not leave partial reports as operator evidence.

MICRO_LIVE safety drag and pacing grid search:

```bash
./.venv/bin/python scripts/run_micro_live_safety_drag_audit.py --backtest-report reports/validation/micro_main_usdt_proxy_backtests/micro_main_usdt_proxy_backtest_20260515T175711Z.json --no-write-report
./.venv/bin/python scripts/run_micro_live_safety_grid_search.py --backtest-report reports/validation/micro_main_usdt_proxy_backtests/micro_main_usdt_proxy_backtest_20260515T175711Z.json --no-write-report
```

The drag audit measures the current `.env` settings. The grid search separates deployable recommendations from raw diagnostics where safety may be disabled.

Session impulse retest runtime audit:

```bash
./.venv/bin/python scripts/run_session_impulse_retest_runtime_audit_report.py --hours 3 --no-fail-exit
```

This summarizes DB-backed `session_impulse_retest` refresh/auto-route audit rows, including signal generation, no fresh candidate, policy-disabled route, WS-route suppression, intent creation failure, submit error, and submitted states. It writes timestamped reports plus `latest.md` and `latest.json` atomically so no-order investigations can start from a stable path.

Scheduled guard heartbeat:

```bash
./.venv/bin/python scripts/run_micro_live_ops_heartbeat.py --no-fail-exit
```

This checks whether runtime guard, no-order watchdog, reconciliation watchdog, synthetic canary, boot check, live/replay parity, replay validation bridge, session impulse retest runtime audit, failure-contract drill, Binance rule drift, and macro blackout reports are still being produced on time. It also reads the latest report content where possible, so a fresh `ALERT`, `WATCH`, `DRIFT`, or `FAIL` report is surfaced instead of being hidden behind a freshness-only `PASS`. The heartbeat row carries the child report reason in `report_reason/status_detail`, so a `live_replay_parity=WATCH` summary should include the actual reason such as `portfolio_symbol_live_flow_and_order_gate_watch` rather than a generic check-needed message. Discord operational formatting prioritizes `상태`, `긴급`, and `주의` lines, so the alert text itself should show the relevant WATCH/FAIL detail without opening the report first. Watch-only heartbeat messages with `fail=0` are titled as monitoring (`운영 관찰`) and say `WATCH는 자동 관찰; 반복/악화 시 해당 리포트 확인`; hard failures still use urgent check wording. Report jobs look for report files directly, not state files, and a checked report with no readable status is treated as a failure. Macro blackout contracts are checked for future event horizon directly from their `windows`, not just for file presence; heartbeat uses the configured `AUTO_TRADING_MICRO_LIVE_EVENT_BLACKOUT_PATH` before falling back to glob discovery, so it audits the same contract live approval uses. Stale blackout contract mtime is a `WATCH` when the horizon is still sufficient, while short/expired horizon remains a hard failure. Notifications separate `FAIL` items from `WATCH` items so urgent fixes are not mixed with review-only warnings, and repeated identical issue sets are cooldown-suppressed by default. Cooldown state is written only after confirmed delivery, so failed alert attempts do not suppress the next run. The script also writes `latest.md` and `latest.json` aliases beside timestamped reports for stable operator/dashboard reads, using atomic replace to avoid partial latest/state files.

MICRO_LIVE failure contract drill:

```bash
./.venv/bin/python scripts/run_micro_live_failure_drill.py --no-fail-exit
```

This non-live drill verifies that missing/stale/malformed reports, short macro blackout horizon, failed alert delivery, stale submitted orders without Binance ledger, submit-ready intents without submission, and runtime audit hard failures do not get hidden as `PASS`. It does not submit live orders or mutate live control switches. It writes timestamped reports plus `latest.md` and `latest.json` atomically under `reports/operations/micro_live_failure_drill`.

Generate optional macOS launchd plists for the operating guards:

```bash
./.venv/bin/python scripts/install_micro_live_ops_launchd.py
```

By default this only writes plists under `reports/operations/launchd`. Use `--install --load` only when you want macOS to actually run runtime guard, no-order watchdog, reconciliation watchdog, synthetic canary, boot check, ops heartbeat, replay validation bridge, session impulse retest runtime audit, failure-contract drill, rule drift, and macro calendar refresh on schedule. Generated and installed plist files are replaced atomically, and `launchctl bootstrap` failure exits non-zero instead of looking successful. Boot check also runs the failure-contract drill before a MICRO_LIVE/LIVE worker starts. The macro refresh job writes to `AUTO_TRADING_MICRO_LIVE_EVENT_BLACKOUT_PATH` when configured, including values supplied through `--env-file`, so the scheduled refresh updates the same blackout contract that live approval and heartbeat read.

Split review followup packet:

```bash
./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDT --universe micro_live_usdt_11 --days 7 --action auto
```

The followup packet turns the latest `operator_action_priority`, `edge_experiment_review`, and `edge_evolution_rule` into a concrete `selected_action + target_contract + review_steps` bundle, then appends the result to `review_followup_ledger`, so split review prep stops being a manual copy/paste exercise even when the top action is `reduce`, `promote`, or `kill-review`.
The intended live experiment loop is fixed: generate the packet from `operator_action_priority` or `top_action_followup_command`, run the real split observation in market, accumulate new closed trades, rerun `edge_experiment_review`, rerun `edge_evolution_rule`, and only then interpret `promote / reduce / kill-review`.
If the packet returns `NO_TARGET` or `NO_REVIEW_ACTION_AVAILABLE`, treat that as a blocker signal rather than an experiment result: clear approval blockers, restore target contract carryover, or wait for enough closed-trade evidence before trying to interpret edge evolution.
If the same packet already exists in fresh `READY` history, if the last packet for that action stalled at `NO_TARGET`, or if the same packet has already been generated three times in a row, `operator_action_priority` now suppresses that duplicate packet and surfaces the suppression through `blocking_signals` / `dedupe_suppressed_actions`.
After the operator has actually resolved a packet, append the outcome back into the same ledger with `./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDT --universe micro_live_usdt_11 --days 7 --action reduce_baseline_allocation_review --transition-status REDUCE_CONFIRMED` or another transition status (`ACKED`, `COMPLETED`, `REJECTED`, `PROMOTE_CONFIRMED`, `KILL_REVIEW_ESCALATED`). That transition history is what lets later `edge_evolution_rule` runs strengthen recommendation language instead of repeating a first-pass advisory forever.
The operator surface divergence snapshot, session brief, and stage monitor now also carry the same ready-to-run followup command on each `entry_timing_review_target` / `execution_style_review_target` line, preserve `top_action_followup_command` for non-split edge-evolution review actions, and surface `review_followup_ledger.last_status / last_action` so recent packet history survives handoff.
The server-side `operator_action_priority` payload now also carries `top_action_followup_command` plus per-row `next_actions[].followup_command` for split-review actions, so dashboard, validation, checklist, and UI can point to the same runnable packet command.

Paper candidate drill:

```bash
./.venv/bin/python scripts/run_paper_candidate_drill.py --submit-paper
```

The paper drill output now includes a derived `approval_strip_summary`, top-level `edge_experiment_review`, and `candidate_edge_experiment_focus`, so PAPER submit readiness and the current entry/execution split focus can be read in the same operator vocabulary.

Paper candidate watcher:

```bash
./.venv/bin/python scripts/watch_paper_candidate_drill.py --interval-seconds 900 --max-attempts 8 --submit-paper
```

The watcher output now also carries top-level `edge_experiment_review` plus `candidate_edge_experiment_focus`, so the final eligible attempt preserves the same split-test focus without reopening the nested drill payload.

Post-live pruning review:

```bash
./.venv/bin/python scripts/run_post_live_pruning_review.py --symbol BTCUSDT --days 7
```

The pruning review output now includes `approval_surfaces`, `edge_experiment_review`, `edge_evolution_rule`, `review_followup_ledger`, and representative accepted/blocked candidate split focus, so the reopen decision stays separate from the current split-test focus while still preserving whether the latest review packet actually resolved a runnable target.

Execution incident drill:

```bash
python scripts/run_execution_incident_drill.py --symbol BTCUSDT --family session_impulse_retest --scenario dashboard --scenario reconcile
```

Open the operator UI:

```bash
open "http://127.0.0.1:8000/execution/operator-ui?symbol=BTCUSDT&universe=micro_live_usdt_11&days=7"
```

## Notes

- Default database URL uses local SQLite for bootstrap.
- Production target is Postgres/TimescaleDB plus Redis.
- All timestamps are stored in UTC.
- Runtime settings load `.env` from the repository root, and relative SQLite URLs plus runtime safety/validation contract paths are anchored to the repository root to keep API, worker, and review processes on the same inputs.
- `app.services.execution` exports are lazy-loaded so direct service imports do not depend on import order during API, worker, script, or test startup.
- Repository read helpers keep one active implementation per method; `PlanRepository.list_recent(..., limit=...)` is part of the runtime/report contract and includes still-open plans whose `valid_until` remains in the requested window.
- Runtime contract JSON files accept either wrapped payloads like `{"blocked_buckets": [...]}` / `{"blocked_plan_ids": [...]}` or raw list payloads, and both live approval and walk-forward review use the same parser behavior. The macro blackout, strategy-time contract, and plan blocklist builders write these contracts atomically and include `output_path` in the saved payload.
- If a Binance live submit raises before exchange acknowledgement, the submission is recorded as `adapter=binance`, `state=SUBMITTED`, `submit_status=LIVE_SUBMIT_ERROR`, and `requires_reconciliation=true`. This intentionally blocks same-plan reentry and counts as live exposure until reconciliation proves the exchange did not accept the order.
- `/health/ready` checks `db`, `binance_rest`, `event_backend`, live worker heartbeats/PIDs, WS no-message timeout, and 1m/5m market-data freshness.
- Runtime scripts disable Pydantic plugin loading and bytecode writes by default for stable startup and cleaner git state.
- `POST /internal/binance/order` is a test order by default. Live submit or cancel opens only when `BINANCE_TRADE_LIVE_ENABLED=true` and the request payload sets `live=true`.
- `AUTO_TRADING_LIVE_LIQUIDITY_GATE_ENABLED=true` adds a final pre-submit live gate using Binance public order-book depth plus recent 1m turnover. It blocks or marks split-required when visible depth, spread, simulated slippage, or volume participation is outside configured limits. If `AUTO_TRADING_LIVE_LIQUIDITY_GATE_PARTIAL_SUBMIT_ENABLED=true`, split-required orders can be reduced to a safe first tranche and the remaining notional is recorded for a later same-thesis live signal, bounded by `AUTO_TRADING_LIVE_LIQUIDITY_GATE_MAX_TRANCHES`.
- `AUTO_TRADING_REPLAY_VALIDATION_BRIDGE_ENABLED=true` lets `session_impulse_retest` use the latest 3-year USDT proxy backtest plus yearly portfolio replay as validation evidence when the live DB sample is still below the confidence floor. It does not bypass runtime GO, session rollout, safety locks, liquidity, or existing sufficient live-sample failures.
- `session_impulse_retest` canary bootstrap uses the selected live/core universe and replay-validation bridge as the live authority. The short rolling shadow summary is a hard promotion gate only while the family is explicitly `shadow_only`; once live-enabled, `no_recent_closed_sample` / short-window shadow scarcity is advisory so the system does not deadlock at zero live closes.
- `POST /internal/binance/user-stream/process` requires the optional `websockets` dependency.
- Binance sync and backfill skip overlap history so older overlapping candles do not trigger reverse-timestamp failures.
- `/indicators/*`, Pine mirror output, and TradingView chart alerts are context surfaces. They do not replace execution approval or live runtime truth.
- Quality near-miss candidates routed to `/validation/alpha-research` remain research backlog entries. They do not bypass hard gates or rollout controls.

### TradingView Mirror

Copy the latest Pine script from the local API:

```bash
curl -s "http://127.0.0.1:8000/indicators/pine-script" -o trading_engine_v1_mirror.pine
```

Or open the tracked repo file directly:

```bash
cat /Users/yumin/Documents/trading/scripts/tradingview/trading_engine_v1_mirror.pine
```

Recommended usage:

- Chart timeframe: `5m`
- Regime timeframe input: `15`
- Default zone age: `48` bars on the `5m` chart
- Use it for context, zones, and setup triage
- Keep the server-side runtime and approval surfaces as the source of truth for `GET /plans/top`, `GET /scanner/top`, `POST /validation/report`, and `POST /operations/checklist`

For chart-side mirror usage, read `docs/TRADINGVIEW_PINE_MIRROR_GUIDE.md`. For the server-side operator flow after triage, follow `docs/AUTO_TRADING_OPERATING_RUNBOOK.md`.
A chart-side `CONFIRM` or `RESEARCH` setup remains context only; if it disagrees with server-side `Top Operator Action` or `Alpha-Research Next Step`, the server wins.

Built-in TradingView alert conditions:

- `Trading Engine Mirror Long`
- `Trading Engine Mirror Short`
- `Trading Engine Mirror Blocked`

## Optional Integrations

The default bootstrap path stays on local SQLite. Use these only for live exchange integration or a production storage path.

Install integration extras:

```bash
pip install -e '.[integration]'
```

Run the opt-in live Binance integration test:

```bash
RUN_BINANCE_LIVE=1 pytest -q tests/test_binance_live_integration.py
```

### Timescale And Postgres Migration

Use this path only when moving from local bootstrap to a production database stack.

Run schema migrations:

```bash
python scripts/run_timescale_migrations.py \
  --database-url postgresql+psycopg://user:pass@localhost:5432/trading \
  --migrations-dir scripts/migrations
```

Run end-to-end runtime validation:

```bash
python scripts/verify_timescale_runtime.py \
  --database-url postgresql+psycopg://user:pass@localhost:5432/trading
```

Run load and retention benchmark:

```bash
python scripts/benchmark_timescale_retention.py \
  --database-url postgresql+psycopg://user:pass@localhost:5432/trading \
  --symbol-count 20 \
  --candle-days 90 \
  --outcome-days 220 \
  --outcomes-per-symbol 1500 \
  --query-repeats 20 \
  --reset-target
```

## Report Generators

These commands are optional reporting helpers. They are not required for local bootstrap or the main operator path.

Parameter changelog:

```bash
python scripts/generate_parameter_changelog.py --trigger manual
```

Feature calibration report:

```bash
python scripts/generate_feature_calibration_report.py --symbol BTCUSDT --refresh
```

Feature calibration runtime prerequisites: `matched_samples >= feature_calibration_min_matches` and `baseline.generated_plans >= feature_calibration_min_generated_plans`.

Execution quality report:

```bash
python scripts/generate_execution_quality_report.py --symbol BTCUSDT --days 30
```

Execution quality uses `execution_fills` as the primary source for fill-rate, slippage, latency, and fees. `zone_outcomes` is only a fallback for older coverage.

Strategy family edge review:

```bash
./.venv/bin/python scripts/run_strategy_family_edge_review.py --family sweep_reversal --peer-family trend_continuation --days 180
./.venv/bin/python scripts/run_strategy_family_edge_review.py --family trend_continuation --peer-family sweep_reversal --days 180
```

Combined live alpha operating review:

```bash
./.venv/bin/python scripts/run_live_alpha_operating_review.py --days 180
```

Replay evidence review:

```bash
./.venv/bin/python scripts/run_replay_evidence_review.py --symbol BTCUSDT --days 180
```

## Execution Friction Measurement

`execution_quality + reconciliation + stress cost + approval cap reference -> execution_friction_measurement`

- `execution_friction_measurement` is the compare-only execution drag verdict layer. It does not replace raw execution ledgers, approval, sizing, or rollout authority.
- It compresses actual fill conversion, slippage, latency, fee drag, reconciliation integrity, and measurement coverage into `healthy_friction / watch_friction / degraded_friction / insufficient_measurement`.
- Validation, checklist, and dashboard can expose `execution_friction_measurement_summary` as the shared verdict for whether measured execution drag is still within current live-confidence tolerance.

## Forward Stress Regime Validation

`walk_forward + strategy_v2_validation + stress/replay lineage + regime/session split -> forward_stress_regime_validation`

- `forward_stress_regime_validation` is the compare-only generalization confidence layer. It does not replace raw validation artifacts, approval, sizing, or rollout authority.
- It compresses current forward proxy, stress verdict, replay lineage readiness, and regime/session split into `validated_generalization / fragile_generalization / insufficient_generalization / insufficient_evidence`.
- Validation, checklist, and dashboard can expose `forward_stress_regime_validation_summary` as the shared verdict for whether current validation evidence still generalizes beyond a narrow regime/session pocket.

## Kill Condition Automation

`risk_gate + safety_state + execution_friction_measurement + forward_stress_regime_validation + recent_reconciliation_summary -> kill_condition_automation`

- `kill_condition_automation` is the compare-only stop-review layer. It does not replace raw risk state, manual safety locks, approval, sizing, or rollout authority.
- It compresses current risk gate, measured friction, generalization confidence, reconciliation severity, and manual override context into `observe_only / throttle_review / close_only_review / kill_switch_review`.
- Validation, checklist, and dashboard can expose `kill_condition_automation_summary` as the shared verdict for whether current live evidence justifies only observation, throttle review, close-only review, or kill-switch review.
- First-wave write scope remains `proposal_only` unless a separate explicit arm opens live safety writes.
- `POST /execution/control/kill-condition/apply` is the explicit-arm executor wrapper for that summary. It stays dry-run by default and only writes live safety state when `allow_live_write=true`, `dry_run=false`, `KILL_CONDITION_AUTOMATION_LIVE_ENABLED=1`, and the supplied arm token matches `KILL_CONDITION_AUTOMATION_ARM_TOKEN`.
- For repeatable operator procedure, use [docs/KILL_CONDITION_AUTOMATION_LIVE_RUNBOOK.md](/Users/yumin/Documents/trading/docs/KILL_CONDITION_AUTOMATION_LIVE_RUNBOOK.md) and [scripts/run_kill_condition_automation.py](/Users/yumin/Documents/trading/scripts/run_kill_condition_automation.py).

Portfolio budget report:

```bash
python scripts/generate_portfolio_budget_report.py --universe micro_live_usdt_11 --limit 11
```

Alert metrics report:

```bash
python scripts/generate_alert_metrics_report.py --days 30
```

Alert retry queue processor:

```bash
python scripts/process_alert_retry_queue.py --limit 100
python scripts/process_alert_retry_queue.py --limit 100 --requeue-dead-letter
```

## Alert Wiring

Set channel credentials via environment variables:

```bash
export ALERT_DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
export ALERT_TELEGRAM_BOT_TOKEN="<telegram-bot-token>"
export ALERT_TELEGRAM_CHAT_ID="<chat-id>"
export ALERT_PUSH_WEBHOOK_URL="https://push-gateway.example/notify"
export ALERT_PUSH_BEARER_TOKEN="<optional-bearer-token>"
export VALIDATION_ALERT_CHANNEL="discord"  # telegram | discord | push | system
export ALERT_RETRY_ATTEMPTS="3"
export ALERT_RETRY_BACKOFF_SECONDS="0.4"
export ALERT_CIRCUIT_BREAKER_FAILURES="3"
export ALERT_CIRCUIT_BREAKER_COOLDOWN_SECONDS="90"
```

`VALIDATION_ALERT_CHANNEL=system` fans out to configured channels and uses the shared retry and circuit-breaker pipeline.

Send a channel smoke alert:

```bash
curl -X POST "http://127.0.0.1:8000/alerts/test" \
  -H "Content-Type: application/json" \
  -d '{"channel":"discord","symbol":"BTCUSDT","message":"validation pipeline alive"}'
```

## Worker

Run one-shot symbol sync plus event reprocess:

```bash
python scripts/run_worker.py --mode once --binance-sync --symbol BTCUSDT --reprocess-events
```

Run continuous universe sync every five minutes:

```bash
python scripts/run_worker.py --mode loop --sync-universe --limit-symbols 30 --symbol-concurrency 4 --interval-seconds 300
```

Run WebSocket stream ingest for one symbol:

```bash
python scripts/run_worker.py --ws-stream --symbol BTCUSDT --ws-intervals 5m,15m
```

Run WebSocket stream ingest for the top universe with live refresh:

```bash
python scripts/run_worker.py --ws-stream --sync-universe --limit-symbols 30 --ws-intervals 5m,15m
```

Worker note: the API is causal by design. Metrics and risk state are computed from historical outcomes only, and scanner ranking applies portfolio overlay by default through `portfolio_overlay_*` settings.
