#!/usr/bin/env python3
"""Gate near-miss smoke candidates across multiple validation windows."""

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


DEFAULT_SMOKE_REPORTS = (
    "reports/validation/diagnostics/market_state_rotation_v6_imp457_near_miss_smoke_evidence_probe_label/"
    "market_state_rotation_v6_near_miss_smoke.json,"
    "reports/validation/diagnostics/market_state_rotation_v6_imp458_near_miss_smoke_current_365d/"
    "market_state_rotation_v6_near_miss_smoke.json"
)


def _resolve(path: str | Path) -> Path:
    raw = Path(path)
    return raw if raw.is_absolute() else ROOT_DIR / raw


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _candidate_rows(smoke_report: dict[str, Any], *, input_report: str) -> list[dict[str, Any]]:
    window = dict(smoke_report.get("window") or {})
    rows: list[dict[str, Any]] = []
    for item in list(smoke_report.get("candidates") or []):
        if item.get("name") == "base":
            continue
        delta = dict(item.get("delta_vs_base") or {})
        rows.append(
            {
                "name": item.get("name"),
                "input_report": input_report,
                "window_days": _int(window.get("days")),
                "return_pct": _float(item.get("total_return_pct")),
                "max_drawdown_pct": _float(item.get("max_drawdown_pct")),
                "add_events": _int(item.get("add_events")),
                "primary_use": item.get("primary_use"),
                "smoke_decision": item.get("smoke_decision"),
                "delta_return_pct": _float(delta.get("return_pct")),
                "delta_max_drawdown_pct": _float(delta.get("max_drawdown_pct")),
                "delta_add_events": _int(delta.get("add_events")),
            }
        )
    return rows


def build_near_miss_promotion_gate_report(
    smoke_reports: list[tuple[str, dict[str, Any]]],
    *,
    generated_at: datetime | None = None,
    max_return_degradation_pct: float = 5.0,
    max_drawdown_worsening_pct: float = 3.0,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    by_candidate: dict[str, list[dict[str, Any]]] = {}
    for input_report, report in smoke_reports:
        for row in _candidate_rows(report, input_report=input_report):
            by_candidate.setdefault(str(row.get("name")), []).append(row)
    candidate_reports: list[dict[str, Any]] = []
    for name, rows in sorted(by_candidate.items()):
        failed_windows: list[dict[str, Any]] = []
        passed_windows: list[dict[str, Any]] = []
        for row in rows:
            passes = (
                row["delta_add_events"] > 0
                and row["delta_return_pct"] >= -abs(float(max_return_degradation_pct))
                and row["delta_max_drawdown_pct"] <= float(max_drawdown_worsening_pct)
                and row["smoke_decision"] == "promote_to_full_walk_forward_evidence_probe_candidate"
            )
            (passed_windows if passes else failed_windows).append(row)
        candidate_reports.append(
            {
                "name": name,
                "status": "promote_to_full_walk_forward" if rows and not failed_windows else "blocked",
                "window_count": len(rows),
                "passed_window_count": len(passed_windows),
                "failed_window_count": len(failed_windows),
                "passed_windows": passed_windows,
                "failed_windows": failed_windows,
            }
        )
    promoted = [item for item in candidate_reports if item["status"] == "promote_to_full_walk_forward"]
    return {
        "generated_at": generated_at.isoformat(),
        "overall_status": "candidate_promoted" if promoted else "no_candidate_promoted",
        "no_live_order_sent": True,
        "gates": {
            "max_return_degradation_pct": float(max_return_degradation_pct),
            "max_drawdown_worsening_pct": float(max_drawdown_worsening_pct),
            "requires_positive_add_event_delta": True,
            "requires_every_input_window_to_pass": True,
        },
        "input_report_count": len(smoke_reports),
        "candidate_count": len(candidate_reports),
        "promoted_candidate_count": len(promoted),
        "candidates": candidate_reports,
        "non_negotiables": [
            "do_not_promote_single_window_near_miss_smoke",
            "do_not_use_rejected_evidence_probe_candidates_for_live_or_paper_bridge",
            "full_walk_forward_is_required_after_this_gate",
        ],
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Market State Rotation V6 Near-Miss Promotion Gate",
        "",
        f"- status: `{report.get('overall_status')}`",
        f"- promoted: `{report.get('promoted_candidate_count')}`",
        f"- candidates: `{report.get('candidate_count')}`",
        "",
    ]
    for item in list(report.get("candidates") or []):
        lines.append(
            f"- `{item.get('name')}` status `{item.get('status')}` "
            f"passed `{item.get('passed_window_count')}/{item.get('window_count')}`"
        )
    lines.append("")
    return "\n".join(lines)


def _split_paths(raw: str) -> list[Path]:
    paths: list[Path] = []
    for item in str(raw or "").split(","):
        text = item.strip()
        if text:
            paths.append(_resolve(text))
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gate near-miss smoke candidates across windows.")
    parser.add_argument("--smoke-reports", default=DEFAULT_SMOKE_REPORTS)
    parser.add_argument("--max-return-degradation-pct", type=float, default=5.0)
    parser.add_argument("--max-drawdown-worsening-pct", type=float, default=3.0)
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_near_miss_promotion_gate")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = _split_paths(args.smoke_reports)
    reports = [(_display_path(path), _load_json(path)) for path in paths]
    report = build_near_miss_promotion_gate_report(
        reports,
        max_return_degradation_pct=float(args.max_return_degradation_pct),
        max_drawdown_worsening_pct=float(args.max_drawdown_worsening_pct),
    )
    if args.write_report:
        report_dir = _resolve(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_near_miss_promotion_gate.json"
        md_path = report_dir / "market_state_rotation_v6_near_miss_promotion_gate.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
        md_path.write_text(_markdown(report), encoding="utf-8")
        report["report_path"] = _display_path(json_path)
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
