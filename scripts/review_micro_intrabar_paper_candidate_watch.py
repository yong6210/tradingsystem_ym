#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text


DEFAULT_CONTRACT_PATH = ROOT_DIR / "reports/operations/micro_intrabar_paper_candidate_contract/latest.json"
DEFAULT_REPORT_GLOB = (
    ROOT_DIR / "reports/operations/micro_intrabar_paper_candidate_watch/micro_intrabar_paper_candidate_watch_*.json"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review accumulated micro intrabar paper-candidate watch reports.")
    parser.add_argument("--contract-path", default=str(DEFAULT_CONTRACT_PATH))
    parser.add_argument("--report-glob", default=str(DEFAULT_REPORT_GLOB))
    parser.add_argument("--report-dir", default="reports/operations/micro_intrabar_paper_candidate_review")
    parser.add_argument("--review-label", default="primary_paper_candidate")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("extra_report_paths", nargs="*", help=argparse.SUPPRESS)
    return parser.parse_args()


def _resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed == parsed else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _report_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def _expand_reports(pattern: str) -> list[Path]:
    resolved = str(_resolve_path(pattern))
    return [Path(path) for path in sorted(glob.glob(resolved))]


def _report_paths(pattern: str, extra_paths: list[str]) -> list[Path]:
    paths = _expand_reports(pattern)
    seen = set(paths)
    for raw in extra_paths:
        path = _resolve_path(raw)
        if path.exists() and path not in seen:
            paths.append(path)
            seen.add(path)
    return paths


def _candidate_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("symbol") or "").upper(),
        str(row.get("entry_ts") or ""),
        str(row.get("direction") or "").lower(),
    )


def _dedupe_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = _candidate_key(row)
        if not all(key):
            continue
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = row
            continue
        existing_seen = _safe_int(existing.get("seen_in_report_count"), 1)
        row = dict(existing)
        row["seen_in_report_count"] = existing_seen + 1
        by_key[key] = row
    return sorted(by_key.values(), key=lambda item: str(item.get("entry_ts") or ""), reverse=True)


def _base_signal_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return _candidate_key(row)


def _dedupe_base_signals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = _base_signal_key(row)
        if not all(key):
            continue
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = row
            continue
        merged = dict(existing)
        merged["seen_in_report_count"] = _safe_int(existing.get("seen_in_report_count"), 1) + 1
        by_key[key] = merged
    return sorted(by_key.values(), key=lambda item: str(item.get("entry_ts") or ""), reverse=True)


def _summarize_candidates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_symbol: dict[str, int] = {}
    by_hour: dict[str, int] = {}
    by_day: dict[str, int] = {}
    by_direction: dict[str, int] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "UNKNOWN")
        direction = str(row.get("direction") or "unknown")
        diagnostics = dict(row.get("diagnostics") or {})
        hour = str(diagnostics.get("setup_hour_utc", "unknown"))
        entry_ts = _parse_ts(row.get("entry_ts"))
        day = entry_ts.date().isoformat() if entry_ts else "unknown"
        by_symbol[symbol] = by_symbol.get(symbol, 0) + 1
        by_hour[hour] = by_hour.get(hour, 0) + 1
        by_day[day] = by_day.get(day, 0) + 1
        by_direction[direction] = by_direction.get(direction, 0) + 1
    return {
        "count": len(rows),
        "by_symbol": dict(sorted(by_symbol.items())),
        "by_direction": dict(sorted(by_direction.items())),
        "by_setup_hour_utc": dict(sorted(by_hour.items())),
        "by_entry_day": dict(sorted(by_day.items())),
    }


def _summarize_base_rejections(rows: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [row for row in rows if bool(row.get("filter_pass"))]
    rejected = [row for row in rows if not bool(row.get("filter_pass"))]
    by_reason: dict[str, int] = {}
    by_primary_reason: dict[str, int] = {}
    for row in rejected:
        reasons = [str(reason) for reason in list(row.get("filter_reasons") or []) if str(reason)]
        if not reasons:
            reasons = ["unknown_rejection_reason"]
        by_primary_reason[reasons[0]] = by_primary_reason.get(reasons[0], 0) + 1
        for reason in reasons:
            by_reason[reason] = by_reason.get(reason, 0) + 1
    return {
        "unique_base_signal_count": len(rows),
        "filter_pass_count": len(passed),
        "rejected_count": len(rejected),
        "by_filter_reason": dict(sorted(by_reason.items())),
        "by_primary_filter_reason": dict(sorted(by_primary_reason.items())),
        "by_symbol": _summarize_candidates(rejected)["by_symbol"],
        "by_direction": _summarize_candidates(rejected)["by_direction"],
        "by_setup_hour_utc": _summarize_candidates(rejected)["by_setup_hour_utc"],
    }


def _observation_days(report_times: list[datetime], candidate_rows: list[dict[str, Any]]) -> float:
    candidate_times = [_parse_ts(row.get("entry_ts")) for row in candidate_rows]
    times = [time for time in candidate_times if time is not None] or report_times
    if len(times) < 2:
        return 0.0
    return round((max(times) - min(times)).total_seconds() / 86400.0, 4)


def _review_state(*, candidate_count: int, observation_days: float, gates: dict[str, Any]) -> tuple[str, list[str]]:
    minimum_samples = _safe_int(gates.get("minimum_closed_paper_trades"), 30)
    minimum_days = _safe_float(gates.get("minimum_observation_days"), 30.0)
    blockers: list[str] = []
    if candidate_count <= 0:
        blockers.append("no_unique_candidate_signals_yet")
    if candidate_count < minimum_samples:
        blockers.append("candidate_signal_count_below_paper_sample_gate")
    if observation_days < minimum_days:
        blockers.append("observation_window_below_gate")
    if blockers:
        return "COLLECTING_SIGNALS", blockers
    return "PAPER_SAMPLE_REVIEW_READY", ["signal_count_and_observation_window_met"]


def _historical_collection_estimate(
    *,
    contract: dict[str, Any],
    current_candidate_count: int,
    gates: dict[str, Any],
) -> dict[str, Any]:
    candidate = dict(contract.get("candidate") or {})
    historical_closed = _safe_int(candidate.get("closed"))
    historical_days = _safe_float(candidate.get("days"))
    minimum_samples = _safe_int(gates.get("minimum_closed_paper_trades"), 30)
    remaining_samples = max(minimum_samples - int(current_candidate_count), 0)
    signals_per_day = historical_closed / historical_days if historical_closed > 0 and historical_days > 0 else 0.0
    estimated_days = remaining_samples / signals_per_day if signals_per_day > 0 else None
    if estimated_days is None:
        feasibility = "UNKNOWN"
    elif estimated_days > 180:
        feasibility = "TOO_SLOW_FOR_LIVE_ONLY_COLLECTION"
    elif estimated_days > 60:
        feasibility = "SLOW_LIVE_COLLECTION"
    else:
        feasibility = "PRACTICAL_LIVE_COLLECTION"
    return {
        "historical_closed": historical_closed,
        "historical_days": round(historical_days, 4),
        "historical_signals_per_day": round(signals_per_day, 6),
        "minimum_candidate_signals": minimum_samples,
        "current_unique_candidate_signals": int(current_candidate_count),
        "remaining_candidate_signals": remaining_samples,
        "estimated_days_to_sample_gate": round(estimated_days, 2) if estimated_days is not None else None,
        "feasibility": feasibility,
        "recommendation": (
            "Add recent replay and shadow-style validation; live-only sample collection is too slow."
            if feasibility == "TOO_SLOW_FOR_LIVE_ONLY_COLLECTION"
            else "Continue live paper collection."
        ),
    }


def build_payload(
    contract_path: Path,
    report_paths: list[Path],
    *,
    review_label: str = "primary_paper_candidate",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    contract = _load_json(contract_path)
    gates = dict(contract.get("promotion_gates") or {})
    load_errors: list[dict[str, str]] = []
    report_times: list[datetime] = []
    candidates_raw: list[dict[str, Any]] = []
    base_signals_raw: list[dict[str, Any]] = []
    report_summaries: list[dict[str, Any]] = []
    for path in report_paths:
        try:
            payload = _load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            load_errors.append({"path": str(path), "error": str(exc)})
            continue
        if str(payload.get("schema_version") or "") != "micro_intrabar_paper_candidate_watch_v1":
            continue
        generated = _parse_ts(payload.get("generated_at"))
        if generated is not None:
            report_times.append(generated)
        latest_candidates = [dict(row) for row in list(payload.get("latest_candidates") or []) if isinstance(row, dict)]
        for row in latest_candidates:
            row.setdefault("seen_in_report_count", 1)
            row["source_report"] = str(path.relative_to(ROOT_DIR) if path.is_relative_to(ROOT_DIR) else path)
        candidates_raw.extend(latest_candidates)
        latest_base_signals = [dict(row) for row in list(payload.get("latest_base_signals") or []) if isinstance(row, dict)]
        for row in latest_base_signals:
            row.setdefault("seen_in_report_count", 1)
            row["source_report"] = str(path.relative_to(ROOT_DIR) if path.is_relative_to(ROOT_DIR) else path)
        base_signals_raw.extend(latest_base_signals)
        summary = dict(payload.get("summary") or {})
        report_summaries.append(
            {
                "path": str(path.relative_to(ROOT_DIR) if path.is_relative_to(ROOT_DIR) else path),
                "generated_at": payload.get("generated_at"),
                "status": payload.get("status"),
                "base_signal_count": _safe_int(dict(summary.get("base_signals") or {}).get("count")),
                "paper_candidate_count": _safe_int(dict(summary.get("paper_candidates") or {}).get("count")),
                "fresh_paper_candidate_count": _safe_int(dict(summary.get("fresh_paper_candidates") or {}).get("count")),
            }
        )

    unique_candidates = _dedupe_candidates(candidates_raw)
    unique_base_signals = _dedupe_base_signals(base_signals_raw)
    observation_days = _observation_days(report_times, unique_candidates)
    state, blockers = _review_state(
        candidate_count=len(unique_candidates),
        observation_days=observation_days,
        gates=gates,
    )
    collection_estimate = _historical_collection_estimate(
        contract=contract,
        current_candidate_count=len(unique_candidates),
        gates=gates,
    )
    if collection_estimate.get("feasibility") == "TOO_SLOW_FOR_LIVE_ONLY_COLLECTION":
        blockers = [*blockers, "historical_signal_rate_makes_live_only_collection_too_slow"]
    return {
        "schema_version": "micro_intrabar_paper_candidate_review_v1",
        "generated_at": generated_at.isoformat(),
        "review_label": review_label,
        "authority": "paper_review_only_no_order_submission",
        "contract_path": str(contract_path.relative_to(ROOT_DIR) if contract_path.is_relative_to(ROOT_DIR) else contract_path),
        "report_count": len(report_paths),
        "loaded_report_count": len(report_summaries),
        "load_errors": load_errors,
        "recommended_state": state,
        "blockers": blockers,
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": False,
        "observation_days": observation_days,
        "minimum_candidate_signals": _safe_int(gates.get("minimum_closed_paper_trades"), 30),
        "minimum_observation_days": _safe_float(gates.get("minimum_observation_days"), 30.0),
        "collection_estimate": collection_estimate,
        "unique_candidate_summary": _summarize_candidates(unique_candidates),
        "unique_candidates": unique_candidates[:100],
        "base_signal_summary": _summarize_candidates(unique_base_signals),
        "base_signal_rejection_summary": _summarize_base_rejections(unique_base_signals),
        "recent_rejected_base_signals": [
            row for row in unique_base_signals if not bool(row.get("filter_pass"))
        ][:100],
        "recent_report_summaries": report_summaries[-20:],
        "contract_snapshot": {
            "policy_name": dict(contract.get("paper_contract") or {}).get("policy_name"),
            "symbols": dict(contract.get("paper_contract") or {}).get("symbols") or [],
            "promotion_gates": gates,
            "risk_notes": contract.get("risk_notes") or [],
        },
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    summary = dict(payload.get("unique_candidate_summary") or {})
    base_summary = dict(payload.get("base_signal_summary") or {})
    rejection_summary = dict(payload.get("base_signal_rejection_summary") or {})
    lines = [
        "# Micro Intrabar Paper Candidate Review",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- review_label: {payload.get('review_label')}",
        f"- authority: {payload.get('authority')}",
        f"- recommended_state: {payload.get('recommended_state')}",
        f"- blockers: {payload.get('blockers')}",
        f"- live_action: {payload.get('live_action')}",
        f"- reports: {payload.get('loaded_report_count')}/{payload.get('report_count')}",
        f"- unique_candidate_signals: {summary.get('count')}",
        f"- unique_base_signals: {base_summary.get('count')}",
        f"- rejected_base_signals: {rejection_summary.get('rejected_count')}",
        f"- rejection_reasons: {rejection_summary.get('by_filter_reason')}",
        f"- observation_days: {payload.get('observation_days')}",
        f"- minimum_candidate_signals: {payload.get('minimum_candidate_signals')}",
        f"- minimum_observation_days: {payload.get('minimum_observation_days')}",
        f"- estimated_days_to_sample_gate: {dict(payload.get('collection_estimate') or {}).get('estimated_days_to_sample_gate')}",
        f"- collection_feasibility: {dict(payload.get('collection_estimate') or {}).get('feasibility')}",
        "",
        "This review does not submit orders or enable live routing.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    generated_at = datetime.now(UTC)
    contract_path = _resolve_path(args.contract_path)
    paths = _report_paths(args.report_glob, list(args.extra_report_paths or []))
    payload = build_payload(contract_path, paths, review_label=str(args.review_label), generated_at=generated_at)
    if args.write_report:
        report_dir = _resolve_path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = _report_stamp(generated_at)
        json_path = report_dir / f"micro_intrabar_paper_candidate_review_{stamp}.json"
        md_path = report_dir / f"micro_intrabar_paper_candidate_review_{stamp}.md"
        latest_json = report_dir / "latest.json"
        latest_md = report_dir / "latest.md"
        payload["report_path"] = str(json_path.relative_to(ROOT_DIR) if json_path.is_relative_to(ROOT_DIR) else json_path)
        payload["latest_report_path"] = str(latest_json.relative_to(ROOT_DIR) if latest_json.is_relative_to(ROOT_DIR) else latest_json)
        atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(md_path, _render_markdown(payload))
        atomic_write_text(latest_json, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(latest_md, _render_markdown(payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
