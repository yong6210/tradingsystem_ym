# Trading Engine v1

Verification-first trading engine that separates chart context, runtime candidate ranking, deployment approval, and live execution truth.
The current live strategy is an `A_ONLY`, verification-first reversal engine that validates HTF location, liquidity sweep, and post-sweep reaction before execution.

Primary audience: operators first, contributors second.

## What This System Is

Trading Engine v1 is a verification-first trading engine for operator-led automated trading.

- It treats `POST /validation/report` and `POST /operations/checklist` as the final approval surfaces.
- It treats scanner, portfolio, and operator surfaces as runtime decision support, not order authority by themselves.
- It currently operates with an `A_ONLY` live stance and prefers verification over signal proliferation.
- It tracks execution quality, fills, positions, alerts, and reconciliation as first-class operational signals.
- It keeps quality-gate near-miss candidates in a research backlog via `/validation/alpha-research` instead of silently dropping them.

If you only remember one rule: chart and scanner views explain what the engine sees, but rollout approval still comes from validation plus operations checklist.

## Strategy Lens

- Decision order: `state -> location -> liquidity -> reaction -> execution`.
- HTF location and liquidity come first. Lower-timeframe structure only refines execution.
- `OB/FVG` are execution zones, not standalone alpha.
- `BOS/CHoCH` are reaction evidence, not primary signals.
- `session box / opening range` are session liquidity references, not standalone entry triggers.
- `/scanner/top` and `/portfolio/budget` may expose `reaction_evidence`, `location_reference`, and `session_liquidity_reference` as compare-only readability aliases.
- The live source of truth remains `reaction_classification`, `reaction_input`, `strategy_family`, `strategy_grade`, and `recommended_risk_r`.

Final rollout approval still comes from `POST /validation/report` plus `POST /operations/checklist`.

## Start Here

See `Quick Start` below for copy-paste startup requests.

1. `GET /health/ready`
   Check database, exchange connectivity, and event backend readiness before looking at trading surfaces.
2. `GET /execution/operator-dashboard`
   See runtime funnel, safety state, recent intents, orders, positions, reconciliation, and portfolio summary in one payload.
3. `GET /portfolio/budget`
   Review exposure headroom, blocked reasons, accepted candidates, and alpha research backlog.
4. `POST /validation/report`
   Generate the deployment approval summary, validation stack, and research outputs for a symbol.
5. `POST /operations/checklist`
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
- `thin_activity_window` is treated as `observe`, not as an automatic negative verdict or threshold-relaxation trigger.

## Operator Surfaces

- `GET /execution/operator-dashboard`
  Runtime source for safety state, funnel, recent intents, open orders, positions, reconciliation, alert summary, and execution quality summary.
  It also surfaces `signal_funnel.operator_action_priority` with capture-aware review order, `signal_funnel.outcome_control_trace`, `signal_funnel.rollout_recommendation`, `signal_funnel.strategy_lifecycle`, `signal_funnel.promotion_governance`, `signal_funnel.promotion_review_queue`, `signal_funnel.promotion_remediation_queue`, `signal_funnel.promotion_clearance_tracker`, `signal_funnel.promotion_reopen_queue`, `signal_funnel.promotion_decision_brief`, `signal_funnel.auto_promotion_rollout_execution`, `signal_funnel.promotion_lifecycle_history`, `signal_funnel.research_promotion_operating_loop`, `signal_funnel.multi_strategy_ab_expansion`, `signal_funnel.b_continuation_activation`, `signal_funnel.execution_friction_measurement`, `signal_funnel.forward_stress_regime_validation`, `signal_funnel.kill_condition_automation`, `signal_funnel.strategy_cluster_balance`, `signal_funnel.opportunity_capture`, `signal_funnel.capital_allocator`, recent intent `outcome_approval_penalty`, and trimmed portfolio candidate drill-down rows.
- `GET /execution/operator-ui`
  Browser operator surface backed by the same runtime payloads, intended for day-to-day operating review.
  It now surfaces an `Approval Divergence` banner directly under `Decision Summary` so operators can see dashboard/checklist/validation/candidate deployment drift before reading deeper inspectors.
  It also surfaces an `A/B Strategy Posture` home-section panel so operators can read `multi_strategy_ab_expansion`, `b_continuation_activation`, and `strategy_cluster_balance` together without dropping into raw dashboard JSON.
  The same home section now includes `Promotion Operating Stack`, which compresses `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`, `promotion_clearance_tracker`, `promotion_reopen_queue`, `promotion_decision_brief`, `auto_promotion_rollout_execution`, `promotion_lifecycle_history`, and `research_promotion_operating_loop` into a single operator review surface.
  It also includes `Promotion Case Inspector`, which re-compresses the current headline promotion family into target posture, write scope, remaining guardrails, cleared guardrails, and next-move language.
  It also includes `Validation / Checklist Review Stack`, which lines up validation top-level summaries and checklist item statuses for rollout, A/B posture, promotion stack, opportunity capture, and capital allocation without requiring raw payload inspection.
  It also includes `Validation Case Inspector`, which re-compresses the current symbol validation case into outcome control, rollout, lifecycle, A/B posture, condition split, capture, allocator, and next-move language.
  It also includes `Runtime Quality Inspector`, which re-compresses recent validation alerts, retry queue pressure, execution quality, and reconciliation health into a single runtime operating-quality card.
  It also includes `Signal Funnel Inspector`, which re-compresses the current hard gate, softening queue, rollout block, and family/regime/session bottlenecks into a single funnel review card.
  It also includes `Alpha Research Inspector`, which re-compresses research backlog, recommended research action, top shadow experiment, softening review, and promotion watchlist into one home-section research card.
  It also includes `Kill Condition Inspector`, which re-compresses `signal_funnel.kill_condition_automation` into stop-review verdict, trigger axis, write scope, manual-override state, and current lock posture before any live stop is armed.
  It also includes `Policy / Lock Inspector`, which re-compresses kill switch, close-only, active locks, matching locks, and rollout policies into a single home-section policy card.
  It also includes `Intent / Exposure Inspector`, which re-compresses recent intents, open orders, open positions, and the current live exposure queue into a single home-section activity card.
  It also includes `Mode / Deployment Inspector`, which re-compresses execution mode, entry gate, dashboard/checklist/validation deployment posture, rollout recommendation, and mode advisory into a single home-section deployment card.
  It also includes `Approval Alignment Inspector`, which re-compresses dashboard/checklist/validation/candidate/operator-priority alignment into a single home-section approval card.
  It also includes `Data Freshness / Source Inspector`, which re-compresses generated timestamps, report windows, and source/report-path readiness for dashboard, validation, checklist, and execution-quality surfaces.
  It now also includes `Portfolio Candidate Drilldown` and `Checklist Evidence Drilldown`, so accepted/blocked candidate overlays and checklist evidence can be reviewed directly from the home section instead of through raw JSON blobs.
  It also includes a dedicated `Portfolio Candidate Inspector`, which expands one representative accepted row and one representative blocked row into risk, outcome bias, allocator, A/B posture, session, and reaction evidence cards.
  It also includes `Report Navigation`, which exposes local validation/checklist/execution-quality report paths as file links for deeper review after the home-section summary.
  For repeatable browser inspection and dry-run divergence capture, use [docs/OPERATOR_UI_HOME_INSPECTION_CHECKLIST.md](/Users/yumin/Documents/trading/docs/OPERATOR_UI_HOME_INSPECTION_CHECKLIST.md), [scripts/collect_operator_surface_divergence_snapshot.py](/Users/yumin/Documents/trading/scripts/collect_operator_surface_divergence_snapshot.py), [scripts/generate_operator_session_brief.py](/Users/yumin/Documents/trading/scripts/generate_operator_session_brief.py), [scripts/notify_operator_session_brief.py](/Users/yumin/Documents/trading/scripts/notify_operator_session_brief.py), [scripts/check_operator_session_brief_automation.py](/Users/yumin/Documents/trading/scripts/check_operator_session_brief_automation.py), and [scripts/check_operator_session_brief_delivery_preflight.py](/Users/yumin/Documents/trading/scripts/check_operator_session_brief_delivery_preflight.py). The notifier supports `system` or `discord` delivery plus separate `shift-start` and `shift-end` handoff formats, and live delivery now requires both `OPERATOR_BRIEF_DRY_RUN` unset and `OPERATOR_BRIEF_ALLOW_LIVE_SEND=1`. [docs/OPERATOR_SESSION_BRIEF_AUTOMATION.md](/Users/yumin/Documents/trading/docs/OPERATOR_SESSION_BRIEF_AUTOMATION.md) documents the tick wrapper, cron examples, launchd plists, automation health checks, and delivery preflight for split shift handoff loops.
- `GET /portfolio/budget`
  Exposure, headroom, blocked reasons, accepted candidates, and `alpha_research_candidates`.
  Accepted and blocked candidate rows may include `strategy_family`, `strategy_cluster`, `strategy_cluster_status`, `multi_strategy_overlay`, `b_continuation_activation`, `strategy_cluster_balance`, `strategy_sizing.outcome_risk_adjustment`, `outcome_bias`, and `capital_allocator` with `allocated_risk_r`.
- `POST /validation/report`
  Deployment approval summary plus the full validation and research stack for one symbol.
  It also includes `operator_action_priority_summary` with `priority_source`, `action_family`, and `capture_context`, plus `outcome_control_trace_summary` to explain how outcome-first controls are tightening approval, sizing, and ordering.
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
  It includes `outcome_control_trace`, `rollout_recommendation`, `strategy_lifecycle`, `promotion_governance`, `promotion_review_queue`, `promotion_remediation_queue`, `promotion_clearance_tracker`, `promotion_reopen_queue`, `promotion_decision_brief`, `auto_promotion_rollout_execution`, `promotion_lifecycle_history`, `research_promotion_operating_loop`, `multi_strategy_ab_expansion`, `b_continuation_activation`, `execution_friction_measurement`, `forward_stress_regime_validation`, `kill_condition_automation`, `b_continuation_edge_validation`, `strategy_cluster_balance`, `a_strategy_post_cost_edge_validation`, `positive_evidence_expansion`, `outcome_bucket_granularity`, `opportunity_capture`, and `capital_allocator` as operator-facing review items.
- `GET /validation/alpha-research`
  Research backlog for quality-gate near-miss candidates prioritized by reason, family, regime, and session.

`GET /scanner/top` and `GET /portfolio/budget` may include `reaction_evidence`, `location_reference`, `session_liquidity_reference`, `strategy_cluster`, `strategy_cluster_status`, `multi_strategy_overlay`, `b_continuation_activation`, and `strategy_cluster_balance`.
These are compare-only readability aliases for operators. They do not replace `reaction_classification`, `reaction_input`, `strategy_family`, `strategy_grade`, or `recommended_risk_r`.

## API Quick Path

- `GET /health/ready`
  First readiness check before using any operator surface.
- `GET /execution/operator-dashboard?symbol=BTCUSDC&universe=usdc_perp_top30&days=7`
  Main runtime operating payload.
- `GET /execution/operator-ui?symbol=BTCUSDC&universe=usdc_perp_top30&days=7`
  Browser operator surface.
- `GET /portfolio/budget?universe=usdc_perp_top30&limit=20&write_report=true`
  Portfolio headroom and blocked-reason review.
- `POST /validation/report?symbol=BTCUSDC`
  Final deployment approval summary and research outputs.
- `POST /operations/checklist?symbol=BTCUSDC&universe=usdc_perp_top30`
  Final operator checklist and playbook output.
- `GET /validation/alpha-research?universe=usdc_perp_top30&symbol=BTCUSDC&write_report=true`
  Quality near-miss research backlog.
- `POST /execution/plans/preview`
  Preview executable contract for a plan before approval.
- `POST /execution/approve-plan`
  Get rollout-aware approval result for a plan.
- `POST /alerts/test`
  Send an operator alert smoke test through the configured alert pipeline.

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

Run the baseline test suite:

```bash
pytest -q -rs
```

Try two requests immediately after the server starts:

```bash
curl -s "http://127.0.0.1:8000/health/ready" | jq
curl -s "http://127.0.0.1:8000/execution/operator-dashboard?symbol=BTCUSDC&universe=usdc_perp_top30&days=7" | jq
```

If you need live Binance user-stream or integration extras:

```bash
pip install -e '.[integration]'
```

## Ops Commands

MICRO_LIVE preflight:

```bash
./.venv/bin/python scripts/run_micro_live_preflight.py --symbol BTCUSDC --days 7
```

Paper candidate drill:

```bash
./.venv/bin/python scripts/run_paper_candidate_drill.py --submit-paper
```

Paper candidate watcher:

```bash
./.venv/bin/python scripts/watch_paper_candidate_drill.py --interval-seconds 900 --max-attempts 8 --submit-paper
```

Post-live pruning review:

```bash
./.venv/bin/python scripts/run_post_live_pruning_review.py --symbol BTCUSDC --days 7
```

Execution incident drill:

```bash
python scripts/run_execution_incident_drill.py --symbol BTCUSDC --scenario dashboard --scenario reconcile
```

Open the operator UI:

```bash
open "http://127.0.0.1:8000/execution/operator-ui?symbol=BTCUSDC&universe=usdc_perp_top30&days=7"
```

## Notes

- Default database URL uses local SQLite for bootstrap.
- Production target is Postgres/TimescaleDB plus Redis.
- All timestamps are stored in UTC.
- `/health/ready` checks `db`, `binance_rest`, and `event_backend`.
- `POST /internal/binance/order` is a test order by default. Live submit or cancel opens only when `BINANCE_TRADE_LIVE_ENABLED=true` and the request payload sets `live=true`.
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
python scripts/generate_feature_calibration_report.py --symbol BTCUSDC --refresh
```

Feature calibration runtime prerequisites: `matched_samples >= feature_calibration_min_matches` and `baseline.generated_plans >= feature_calibration_min_generated_plans`.

Execution quality report:

```bash
python scripts/generate_execution_quality_report.py --symbol BTCUSDC --days 30
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
python scripts/generate_portfolio_budget_report.py --universe usdc_perp_top30 --limit 20
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
  -d '{"channel":"discord","symbol":"BTCUSDC","message":"validation pipeline alive"}'
```

## Worker

Run one-shot symbol sync plus event reprocess:

```bash
python scripts/run_worker.py --mode once --binance-sync --symbol BTCUSDC --reprocess-events
```

Run continuous universe sync every five minutes:

```bash
python scripts/run_worker.py --mode loop --sync-universe --limit-symbols 30 --symbol-concurrency 4 --interval-seconds 300
```

Run WebSocket stream ingest for one symbol:

```bash
python scripts/run_worker.py --ws-stream --symbol BTCUSDC --ws-intervals 5m,15m
```

Run WebSocket stream ingest for the top universe with live refresh:

```bash
python scripts/run_worker.py --ws-stream --sync-universe --limit-symbols 30 --ws-intervals 5m,15m
```

Worker note: the API is causal by design. Metrics and risk state are computed from historical outcomes only, and scanner ranking applies portfolio overlay by default through `portfolio_overlay_*` settings.
