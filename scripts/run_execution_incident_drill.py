#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.session import SessionLocal, init_db
from app.services.strategy_engine import StrategyEngine


DEFAULT_SCENARIOS = ["dashboard", "reconcile", "kill_switch", "close_only", "rollout_block"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run auto-trading incident drill scenarios")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--family", default="trend_continuation")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=DEFAULT_SCENARIOS,
        help="Scenario to run. Repeat to run multiple. Defaults to all standard scenarios.",
    )
    parser.add_argument("--intent-limit", type=int, default=10)
    parser.add_argument("--reconcile-limit", type=int, default=10)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--operator", default="incident_drill")
    parser.add_argument("--report-dir", default="reports/execution/incident_drills")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-restore", action="store_true")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# Execution Incident Drill")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- symbol: {payload['symbol']}")
    lines.append(f"- family: {payload['family']}")
    lines.append(f"- scenarios: {', '.join(payload['scenarios'])}")
    lines.append(f"- restored: {payload['restored']}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- initial_new_entries_allowed: {payload['initial_dashboard'].get('new_entries_allowed')}")
    lines.append(f"- initial_blocking_reason: {payload['initial_dashboard'].get('blocking_reason_code') or 'none'}")
    lines.append("")
    for scenario in payload["results"]:
        lines.append(f"## {scenario['scenario']}")
        lines.append("")
        lines.append(f"- ok: {scenario.get('ok', True)}")
        if scenario.get("note"):
            lines.append(f"- note: {scenario['note']}")
        if "before" in scenario:
            before = scenario["before"]
            lines.append(f"- before_new_entries_allowed: {before.get('new_entries_allowed')}")
            lines.append(f"- before_blocking_reason: {before.get('blocking_reason_code') or 'none'}")
        if "after" in scenario:
            after = scenario["after"]
            lines.append(f"- after_new_entries_allowed: {after.get('new_entries_allowed')}")
            lines.append(f"- after_blocking_reason: {after.get('blocking_reason_code') or 'none'}")
        if "reconcile" in scenario:
            reconcile = scenario["reconcile"]
            lines.append(f"- reconcile_highest_severity: {reconcile.get('highest_severity')}")
            lines.append(f"- reconcile_lock_required: {reconcile.get('lock_required')}")
            lines.append(f"- reconcile_mismatches: {len(reconcile.get('mismatches', []))}")
        if "policy_before" in scenario:
            lines.append(f"- policy_before: {json.dumps(scenario['policy_before'], ensure_ascii=False, default=_json_default)}")
        if "policy_after" in scenario:
            lines.append(f"- policy_after: {json.dumps(scenario['policy_after'], ensure_ascii=False, default=_json_default)}")
        if "restore" in scenario:
            restore = scenario["restore"]
            lines.append(f"- restore_new_entries_allowed: {restore.get('new_entries_allowed')}")
            lines.append(f"- restore_blocking_reason: {restore.get('blocking_reason_code') or 'none'}")
        lines.append("")
    lines.append("## Raw Payload")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    lines.append("```")
    path.write_text("\n".join(lines), encoding="utf-8")


def _dashboard(engine: StrategyEngine, *, symbol: str, universe: str, intent_limit: int, reconcile_limit: int, days: int) -> dict[str, Any]:
    return engine.execution_operator_dashboard(
        symbol=symbol,
        universe=universe,
        intent_limit=max(1, intent_limit),
        reconcile_limit=max(1, reconcile_limit),
        days=max(1, days),
    )


def main() -> int:
    args = parse_args()
    scenarios = args.scenario or list(DEFAULT_SCENARIOS)
    init_db()
    report_path: Path | None = None

    with SessionLocal() as db:
        engine = StrategyEngine(db)
        initial_dashboard = _dashboard(
            engine,
            symbol=args.symbol,
            universe=args.universe,
            intent_limit=args.intent_limit,
            reconcile_limit=args.reconcile_limit,
            days=args.days,
        )
        initial_safety = engine.safety_state(symbol=args.symbol, family=args.family)

        results: list[dict[str, Any]] = []

        for scenario in scenarios:
            if scenario == "dashboard":
                results.append({
                    "scenario": scenario,
                    "ok": True,
                    "note": "Captured operator dashboard snapshot.",
                    "after": initial_dashboard,
                })
                continue

            if scenario == "reconcile":
                reconcile = engine.reconcile_execution(symbol=args.symbol, auto_resolve=False, apply_lock=False)
                results.append({
                    "scenario": scenario,
                    "ok": True,
                    "note": "Ran read-only reconciliation.",
                    "reconcile": reconcile,
                })
                continue

            if scenario == "kill_switch":
                before = engine.safety_state(symbol=args.symbol, family=args.family)
                after = engine.set_kill_switch(
                    active=True,
                    reason_message="Incident drill: manual kill switch",
                    updated_by=args.operator,
                )
                item = {
                    "scenario": scenario,
                    "ok": True,
                    "before": before,
                    "after": after,
                }
                if not args.no_restore:
                    restore = engine.set_kill_switch(
                        active=False,
                        reason_message="Incident drill restore: manual kill switch",
                        updated_by=args.operator,
                    )
                    item["restore"] = restore
                results.append(item)
                continue

            if scenario == "close_only":
                before = engine.safety_state(symbol=args.symbol, family=args.family)
                after = engine.set_close_only(
                    active=True,
                    reason_message="Incident drill: close-only",
                    updated_by=args.operator,
                )
                item = {
                    "scenario": scenario,
                    "ok": True,
                    "before": before,
                    "after": after,
                }
                if not args.no_restore:
                    restore = engine.set_close_only(
                        active=False,
                        reason_message="Incident drill restore: close-only",
                        updated_by=args.operator,
                    )
                    item["restore"] = restore
                results.append(item)
                continue

            if scenario == "rollout_block":
                before_policy = engine.rollout_policy_service.get(args.family).to_dict()
                before = engine.safety_state(symbol=args.symbol, family=args.family)
                engine.upsert_rollout_policy(
                    family=args.family,
                    live_enabled=False,
                    max_execution_mode="SHADOW",
                    max_risk_r=0.0,
                    allowed_sessions=[],
                    min_quality_score=max(float(before_policy.get("min_quality_score") or 0.0), 1.0),
                    updated_by=args.operator,
                    notes="Incident drill: force rollout block",
                )
                after = engine.safety_state(symbol=args.symbol, family=args.family)
                item = {
                    "scenario": scenario,
                    "ok": True,
                    "before": before,
                    "after": after,
                    "policy_before": before_policy,
                    "policy_after": engine.rollout_policy_service.get(args.family).to_dict(),
                }
                if not args.no_restore:
                    engine.upsert_rollout_policy(
                        family=args.family,
                        live_enabled=bool(before_policy.get("live_enabled")),
                        max_execution_mode=str(before_policy.get("max_execution_mode") or "SHADOW"),
                        max_risk_r=float(before_policy.get("max_risk_r") or 0.0),
                        allowed_sessions=list(before_policy.get("allowed_sessions") or []),
                        min_quality_score=float(before_policy.get("min_quality_score") or 0.0),
                        updated_by=args.operator,
                        notes="Incident drill restore: rollout policy",
                    )
                    item["restore"] = engine.safety_state(symbol=args.symbol, family=args.family)
                results.append(item)
                continue

        generated_at = _now()
        payload = {
            "generated_at": generated_at.isoformat(),
            "symbol": args.symbol,
            "family": args.family,
            "scenarios": scenarios,
            "restored": not args.no_restore,
            "initial_dashboard": initial_dashboard,
            "initial_safety": initial_safety,
            "results": results,
        }

        if not args.no_write_report:
            ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
            report_path = ROOT_DIR / args.report_dir / f"execution_incident_drill_{args.symbol}_{ts}.md"
            _write_report(report_path, payload)
            payload["report_path"] = str(report_path.relative_to(ROOT_DIR))

        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
