#!/usr/bin/env python3
"""Build the full v6 shadow readiness evidence bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.session import SessionLocal, init_db
from app.services.live_order_lifecycle import LiveOrderLifecycleReporter
from scripts.run_market_state_rotation_v6_execution_shadow_audit import (
    build_execution_shadow_audit_report,
)
from scripts.run_market_state_rotation_v6_safety_evidence_collect import (
    build_safety_evidence_collection_report,
)
from scripts.run_market_state_rotation_v6_shadow_fill_export import (
    build_shadow_fill_export_report,
)


EXPECTED_STRATEGY_FAMILY = "market_state_rotation_v6"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT_DIR / path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _lifecycle_payload_from_db(
    *,
    symbol: str,
    strategy_family: str,
    days: int,
    limit: int,
    include_paper: bool,
) -> dict[str, Any]:
    init_db()
    with SessionLocal() as db:
        return LiveOrderLifecycleReporter(db).generate(
            days=max(1, int(days)),
            symbol=symbol.upper(),
            live_only=not bool(include_paper),
            limit=max(1, int(limit)),
            strategy_families=[strategy_family],
        )


def build_shadow_readiness_pipeline_report(
    *,
    stress_report: dict[str, Any],
    lifecycle_payload: dict[str, Any],
    manual_safety_evidence: dict[str, Any] | None = None,
    input_stress_report: str | None = None,
    input_lifecycle_report: str | None = None,
    symbol: str = "BTCUSDT",
    strategy_family: str = EXPECTED_STRATEGY_FAMILY,
    min_shadow_fill_samples: int = 100,
    max_report_age_hours: float = 24.0,
    max_evidence_age_days: int = 7,
) -> dict[str, Any]:
    shadow_export = build_shadow_fill_export_report(
        lifecycle_payload,
        input_lifecycle_report=input_lifecycle_report,
        expected_symbol=symbol,
        expected_strategy_family=strategy_family,
    )
    safety_collection = build_safety_evidence_collection_report(
        manual_evidence=manual_safety_evidence,
        max_report_age_hours=float(max_report_age_hours),
        max_evidence_age_days=max(1, int(max_evidence_age_days)),
    )
    execution_audit = build_execution_shadow_audit_report(
        stress_report,
        list(shadow_export.get("rows") or []),
        safety_controls=dict(safety_collection.get("normalized_safety_controls") or {}),
        input_stress_report=input_stress_report,
        input_shadow_fills="pipeline:shadow_fill_export.rows",
        input_safety_controls="pipeline:safety_evidence_collect.normalized_safety_controls",
        expected_symbol=symbol,
        expected_strategy_family=strategy_family,
        min_shadow_fill_samples=max(1, int(min_shadow_fill_samples)),
    )
    return {
        "overall_status": execution_audit.get("overall_status"),
        "summary": dict(execution_audit.get("summary") or {}),
        "input_stress_report": input_stress_report,
        "input_lifecycle_report": input_lifecycle_report,
        "symbol": symbol.upper(),
        "strategy_family": strategy_family,
        "shadow_fill_export": shadow_export,
        "safety_evidence_collection": safety_collection,
        "execution_shadow_audit": execution_audit,
        "required_next_actions": list(execution_audit.get("required_next_actions") or []),
    }


def _markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary") or {})
    shadow = dict(report.get("shadow_fill_export") or {})
    safety = dict(report.get("safety_evidence_collection") or {})
    lines = [
        "# Market State Rotation V6 Shadow Readiness Pipeline",
        "",
        f"- Status: `{report.get('overall_status')}`",
        f"- Ready for paper: `{summary.get('ready_for_paper')}`",
        f"- Ready for tiny live canary: `{summary.get('ready_for_tiny_live_canary')}`",
        f"- Live order submission allowed: `{summary.get('live_order_submission_allowed')}`",
        f"- Shadow fill rows: `{shadow.get('row_count')}`",
        f"- Safety verified: `{safety.get('verified_count')}/{safety.get('required_count')}`",
        f"- Failed gates: `{', '.join(summary.get('failed_gates') or [])}`",
        f"- Pending gates: `{', '.join(summary.get('pending_gates') or [])}`",
        "",
        "## Required Next Actions",
        "",
    ]
    for action in list(report.get("required_next_actions") or []):
        lines.append(f"- {action}")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build market-state rotation v6 shadow fill, safety evidence, and execution audit bundle."
    )
    parser.add_argument("--stress-report", required=True)
    parser.add_argument("--lifecycle-report", default="")
    parser.add_argument("--manual-safety-evidence", default="")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--strategy-family", default=EXPECTED_STRATEGY_FAMILY)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--include-paper", action="store_true")
    parser.add_argument("--min-shadow-fill-samples", type=int, default=100)
    parser.add_argument("--max-report-age-hours", type=float, default=24.0)
    parser.add_argument("--max-evidence-age-days", type=int, default=7)
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_shadow_readiness_pipeline")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stress_path = _resolve(args.stress_report)
    stress_report = _load_json(stress_path)

    lifecycle_path = _resolve(args.lifecycle_report) if args.lifecycle_report else None
    if lifecycle_path is not None:
        lifecycle_payload = _load_json(lifecycle_path)
        input_lifecycle_report = _display_path(lifecycle_path)
    else:
        lifecycle_payload = _lifecycle_payload_from_db(
            symbol=str(args.symbol or "BTCUSDT"),
            strategy_family=str(args.strategy_family or EXPECTED_STRATEGY_FAMILY),
            days=max(1, int(args.days)),
            limit=max(1, int(args.limit)),
            include_paper=bool(args.include_paper),
        )
        input_lifecycle_report = "generated_from_db"

    manual_path = _resolve(args.manual_safety_evidence) if args.manual_safety_evidence else None
    manual_evidence = _load_json(manual_path) if manual_path is not None else None
    report = build_shadow_readiness_pipeline_report(
        stress_report=stress_report,
        lifecycle_payload=lifecycle_payload,
        manual_safety_evidence=manual_evidence,
        input_stress_report=_display_path(stress_path),
        input_lifecycle_report=input_lifecycle_report,
        symbol=str(args.symbol or "BTCUSDT").upper(),
        strategy_family=str(args.strategy_family or EXPECTED_STRATEGY_FAMILY),
        min_shadow_fill_samples=max(1, int(args.min_shadow_fill_samples)),
        max_report_age_hours=float(args.max_report_age_hours),
        max_evidence_age_days=max(1, int(args.max_evidence_age_days)),
    )
    if manual_path is not None:
        report["input_manual_safety_evidence"] = _display_path(manual_path)

    if args.write_report:
        report_dir = Path(args.report_dir)
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        _write_json(report_dir / "market_state_rotation_v6_shadow_readiness_pipeline.json", report)
        _write_json(
            report_dir / "market_state_rotation_v6_shadow_fill_export.json",
            dict(report.get("shadow_fill_export") or {}),
        )
        _write_jsonl(
            report_dir / "market_state_rotation_v6_shadow_fills.jsonl",
            list(dict(report.get("shadow_fill_export") or {}).get("rows") or []),
        )
        _write_json(
            report_dir / "market_state_rotation_v6_safety_evidence_collect.json",
            dict(report.get("safety_evidence_collection") or {}),
        )
        _write_json(
            report_dir / "market_state_rotation_v6_execution_shadow_audit.json",
            dict(report.get("execution_shadow_audit") or {}),
        )
        (report_dir / "market_state_rotation_v6_shadow_readiness_pipeline.md").write_text(
            _markdown(report),
            encoding="utf-8",
        )
        print(f"wrote {_display_path(report_dir / 'market_state_rotation_v6_shadow_readiness_pipeline.json')}")
        print(f"wrote {_display_path(report_dir / 'market_state_rotation_v6_shadow_readiness_pipeline.md')}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
