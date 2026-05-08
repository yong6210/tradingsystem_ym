from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RegimeKey = Literal[
    "trend",
    "transition",
    "range",
    "session_open",
    "volatility_expansion",
    "event_shock",
    "dead_market",
]

LifecycleStage = Literal["live", "shadow", "research", "watch", "rejected", "disabled"]


@dataclass(frozen=True)
class StrategyBlueprint:
    key: str
    display_name: str
    regimes: tuple[RegimeKey, ...]
    lifecycle: LifecycleStage
    thesis: str
    trigger_event: str
    confirmation: str
    preferred_entry_models: tuple[str, ...]
    exit_style: str
    risk_role: str
    thesis_collision_policy: str
    current_status: str
    next_validation_step: str


STRATEGY_BLUEPRINTS: tuple[StrategyBlueprint, ...] = (
    StrategyBlueprint(
        key="sweep_reversal",
        display_name="A / Sweep Reversal Anchor",
        regimes=("transition", "range"),
        lifecycle="live",
        thesis="Liquidity sweep into reclaim/rejection at zone extremes.",
        trigger_event="Prior liquidity taken, reclaim held, reversal acceptance confirmed.",
        confirmation="Reaction classifier plus family router to sweep_reversal.",
        preferred_entry_models=("LIMIT",),
        exit_style="Short-hold intraday mean-reversion to opposing liquidity.",
        risk_role="Primary anchor edge.",
        thesis_collision_policy="Owns thesis first; duplicate thesis blocks additional entries.",
        current_status="Current production anchor on BTC and research anchor on ETH.",
        next_validation_step="Keep baseline stable and compare only against selective overlays.",
    ),
    StrategyBlueprint(
        key="transition_edge_overlay",
        display_name="B / Transition Rescue Overlay",
        regimes=("transition",),
        lifecycle="shadow",
        thesis="Rescue false negatives caused by low_confluence in transition without changing entry semantics.",
        trigger_event="Baseline rejects low_confluence, but transition winner variant restores candidate quality.",
        confirmation="proof_reclaim_plus_one_bar plus transition-specific confluence override.",
        preferred_entry_models=("LIMIT",),
        exit_style="Same as sweep_reversal; no execution rewrite.",
        risk_role="Narrow rescue lane layered over A.",
        thesis_collision_policy="Never additive; only replacement approval for the same thesis cluster.",
        current_status="Shadow-only on BTCUSDC and ETHUSDC with kill switch and partial gate ready.",
        next_validation_step="Wait for shadow_pass_count > 0 before partial activation.",
    ),
    StrategyBlueprint(
        key="trend_continuation_pullback",
        display_name="C1 / Trend Continuation Pullback",
        regimes=("trend",),
        lifecycle="rejected",
        thesis="Structure-preserving pullback continuation in a clean trend.",
        trigger_event="Trend intact, shallow pullback, continuation reclaim.",
        confirmation="HTF alignment, structure persistence, pullback depth, liquidity ahead.",
        preferred_entry_models=("LIMIT", "CONFIRM"),
        exit_style="Intraday continuation to next liquidity step.",
        risk_role="Frequency complement to mean-reversion families.",
        thesis_collision_policy="Separate trend thesis; still blocked on identical symbol-direction cluster.",
        current_status="Repo-native BTC future-blind scan produced zero generated candidates.",
        next_validation_step="Do not extend this family without materially different event definition.",
    ),
    StrategyBlueprint(
        key="choch_displacement_reclaim",
        display_name="C2 / CHOCH Displacement Reclaim",
        regimes=("transition", "range"),
        lifecycle="research",
        thesis="Trade first structural break after a local trend fails, but only when displacement and reclaim confirm the change of state.",
        trigger_event="CHOCH followed by impulsive displacement and reclaim into imbalance or protected level.",
        confirmation="Break-of-structure event, displacement threshold, reclaim hold, session sanity filter.",
        preferred_entry_models=("LIMIT", "CONFIRM"),
        exit_style="Short-hold reversal or regime flip continuation depending post-break structure.",
        risk_role="High-selectivity state-change specialist.",
        thesis_collision_policy="Must not overlap with A/B thesis cluster on the same sweep event.",
        current_status="Best next candidate for a second family; not implemented yet.",
        next_validation_step="Build explicit event definition and future-blind research runner.",
    ),
    StrategyBlueprint(
        key="orb_breakout",
        display_name="C3 / Opening Range Breakout",
        regimes=("session_open",),
        lifecycle="research",
        thesis="Capture time-boxed opening imbalance once range breaks with enough follow-through.",
        trigger_event="Opening range forms, breakout occurs, retest or hold confirms direction.",
        confirmation="Session window, breakout distance, retest quality, blackout/news guard.",
        preferred_entry_models=("CONFIRM", "LIMIT"),
        exit_style="Momentum burst during the same session block.",
        risk_role="Time-based frequency engine.",
        thesis_collision_policy="Independent session thesis; symbol slot still shared.",
        current_status="Not yet implemented; strong candidate when a second family is needed.",
        next_validation_step="Prototype session box builder and event blackout contract.",
    ),
    StrategyBlueprint(
        key="session_auction_reclaim",
        display_name="C3b / Session Auction Reclaim",
        regimes=("session_open", "trend"),
        lifecycle="research",
        thesis="Trade post-open continuation only after the opening drive is reclaimed through VWAP or opening-range acceptance.",
        trigger_event="Opening auction drives away from balance, then pullback reclaims session VWAP/opening range in trend direction.",
        confirmation="Opening range width sanity, post-open drive threshold, VWAP/ORB reclaim hold, trend alignment.",
        preferred_entry_models=("LIMIT", "CONFIRM"),
        exit_style="Short-hold continuation during the same session auction.",
        risk_role="Candidate main engine for higher-frequency intraday continuation.",
        thesis_collision_policy="Independent session thesis; shares symbol slot with ORB and other intraday families.",
        current_status="Implemented as research-only specialist family; awaiting 365d future-blind scorecard.",
        next_validation_step="Run BTC/ETH matrix scan and decide PASS/WATCH/REJECT from post-cost EV and trade count.",
    ),
    StrategyBlueprint(
        key="volatility_expansion",
        display_name="C4 / Volatility Expansion",
        regimes=("volatility_expansion", "trend"),
        lifecycle="research",
        thesis="Trade the first clean release from compression when expansion is real rather than a fake break.",
        trigger_event="Compression regime ends, ATR/dispersion expands, structure confirms direction.",
        confirmation="Squeeze score, expansion threshold, continuation hold, fake-break rejection guard.",
        preferred_entry_models=("CONFIRM",),
        exit_style="Momentum carry until expansion fades.",
        risk_role="Non-reversal impulse specialist.",
        thesis_collision_policy="Independent expansion thesis; do not co-own with ORB on same event.",
        current_status="Not yet implemented; suitable after ORB/CHOCH research.",
        next_validation_step="Define squeeze metric and post-release acceptance criteria.",
    ),
    StrategyBlueprint(
        key="range_rotation",
        display_name="C5 / Range Rotation",
        regimes=("range",),
        lifecycle="research",
        thesis="Exploit bounded auction behavior by rotating from one side of a mature range to the other.",
        trigger_event="Range maturity confirmed, edge rejection forms, midpoint acceptance holds.",
        confirmation="Range box stability, failed break, liquidity sweep, midpoint hold.",
        preferred_entry_models=("LIMIT",),
        exit_style="Mean-revert across the range rather than to a small local target.",
        risk_role="Range-specific complement when transition edge is absent.",
        thesis_collision_policy="Can coexist with A only if thesis clusters are materially different.",
        current_status="Not yet tested separately from sweep_reversal.",
        next_validation_step="Separate mature range qualification from generic reversal flow.",
    ),
    StrategyBlueprint(
        key="liquidity_run_continuation",
        display_name="C6 / Liquidity Run Continuation",
        regimes=("trend", "volatility_expansion"),
        lifecycle="research",
        thesis="Interpret a sweep as continuation fuel instead of reversal when structure never actually fails.",
        trigger_event="Liquidity taken in trend direction, pullback absorbs, continuation acceptance follows.",
        confirmation="Trend regime, protected swing intact, continuation reclaim, liquidity still ahead.",
        preferred_entry_models=("LIMIT", "CONFIRM"),
        exit_style="Continuation to external liquidity.",
        risk_role="Mirror image to sweep_reversal; trend-side liquidity specialist.",
        thesis_collision_policy="Mutually exclusive with A/B on the same event.",
        current_status="Concept defined, not tested.",
        next_validation_step="Build explicit continuation-vs-reversal discriminator.",
    ),
    StrategyBlueprint(
        key="event_shock_imbalance",
        display_name="C7 / Event Shock Imbalance",
        regimes=("event_shock",),
        lifecycle="research",
        thesis="Trade short-lived directional inefficiency around macro or exchange event shock only when imbalance is clean and tradable.",
        trigger_event="Scheduled event or abnormal session shock produces directional imbalance with persistent spread normalization.",
        confirmation="Event whitelist, spread sanity, displacement threshold, no blackout conflict.",
        preferred_entry_models=("CONFIRM",),
        exit_style="Very short-hold post-event directional burst.",
        risk_role="Special situation alpha, not always-on.",
        thesis_collision_policy="Independent event thesis; disable if execution friction spikes.",
        current_status="Research only; unsuitable until explicit cost/slippage model exists.",
        next_validation_step="Add event calendar and friction-aware simulation.",
    ),
    StrategyBlueprint(
        key="capital_preservation_no_trade",
        display_name="Guard / No-Trade State",
        regimes=("dead_market",),
        lifecycle="live",
        thesis="Preserve capital when no verified edge regime is active.",
        trigger_event="No regime owns the state or downstream quality is impaired.",
        confirmation="Dead market / information failure / execution anomaly / kill switch.",
        preferred_entry_models=(),
        exit_style="No position.",
        risk_role="Mandatory capital preservation layer.",
        thesis_collision_policy="Overrides every family.",
        current_status="Already implicit in many guards; should remain explicit in routing decisions.",
        next_validation_step="Keep as an explicit regime in future routing dashboards.",
    ),
)


def list_blueprints(
    *,
    lifecycle: LifecycleStage | None = None,
    regime: RegimeKey | None = None,
) -> list[StrategyBlueprint]:
    blueprints = list(STRATEGY_BLUEPRINTS)
    if lifecycle is not None:
        blueprints = [item for item in blueprints if item.lifecycle == lifecycle]
    if regime is not None:
        blueprints = [item for item in blueprints if regime in item.regimes]
    return blueprints


def build_regime_matrix() -> dict[RegimeKey, list[str]]:
    matrix: dict[RegimeKey, list[str]] = {
        "trend": [],
        "transition": [],
        "range": [],
        "session_open": [],
        "volatility_expansion": [],
        "event_shock": [],
        "dead_market": [],
    }
    for blueprint in STRATEGY_BLUEPRINTS:
        for regime in blueprint.regimes:
            matrix[regime].append(blueprint.key)
    return matrix
