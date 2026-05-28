# Nanyotti/Wonyotti Rotation Method System

Status: shadow policy implemented, live authority disabled by default

## 1. Boundary

Telegram messages, videos, PDFs, screenshots, and OCR are not live trading signals.
They are pattern samples used to build a deterministic market-data system.

The system must therefore answer this question on every generated plan:

```text
Does the current market state, location, and position-management context match
the rotation method well enough to allow risk, only a probe, reduce-only, or no trade?
```

## 2. Correct Definition

This method is not simple long/short alternation and not blind averaging down.

Working definition:

```text
Prioritize the side the market is currently rescuing, spend size only at clear
structure locations, reduce battle size on reaction, and repair trapped average
price only when the expected chart reaction can realistically cover the recovery
distance.
```

The core object is not an entry signal. It is position inventory control.

## 3. Runtime Layers

### Layer 1. Market State

Purpose: decide which side the market is rescuing.

Outputs:

- `primary_bias`: `long`, `short`, `neutral`
- `bias_strength`
- `side_alignment`: `with_trend`, `against_trend`, `neutral`
- `one_way_score`
- `one_way_risk`: `low`, `medium`, `high`

Rule:

```text
If one_way_risk is high and the candidate is against trend, averaging and battle
size are forbidden.
```

### Layer 2. Scenario Plan

Purpose: map the current zone to the message template: first, second, battle,
watch, invalidated, or retired.

Outputs:

- `side`
- `zone_role`
- `stage`: `probe`, `base`, `battle_candidate`, `watch`, `retired`
- `already_touched`
- `invalidation_price`
- `confidence`

Rule:

```text
First touch is a probe. Repeated touch or weak reaction lowers stage quality.
Battle is allowed only when location, reaction, and repair capacity agree.
```

### Layer 3. Location and RR

Purpose: prevent the bot from trading the center or chasing after the move.

Outputs:

- `bad_rr_state`: `acceptable`, `watch`, `bad_rr`
- `bad_rr_score`
- `risk_atr`
- `entry_offset_atr`
- `zone_width_atr`

Rule:

```text
Bad RR, wide/centered zone, late offset, or noisy execution defaults to observe,
probe-only, or no-trade.
```

### Layer 4. Inventory and Repair

Purpose: turn averaging into measurable repair, not hope.

Outputs:

- `expected_reaction_atr`
- `recovery_distance_atr`
- `repair_efficiency`
- `repair_action`
- `battle_permission`

Rule:

```text
repair_efficiency <= 0.6: repairable
0.6 < repair_efficiency <= 1.1: reduce battle size on reaction
1.1 < repair_efficiency <= 1.5: do not add; rotate loss or reduce
> 1.5: trapped average; reduce-only or switch after new structure
```

Current plan generation has no live inventory object attached, so the first
implementation uses plan risk distance as the recovery proxy and explicitly logs
`inventory_state.available = false`. This closes the design gap without pretending
that inventory-aware repair is already live.

### Layer 5. Execution Policy

Purpose: convert the method view into a risk lane.

Outputs:

- `entry_quality`: `A`, `B`, `C`, `NO_TRADE`
- `size_bias`: `normal`, `probe`, `reduced`, `observe`
- `position_management_bias`: `base_allowed`, `probe_only`, `reduce_only`
- `max_risk_multiplier`
- `shadow_recommended_risk_r`

Default authority:

```text
shadow_advisory_only
```

The system logs the policy and shadow sizing effect, but does not alter live
risk unless `nanyotti_rotation_method_sizing_overlay_apply_live` is explicitly
enabled and validated.

### Layer 6. Switch Policy

Purpose: block the wrong interpretation of "exit long then short immediately."

Allowed only when:

- previous side failed to recover inside expected reaction
- its structure/invalidation broke
- the opposite side has clearer structure
- the switch is not into a one-way opposing trend
- recovery math is still possible after realized loss

Runtime output:

- `switch_permission`
- `switch_blockers`

## 4. Holes Closed From Earlier Implementations

- Message prices are not used as live entries.
- Long and short are not alternated automatically.
- Battle size is separate from base/probe.
- Bad RR and center-zone states are explicit no-trade candidates.
- One-way trend blocks countertrend averaging.
- Repair is measured by expected reaction versus recovery distance.
- Repeated touches lower scenario quality.
- 10x leverage is treated as exposure/capacity, not an edge.
- The policy is logged in plan validity and sizing metadata.

## 5. Promotion Path

1. Shadow logging on all generated plans.
2. Backtest: filter plans by `entry_quality`, `one_way_risk`, and `bad_rr_state`.
3. Paper: require post-cost EV improvement and drawdown reduction.
4. Micro-live: enable sizing overlay only after enough closed samples.
5. Live: never enable blind battle adds without inventory-aware repair state.
