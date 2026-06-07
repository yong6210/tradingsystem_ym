#!/usr/bin/env python3
"""Build a repeatable shadow WFO plan for the v6 adaptive meta-router.

The plan is intentionally non-executing by default. It creates concrete,
copy-safe research commands that exercise the existing walk-forward engine with
explicit regime-router, runner-protection, base-pruning, probe-pruning, and
winner-capacity recipes. It never submits live orders.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]

DEFAULT_META_ROUTER_AUDIT = (
    "reports/validation/diagnostics/market_state_rotation_v6_adaptive_meta_router_audit/"
    "market_state_rotation_v6_adaptive_meta_router_audit.json"
)
DEFAULT_REPORT_DIR = "reports/validation/diagnostics/market_state_rotation_v6_meta_router_shadow_wfo_plan"
DEFAULT_SHADOW_WFO_ROOT = "reports/validation/diagnostics/market_state_rotation_v6_meta_router_shadow_wfo"


def _resolve(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    raw = Path(path)
    return raw if raw.is_absolute() else ROOT_DIR / raw


def _display_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _load_json_optional(path: str | Path | None) -> dict[str, Any] | None:
    resolved = _resolve(path)
    if resolved is None or not resolved.exists():
        return None
    return dict(json.loads(resolved.read_text(encoding="utf-8")))


def _enabled_experiments(meta_router_audit: dict[str, Any] | None) -> set[str]:
    if not meta_router_audit:
        return set()
    return {
        str(item.get("id"))
        for item in list(meta_router_audit.get("next_experiment_order") or [])
        if bool(item.get("enabled"))
    }


def _source_report(meta_router_audit: dict[str, Any] | None, fallback: str | None) -> str | None:
    if fallback:
        return fallback
    if meta_router_audit:
        value = meta_router_audit.get("input_walk_forward_report")
        if value:
            return str(value)
    return None


def _base_command(
    *,
    source_report: str,
    report_dir: str,
    fold_limit: int,
    fold_offset: int,
    warm_fold_offset_selection_state: bool,
    disable_source_replay_auto_warm_selection_state: bool,
    test_top_train_candidates: int,
    transition_trim_enabled: bool = True,
) -> list[str]:
    command = [
        ".venv/bin/python",
        "scripts/run_market_state_rotation_v6_walk_forward_validation.py",
        "--source-report",
        source_report,
        "--report-dir",
        report_dir,
        "--regime-router-enabled",
        "--test-top-train-candidates",
        str(max(1, int(test_top_train_candidates))),
        "--source-replay-watch-unresolved-material-drift",
        "--write-report",
    ]
    if transition_trim_enabled:
        command.extend(
            [
                "--router-transition-trim-modes",
                "one_way_chase,exhaustion_reversal,risk_off",
                "--router-transition-trim-fraction",
                "0.50",
                "--router-transition-trim-cooldown-bars",
                "288",
                "--router-risk-off-size-mult",
                "0.0",
            ]
        )
    if disable_source_replay_auto_warm_selection_state:
        command.append("--disable-source-replay-auto-warm-selection-state")
    if fold_limit > 0:
        command.extend(["--fold-limit", str(int(fold_limit))])
    if fold_offset > 0:
        command.extend(["--fold-offset", str(int(fold_offset))])
        if warm_fold_offset_selection_state:
            command.append("--warm-fold-offset-selection-state")
    return command


def _recipe_command(
    *,
    source_report: str,
    shadow_wfo_root: str,
    recipe_id: str,
    fold_limit: int,
    fold_offset: int,
    warm_fold_offset_selection_state: bool,
    disable_source_replay_auto_warm_selection_state: bool,
    test_top_train_candidates: int,
    args: list[str],
    transition_trim_enabled: bool = True,
) -> list[str]:
    command = _base_command(
        source_report=source_report,
        report_dir=f"{shadow_wfo_root}/{recipe_id}",
        fold_limit=fold_limit,
        fold_offset=fold_offset,
        warm_fold_offset_selection_state=warm_fold_offset_selection_state,
        disable_source_replay_auto_warm_selection_state=disable_source_replay_auto_warm_selection_state,
        test_top_train_candidates=test_top_train_candidates,
        transition_trim_enabled=transition_trim_enabled,
    )
    command.extend(args)
    return command


def _recipes(
    *,
    source_report: str,
    shadow_wfo_root: str,
    fold_limit: int,
    fold_offset: int,
    warm_fold_offset_selection_state: bool,
    disable_source_replay_auto_warm_selection_state: bool,
    test_top_train_candidates: int,
    enabled_experiments: set[str],
) -> list[dict[str, Any]]:
    def enabled(*experiment_ids: str) -> bool:
        return not enabled_experiments or any(item in enabled_experiments for item in experiment_ids)

    recipes = [
        {
            "id": "router_contract_observe_only",
            "enabled": enabled("router_contract_shadow_wfo"),
            "priority": 1,
            "goal": "turn on explicit market-state classification while preserving legacy sizing and exits.",
            "validates": ["router_contract_shadow_wfo", "paper_execution_parity_collection"],
            "command": _recipe_command(
                source_report=source_report,
                shadow_wfo_root=shadow_wfo_root,
                recipe_id="router_contract_observe_only",
                fold_limit=fold_limit,
                fold_offset=fold_offset,
                warm_fold_offset_selection_state=warm_fold_offset_selection_state,
                disable_source_replay_auto_warm_selection_state=disable_source_replay_auto_warm_selection_state,
                test_top_train_candidates=test_top_train_candidates,
                transition_trim_enabled=False,
                args=[
                    "--router-trend-reaction-size-mult",
                    "1.0",
                    "--router-one-way-chase-size-mult",
                    "1.0",
                    "--router-one-way-counter-size-mult",
                    "1.0",
                    "--router-range-probe-size-mult",
                    "1.0",
                    "--router-range-base-size-mult",
                    "1.0",
                    "--router-exhaustion-reversal-size-mult",
                    "1.0",
                    "--router-risk-off-size-mult",
                    "1.0",
                ],
            ),
        },
        {
            "id": "router_contract_conservative",
            "enabled": enabled("router_contract_shadow_wfo"),
            "priority": 2,
            "goal": "activate explicit mode routing without changing alpha modules aggressively.",
            "validates": ["router_contract_shadow_wfo"],
            "command": _recipe_command(
                source_report=source_report,
                shadow_wfo_root=shadow_wfo_root,
                recipe_id="router_contract_conservative",
                fold_limit=fold_limit,
                fold_offset=fold_offset,
                warm_fold_offset_selection_state=warm_fold_offset_selection_state,
                disable_source_replay_auto_warm_selection_state=disable_source_replay_auto_warm_selection_state,
                test_top_train_candidates=test_top_train_candidates,
                args=[
                    "--router-trend-reaction-size-mult",
                    "1.0",
                    "--router-one-way-chase-size-mult",
                    "1.0",
                    "--router-one-way-counter-size-mult",
                    "0.0",
                    "--router-range-probe-size-mult",
                    "0.25",
                    "--router-range-base-size-mult",
                    "0.0",
                    "--router-exhaustion-reversal-size-mult",
                    "0.25",
                    "--router-exhaustion-min-score-edge",
                    "2",
                    "--router-exhaustion-min-extension-atr",
                    "1.5",
                ],
            ),
        },
        {
            "id": "mode_loss_abstain_soft",
            "enabled": enabled("router_contract_shadow_wfo", "range_structure_classifier"),
            "priority": 3,
            "goal": "preserve trend/risk-off alpha while softly abstaining from weak range, counter, and exhaustion pockets.",
            "validates": ["router_contract_shadow_wfo", "range_structure_classifier"],
            "command": _recipe_command(
                source_report=source_report,
                shadow_wfo_root=shadow_wfo_root,
                recipe_id="mode_loss_abstain_soft",
                fold_limit=fold_limit,
                fold_offset=fold_offset,
                warm_fold_offset_selection_state=warm_fold_offset_selection_state,
                disable_source_replay_auto_warm_selection_state=disable_source_replay_auto_warm_selection_state,
                test_top_train_candidates=test_top_train_candidates,
                transition_trim_enabled=False,
                args=[
                    "--router-trend-reaction-size-mult",
                    "1.0",
                    "--router-one-way-chase-size-mult",
                    "1.0",
                    "--router-one-way-counter-size-mult",
                    "0.0",
                    "--router-range-probe-size-mult",
                    "0.50",
                    "--router-range-base-size-mult",
                    "0.0",
                    "--router-exhaustion-reversal-size-mult",
                    "0.50",
                    "--router-risk-off-size-mult",
                    "1.0",
                ],
            ),
        },
        {
            "id": "one_way_trim_tax_light",
            "enabled": enabled("one_way_runner_protection_ablation"),
            "priority": 4,
            "goal": "reduce one-way forced-trim churn without transition trims or risk-off deactivation.",
            "validates": ["one_way_runner_protection_ablation"],
            "command": _recipe_command(
                source_report=source_report,
                shadow_wfo_root=shadow_wfo_root,
                recipe_id="one_way_trim_tax_light",
                fold_limit=fold_limit,
                fold_offset=fold_offset,
                warm_fold_offset_selection_state=warm_fold_offset_selection_state,
                disable_source_replay_auto_warm_selection_state=disable_source_replay_auto_warm_selection_state,
                test_top_train_candidates=test_top_train_candidates,
                transition_trim_enabled=False,
                args=[
                    "--router-trend-reaction-size-mult",
                    "1.0",
                    "--router-one-way-chase-size-mult",
                    "1.0",
                    "--router-one-way-counter-size-mult",
                    "1.0",
                    "--router-range-probe-size-mult",
                    "1.0",
                    "--router-range-base-size-mult",
                    "1.0",
                    "--router-exhaustion-reversal-size-mult",
                    "1.0",
                    "--router-risk-off-size-mult",
                    "1.0",
                    "--one-way-trim-context-guard-count",
                    "2",
                    "--one-way-trim-context-window-bars",
                    "288",
                    "--one-way-trim-context-cooldown-bars",
                    "288",
                ],
            ),
        },
        {
            "id": "one_way_runner_protection",
            "enabled": enabled("one_way_runner_protection_ablation"),
            "priority": 5,
            "goal": "reduce one-way forced-trim tax while preserving invalidation exits.",
            "validates": ["one_way_runner_protection_ablation"],
            "command": _recipe_command(
                source_report=source_report,
                shadow_wfo_root=shadow_wfo_root,
                recipe_id="one_way_runner_protection",
                fold_limit=fold_limit,
                fold_offset=fold_offset,
                warm_fold_offset_selection_state=warm_fold_offset_selection_state,
                disable_source_replay_auto_warm_selection_state=disable_source_replay_auto_warm_selection_state,
                test_top_train_candidates=test_top_train_candidates,
                args=[
                    "--router-trend-reaction-size-mult",
                    "1.0",
                    "--router-one-way-chase-size-mult",
                    "1.10",
                    "--router-one-way-counter-size-mult",
                    "0.0",
                    "--router-range-probe-size-mult",
                    "0.20",
                    "--router-range-base-size-mult",
                    "0.0",
                    "--router-exhaustion-reversal-size-mult",
                    "0.20",
                    "--reaction-trim-trend-hold-trigger-mult",
                    "1.50",
                    "--one-way-trim-size-mult",
                    "0.75",
                    "--one-way-trim-context-guard-count",
                    "1",
                    "--one-way-trim-context-window-bars",
                    "288",
                    "--one-way-trim-context-cooldown-bars",
                    "1440",
                ],
            ),
        },
        {
            "id": "negative_base_context_pruning",
            "enabled": enabled("negative_base_context_pruning_ablation"),
            "priority": 6,
            "goal": "prune losing base contexts without blanket base-entry deletion.",
            "validates": ["negative_base_context_pruning_ablation"],
            "command": _recipe_command(
                source_report=source_report,
                shadow_wfo_root=shadow_wfo_root,
                recipe_id="negative_base_context_pruning",
                fold_limit=fold_limit,
                fold_offset=fold_offset,
                warm_fold_offset_selection_state=warm_fold_offset_selection_state,
                disable_source_replay_auto_warm_selection_state=disable_source_replay_auto_warm_selection_state,
                test_top_train_candidates=test_top_train_candidates,
                args=[
                    "--router-trend-reaction-size-mult",
                    "1.0",
                    "--router-one-way-chase-size-mult",
                    "1.0",
                    "--router-range-base-size-mult",
                    "0.0",
                    "--negative-base-context-reduce-after-selection",
                    "--negative-base-context-reduce-size-mult",
                    "0.0",
                    "--negative-base-context-reduce-min-loss-usd-units",
                    "50",
                    "--negative-base-context-reduce-min-add-count",
                    "1",
                    "--negative-base-context-reduce-max-contexts",
                    "3",
                ],
            ),
        },
        {
            "id": "probe_alpha_leak_pruning",
            "enabled": enabled("probe_alpha_leak_pruning_ablation", "range_structure_classifier"),
            "priority": 7,
            "goal": "allow only quality-gated MC12-style probes and keep MC04 observe-only.",
            "validates": ["probe_alpha_leak_pruning_ablation", "range_structure_classifier"],
            "command": _recipe_command(
                source_report=source_report,
                shadow_wfo_root=shadow_wfo_root,
                recipe_id="probe_alpha_leak_pruning",
                fold_limit=fold_limit,
                fold_offset=fold_offset,
                warm_fold_offset_selection_state=warm_fold_offset_selection_state,
                disable_source_replay_auto_warm_selection_state=disable_source_replay_auto_warm_selection_state,
                test_top_train_candidates=test_top_train_candidates,
                args=[
                    "--router-trend-reaction-size-mult",
                    "1.0",
                    "--router-one-way-chase-size-mult",
                    "0.90",
                    "--router-range-probe-size-mult",
                    "0.15",
                    "--router-range-base-size-mult",
                    "0.0",
                    "--near-miss-probe-units",
                    "0.005",
                    "--near-miss-probe-min-score",
                    "5",
                    "--near-miss-probe-min-score-edge",
                    "1",
                    "--near-miss-probe-min-reason-stack",
                    "1",
                    "--near-miss-probe-cooldown-bars",
                    "72",
                    "--near-miss-probe-max-extension-atr",
                    "1.75",
                    "--near-miss-probe-failure-guard-count",
                    "2",
                    "--near-miss-probe-failure-guard-window-bars",
                    "1440",
                    "--near-miss-probe-failure-cooldown-bars",
                    "4320",
                    "--near-miss-probe-allowed-soft-reasons",
                    "MC12_low_confluence",
                    "--near-miss-probe-allowed-alignments",
                    "with_trend",
                    "--near-miss-probe-allowed-execution-contexts",
                    "normal",
                    "--near-miss-probe-allowed-regimes",
                    "uptrend,downtrend",
                ],
            ),
        },
        {
            "id": "winner_only_capacity",
            "enabled": enabled("winner_only_capacity_ablation"),
            "priority": 8,
            "goal": "test extra capacity only after the trade validates the thesis.",
            "validates": ["winner_only_capacity_ablation"],
            "command": _recipe_command(
                source_report=source_report,
                shadow_wfo_root=shadow_wfo_root,
                recipe_id="winner_only_capacity",
                fold_limit=fold_limit,
                fold_offset=fold_offset,
                warm_fold_offset_selection_state=warm_fold_offset_selection_state,
                disable_source_replay_auto_warm_selection_state=disable_source_replay_auto_warm_selection_state,
                test_top_train_candidates=test_top_train_candidates,
                args=[
                    "--router-trend-reaction-size-mult",
                    "1.0",
                    "--router-one-way-chase-size-mult",
                    "1.0",
                    "--router-range-base-size-mult",
                    "0.0",
                    "--winner-pyramid-units",
                    "0.25",
                    "--winner-pyramid-min-profit-reaction",
                    "0.55",
                    "--winner-pyramid-min-score",
                    "6",
                    "--winner-pyramid-min-reason-stack",
                    "2",
                    "--winner-pyramid-cooldown-bars",
                    "24",
                    "--winner-pyramid-max-units",
                    "0.50",
                    "--winner-pyramid-max-extension-atr",
                    "2.75",
                ],
            ),
        },
    ]
    return recipes


def build_meta_router_shadow_wfo_plan(
    *,
    meta_router_audit: dict[str, Any] | None,
    source_report: str | None = None,
    input_meta_router_audit: str | None = None,
    shadow_wfo_root: str = DEFAULT_SHADOW_WFO_ROOT,
    fold_limit: int = 0,
    fold_offset: int = 0,
    warm_fold_offset_selection_state: bool = False,
    disable_source_replay_auto_warm_selection_state: bool = True,
    test_top_train_candidates: int = 2,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    resolved_source = _source_report(meta_router_audit, source_report)
    if not resolved_source:
        raise ValueError("source_report is required when the meta-router audit has no input_walk_forward_report")
    enabled = _enabled_experiments(meta_router_audit)
    recipes = _recipes(
        source_report=resolved_source,
        shadow_wfo_root=shadow_wfo_root,
        fold_limit=fold_limit,
        fold_offset=fold_offset,
        warm_fold_offset_selection_state=warm_fold_offset_selection_state,
        disable_source_replay_auto_warm_selection_state=disable_source_replay_auto_warm_selection_state,
        test_top_train_candidates=test_top_train_candidates,
        enabled_experiments=enabled,
    )
    enabled_recipes = [item for item in recipes if item.get("enabled")]
    return {
        "generated_at": generated_at.isoformat(),
        "status": "meta_router_shadow_wfo_plan_ready",
        "no_live_order_sent": True,
        "input_meta_router_audit": input_meta_router_audit,
        "source_report": resolved_source,
        "shadow_wfo_root": shadow_wfo_root,
        "fold_limit": int(fold_limit),
        "fold_offset": int(fold_offset),
        "warm_fold_offset_selection_state": bool(warm_fold_offset_selection_state),
        "disable_source_replay_auto_warm_selection_state": bool(
            disable_source_replay_auto_warm_selection_state
        ),
        "test_top_train_candidates": int(test_top_train_candidates),
        "safety_policy": {
            "research_only": True,
            "paper_or_live_execution": False,
            "live_allowed_candidate_count": 0,
            "requires_separate_readiness_and_execution_parity_after_wfo": True,
        },
        "enabled_experiment_ids_from_audit": sorted(enabled),
        "recipe_count": len(recipes),
        "enabled_recipe_count": len(enabled_recipes),
        "recipes": recipes,
        "next_action": "Run enabled commands as shadow WFO jobs, then feed the best report back into readiness and stress gates.",
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Market State Rotation V6 Meta-Router Shadow WFO Plan",
        "",
        f"- status: `{report.get('status')}`",
        f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
        f"- source_report: `{report.get('source_report')}`",
        f"- enabled_recipe_count: `{report.get('enabled_recipe_count')}`",
        "",
        "## Recipes",
        "",
    ]
    for item in list(report.get("recipes") or []):
        command = " ".join(str(part) for part in list(item.get("command") or []))
        lines.append(
            f"- `{item.get('id')}`: enabled=`{item.get('enabled')}`, priority=`{item.get('priority')}`, "
            f"goal=`{item.get('goal')}`"
        )
        lines.append(f"  - command: `{command}`")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a v6 adaptive meta-router shadow WFO command plan.")
    parser.add_argument("--meta-router-audit", default=DEFAULT_META_ROUTER_AUDIT)
    parser.add_argument("--source-report", default="")
    parser.add_argument("--shadow-wfo-root", default=DEFAULT_SHADOW_WFO_ROOT)
    parser.add_argument("--fold-limit", type=int, default=0)
    parser.add_argument("--fold-offset", type=int, default=0)
    parser.add_argument(
        "--warm-fold-offset-selection-state",
        action="store_true",
        help="Preserve full selection history when using --fold-offset. Omit for fast smoke checks.",
    )
    parser.add_argument(
        "--preserve-source-replay-auto-warm-selection-state",
        action="store_true",
        help="Keep source replay auto-warm for formal runs. Default disables it for fast smoke checks.",
    )
    parser.add_argument("--test-top-train-candidates", type=int, default=2)
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    meta_path = _resolve(args.meta_router_audit)
    report = build_meta_router_shadow_wfo_plan(
        meta_router_audit=_load_json_optional(meta_path),
        source_report=args.source_report or None,
        input_meta_router_audit=_display_path(meta_path),
        shadow_wfo_root=str(args.shadow_wfo_root),
        fold_limit=max(0, int(args.fold_limit)),
        fold_offset=max(0, int(args.fold_offset)),
        warm_fold_offset_selection_state=bool(args.warm_fold_offset_selection_state),
        disable_source_replay_auto_warm_selection_state=not bool(
            args.preserve_source_replay_auto_warm_selection_state
        ),
        test_top_train_candidates=max(1, int(args.test_top_train_candidates)),
    )
    if args.write_report:
        report_dir = _resolve(args.report_dir)
        assert report_dir is not None
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_meta_router_shadow_wfo_plan.json"
        md_path = report_dir / "market_state_rotation_v6_meta_router_shadow_wfo_plan.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        report["report_path"] = _display_path(json_path)
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
