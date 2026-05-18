#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text
from scripts.run_micro_main_exit_policy_search import summarize_rows
from scripts.run_micro_main_intrabar_subset_report import _cost_stress


DEFAULT_CONTRACT_PATH = ROOT_DIR / "reports/operations/micro_intrabar_paper_candidate_contract/latest.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review recent replay windows for the paper-only micro intrabar candidate.")
    parser.add_argument("--contract-path", default=str(DEFAULT_CONTRACT_PATH))
    parser.add_argument("--intrabar-report-path", default="")
    parser.add_argument("--report-dir", default="reports/operations/micro_intrabar_candidate_replay_review")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _report_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def _infer_intrabar_report_path(contract: dict[str, Any]) -> Path:
    candidate = dict(contract.get("candidate") or {})
    source_path = str(candidate.get("source_path") or "").strip()
    if not source_path:
        raise ValueError("contract candidate has no source_path")
    subset_path = _resolve_path(source_path)
    subset_payload = _load_json(subset_path)
    source_report = str(subset_payload.get("source_report") or "").strip()
    if not source_report:
        raise ValueError(f"subset report has no source_report: {subset_path}")
    return _resolve_path(source_report)


def _load_trade_rows(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = _load_json(path)
    rows: list[dict[str, Any]] = []
    for item in list(payload.get("results") or []):
        if not isinstance(item, dict):
            continue
        for row in list(item.get("trades") or []):
            if isinstance(row, dict):
                rows.append(dict(row))
    if not rows:
        raise ValueError(f"intrabar report has no included trade rows: {path}")
    return payload, rows


def _passes_contract(row: dict[str, Any], paper_contract: dict[str, Any]) -> bool:
    symbols = {str(symbol).strip().upper() for symbol in list(paper_contract.get("symbols") or []) if str(symbol).strip()}
    if symbols and str(row.get("symbol") or "").upper() not in symbols:
        return False
    exit_policy_name = str(paper_contract.get("exit_policy_name") or "").strip()
    if exit_policy_name and str(row.get("policy") or "").strip() != exit_policy_name:
        return False
    filter_contract = dict(paper_contract.get("filter_contract") or {})
    diagnostics = dict(row.get("diagnostics") or {})
    expected_direction = str(filter_contract.get("direction") or "").strip().lower()
    if expected_direction and expected_direction != "both" and str(row.get("direction") or "").strip().lower() != expected_direction:
        return False
    allowed_hours = {_safe_int(hour, -1) for hour in list(filter_contract.get("setup_hour_utc") or [])}
    if allowed_hours and _safe_int(diagnostics.get("setup_hour_utc"), -1) not in allowed_hours:
        return False
    min_volume_factor = filter_contract.get("min_volume_factor")
    if min_volume_factor is not None and _safe_float(diagnostics.get("volume_factor")) < _safe_float(min_volume_factor):
        return False
    min_reclaim_body_atr = filter_contract.get("min_reclaim_body_atr")
    if min_reclaim_body_atr is not None and _safe_float(diagnostics.get("reclaim_body_atr")) < _safe_float(min_reclaim_body_atr):
        return False
    min_risk_atr = filter_contract.get("min_risk_atr")
    if min_risk_atr is not None and _safe_float(diagnostics.get("risk_atr")) < _safe_float(min_risk_atr):
        return False
    max_risk_atr = filter_contract.get("max_risk_atr")
    if max_risk_atr is not None and _safe_float(diagnostics.get("risk_atr")) > _safe_float(max_risk_atr):
        return False
    max_retest_wait_minutes = filter_contract.get("max_retest_wait_minutes")
    if max_retest_wait_minutes is not None and _safe_float(diagnostics.get("retest_wait_minutes")) > _safe_float(max_retest_wait_minutes):
        return False
    max_entry_distance_atr = filter_contract.get("max_entry_distance_atr")
    if max_entry_distance_atr is not None and _safe_float(diagnostics.get("entry_distance_atr")) > _safe_float(max_entry_distance_atr):
        return False
    return True


def _window_rows(rows: list[dict[str, Any]], *, end_ts: datetime, days: int | None) -> list[dict[str, Any]]:
    if days is None:
        return rows
    start_ts = end_ts - timedelta(days=max(int(days), 1))
    return [row for row in rows if (entry_ts := _parse_ts(row.get("entry_ts"))) is not None and entry_ts >= start_ts]


def _window_summary(rows: list[dict[str, Any]], *, end_ts: datetime, days: int | None) -> dict[str, Any]:
    selected = _window_rows(rows, end_ts=end_ts, days=days)
    summary = summarize_rows(selected)
    return {
        "label": "all" if days is None else f"last_{days}d",
        "days": days,
        "summary": summary,
        "cost_stress": _cost_stress(selected),
    }


def _decision(windows: list[dict[str, Any]]) -> tuple[str, list[str]]:
    by_label = {str(item.get("label")): item for item in windows}
    all_summary = dict(dict(by_label.get("all") or {}).get("summary") or {})
    last365 = dict(dict(by_label.get("last_365d") or {}).get("summary") or {})
    last180 = dict(dict(by_label.get("last_180d") or {}).get("summary") or {})
    blockers: list[str] = []
    warnings: list[str] = []
    if _safe_float(all_summary.get("total_r")) <= 0.0:
        blockers.append("all_window_non_positive")
    if _safe_int(last365.get("closed")) < 10:
        warnings.append("last365_sample_thin")
    elif _safe_float(last365.get("total_r")) <= 0.0 or _safe_float(last365.get("ev_r")) <= 0.0:
        blockers.append("last365_non_positive")
    if _safe_int(last180.get("closed")) < 5:
        warnings.append("last180_sample_thin")
    elif _safe_float(last180.get("total_r")) <= 0.0:
        warnings.append("last180_non_positive")
    if blockers:
        return "REPLAY_NOT_READY", blockers + warnings
    return "REPLAY_SUPPORTS_PAPER_ONLY_WATCH", warnings or ["recent_replay_has_no_hard_blocker"]


def build_payload(
    contract_path: Path,
    *,
    intrabar_report_path: Path | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    contract = _load_json(contract_path)
    paper_contract = dict(contract.get("paper_contract") or {})
    if intrabar_report_path is None:
        intrabar_report_path = _infer_intrabar_report_path(contract)
    source_payload, raw_rows = _load_trade_rows(intrabar_report_path)
    matched_rows = [row for row in raw_rows if _passes_contract(row, paper_contract)]
    entry_times = [_parse_ts(row.get("entry_ts")) for row in matched_rows]
    clean_entry_times = [ts for ts in entry_times if ts is not None]
    end_ts = max(clean_entry_times) if clean_entry_times else generated_at
    windows = [
        _window_summary(matched_rows, end_ts=end_ts, days=90),
        _window_summary(matched_rows, end_ts=end_ts, days=180),
        _window_summary(matched_rows, end_ts=end_ts, days=365),
        _window_summary(matched_rows, end_ts=end_ts, days=730),
        _window_summary(matched_rows, end_ts=end_ts, days=None),
    ]
    state, reasons = _decision(windows)
    return {
        "schema_version": "micro_intrabar_candidate_replay_review_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "replay_review_only_no_order_submission",
        "contract_path": str(contract_path.relative_to(ROOT_DIR) if contract_path.is_relative_to(ROOT_DIR) else contract_path),
        "intrabar_report_path": str(intrabar_report_path.relative_to(ROOT_DIR) if intrabar_report_path.is_relative_to(ROOT_DIR) else intrabar_report_path),
        "source_report_generated_at": source_payload.get("generated_at"),
        "recommended_state": state,
        "reasons": reasons,
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": False,
        "raw_trade_count": len(raw_rows),
        "matched_trade_count": len(matched_rows),
        "replay_end_ts": end_ts.isoformat(),
        "windows": windows,
        "contract_snapshot": {
            "policy_name": paper_contract.get("policy_name"),
            "exit_policy_name": paper_contract.get("exit_policy_name"),
            "symbols": paper_contract.get("symbols") or [],
            "filter_contract": paper_contract.get("filter_contract") or {},
        },
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Micro Intrabar Candidate Replay Review",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- authority: {payload.get('authority')}",
        f"- recommended_state: {payload.get('recommended_state')}",
        f"- reasons: {payload.get('reasons')}",
        f"- live_action: {payload.get('live_action')}",
        f"- matched_trade_count: {payload.get('matched_trade_count')}",
        f"- replay_end_ts: {payload.get('replay_end_ts')}",
        "",
        "## Windows",
    ]
    for item in list(payload.get("windows") or []):
        summary = dict(item.get("summary") or {})
        extra = dict(dict(item.get("cost_stress") or {}).get("extra_0_05r_per_trade") or {})
        lines.append(
            "- "
            f"{item.get('label')}: trades={summary.get('closed')} total_r={summary.get('total_r')} "
            f"ev={summary.get('ev_r')} max_dd={summary.get('max_dd_r')} "
            f"extra_0_05r_total_r={extra.get('total_r')}"
        )
    lines.append("")
    lines.append("This replay review does not submit orders or enable live routing.")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    generated_at = datetime.now(UTC)
    contract_path = _resolve_path(args.contract_path)
    intrabar_report_path = _resolve_path(args.intrabar_report_path) if str(args.intrabar_report_path or "").strip() else None
    payload = build_payload(contract_path, intrabar_report_path=intrabar_report_path, generated_at=generated_at)
    if args.write_report:
        report_dir = _resolve_path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = _report_stamp(generated_at)
        json_path = report_dir / f"micro_intrabar_candidate_replay_review_{stamp}.json"
        md_path = report_dir / f"micro_intrabar_candidate_replay_review_{stamp}.md"
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
