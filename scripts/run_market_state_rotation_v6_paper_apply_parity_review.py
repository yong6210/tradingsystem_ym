#!/usr/bin/env python3
"""Review whether a PAPER apply credited the v6 execution parity journal.

This script is read-only. It compares a pre-apply evidence report against a
post-apply evidence report and checks whether the execution parity journal row
count moved as the pre-apply forecast said it should.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

DEFAULT_REPORT_DIR = "reports/validation/diagnostics/market_state_rotation_v6_paper_apply_parity_review"
REPORT_NAME = "market_state_rotation_v6_paper_apply_parity_review.json"


def _resolve(path: str | Path | None) -> Path | None:
    if path is None or str(path).strip() == "":
        return None
    raw = Path(path)
    return raw if raw.is_absolute() else ROOT_DIR / raw


def _display_path(path: str | Path | None) -> str | None:
    resolved = _resolve(path)
    if resolved is None:
        return None
    try:
        return str(resolved.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(resolved)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _load_jsonl(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _int_or_none(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _int_value(value: Any, default: int = 0) -> int:
    parsed = _int_or_none(value)
    return int(default) if parsed is None else parsed


def _journal_jsonl_path(payload: dict[str, Any]) -> Path | None:
    paths = dict(payload.get("report_paths") or {})
    path = paths.get("execution_parity_journal_jsonl")
    return _resolve(path) if path else None


def _journal_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _load_jsonl(_journal_jsonl_path(payload))


def _row_signature(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _new_journal_rows(before_report: dict[str, Any], after_report: dict[str, Any]) -> list[dict[str, Any]]:
    before_rows = _journal_rows(before_report)
    after_rows = _journal_rows(after_report)
    before_counts = Counter(_row_signature(row) for row in before_rows)
    new_rows: list[dict[str, Any]] = []
    for row in after_rows:
        signature = _row_signature(row)
        if before_counts[signature] > 0:
            before_counts[signature] -= 1
            continue
        new_rows.append(row)
    return new_rows


def _normalized_side(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text == "buy":
        return "long"
    if text == "sell":
        return "short"
    return text


def _expected_journal_row_match(
    before_report: dict[str, Any],
    new_rows: list[dict[str, Any]],
    *,
    journal_rows_available: bool,
) -> dict[str, Any]:
    parity_plan = dict(before_report.get("execution_parity_collection_plan") or {})
    preflight = dict(parity_plan.get("execution_parity_preflight") or {})
    expected_action = str(preflight.get("expected_journal_action") or parity_plan.get("bridge_action") or "").lower()
    expected_side = _normalized_side(preflight.get("expected_journal_side"))
    expected_source_ts = str(preflight.get("source_event_ts") or "").strip()
    matches: list[dict[str, Any]] = []
    for row in new_rows:
        actual_action = str(row.get("actual_action") or "").strip().lower()
        row_expected_action = str(row.get("expected_action") or "").strip().lower()
        action_match = not expected_action or expected_action in {actual_action, row_expected_action}
        actual_side = _normalized_side(row.get("actual_side"))
        row_expected_side = _normalized_side(row.get("expected_side"))
        side_match = not expected_side or expected_side in {actual_side, row_expected_side}
        source_ts = str(row.get("source_bar_ts") or "").strip()
        source_ts_match = not expected_source_ts or source_ts == expected_source_ts
        matches.append(
            {
                "decision_id": row.get("decision_id"),
                "timestamp": row.get("timestamp"),
                "actual_action": row.get("actual_action"),
                "expected_action": row.get("expected_action"),
                "actual_side": row.get("actual_side"),
                "expected_side": row.get("expected_side"),
                "source_bar_ts": row.get("source_bar_ts"),
                "action_match": action_match,
                "side_match": side_match,
                "source_ts_match": source_ts_match,
                "all_expected_fields_match": action_match and side_match and source_ts_match,
            }
        )
    any_match = any(item["all_expected_fields_match"] is True for item in matches)
    return {
        "expected_action": expected_action or None,
        "expected_side": expected_side or None,
        "expected_source_ts": expected_source_ts or None,
        "new_journal_row_count": len(new_rows),
        "matching_new_row_found": any_match,
        "new_rows_checked": matches[:5],
        "journal_row_identity_check_available": bool(journal_rows_available and (expected_action or expected_side or expected_source_ts)),
    }


def _snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    progress = dict(payload.get("collection_progress") or {})
    parity_plan = dict(payload.get("execution_parity_collection_plan") or {})
    journal = dict(payload.get("execution_parity_journal") or {})
    conversion = dict(journal.get("conversion") or {})
    journal_plan = dict(journal.get("collection_plan") or {})
    contract_summary = dict(journal.get("contract_summary") or {})
    apply_gate = dict(payload.get("paper_bridge_apply_gate") or {})
    journal_rows = (
        _int_or_none(progress.get("execution_parity_journal_rows"))
        or _int_or_none(conversion.get("journal_row_count"))
        or _int_or_none(journal_plan.get("sample_count"))
        or _int_or_none(contract_summary.get("sample_count"))
        or 0
    )
    missing_samples = (
        _int_or_none(progress.get("execution_parity_missing_samples"))
        or _int_or_none(parity_plan.get("missing_samples"))
        or _int_or_none(journal_plan.get("missing_samples"))
        or 0
    )
    return {
        "generated_at": payload.get("generated_at"),
        "no_live_order_sent": payload.get("no_live_order_sent") is True,
        "overall_status": payload.get("overall_status"),
        "launch_status": dict(payload.get("launch_readiness") or {}).get("status"),
        "paper_apply_status": apply_gate.get("status"),
        "paper_apply_requested": apply_gate.get("apply_requested") is True,
        "bridge_action": apply_gate.get("bridge_action") or parity_plan.get("bridge_action"),
        "fresh_signal": apply_gate.get("fresh_signal") is True,
        "can_request_paper_apply_now": apply_gate.get("can_request_paper_apply_now") is True,
        "execution_parity_journal_rows": int(journal_rows),
        "execution_parity_missing_samples": int(missing_samples),
        "paper_fill_rows": _int_value(progress.get("paper_fill_rows")),
        "execution_parity_passed": progress.get("execution_parity_passed") is True,
        "will_credit_current_apply": parity_plan.get("will_credit_current_apply_after_operator_review") is True,
        "projected_journal_rows_after_apply": _int_or_none(
            parity_plan.get("projected_journal_rows_after_current_creditable_apply")
        ),
        "events_needed_before_apply": _int_or_none(parity_plan.get("estimated_future_paper_apply_events_needed")),
        "events_needed_after_apply_forecast": _int_or_none(
            parity_plan.get("estimated_events_needed_after_current_creditable_apply")
        ),
        "creditable_actions": list(parity_plan.get("currently_creditable_actions") or []),
        "accepted_actions": list(parity_plan.get("accepted_actions") or []),
        "parity_plan_status": parity_plan.get("status"),
        "execution_parity_journal_jsonl": _display_path(_journal_jsonl_path(payload)),
    }


def build_paper_apply_parity_review(
    *,
    before_report: dict[str, Any],
    after_report: dict[str, Any],
    input_before_report: str | None = None,
    input_after_report: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    before = _snapshot(before_report)
    after = _snapshot(after_report)
    new_rows = _new_journal_rows(before_report, after_report)
    identity_check = _expected_journal_row_match(
        before_report,
        new_rows,
        journal_rows_available=_journal_jsonl_path(after_report) is not None,
    )
    expected_credit = 1 if before["will_credit_current_apply"] else 0
    expected_after_rows = before["projected_journal_rows_after_apply"]
    if expected_after_rows is None:
        expected_after_rows = before["execution_parity_journal_rows"] + expected_credit
    actual_row_delta = after["execution_parity_journal_rows"] - before["execution_parity_journal_rows"]
    actual_missing_delta = after["execution_parity_missing_samples"] - before["execution_parity_missing_samples"]
    blockers: list[str] = []
    if before["no_live_order_sent"] is not True or after["no_live_order_sent"] is not True:
        blockers.append("live_order_flag_detected_in_evidence_report")
    if expected_credit > 0 and actual_row_delta < expected_credit:
        blockers.append("expected_execution_parity_credit_missing")
    if expected_credit > 0 and after["execution_parity_journal_rows"] < int(expected_after_rows):
        blockers.append("projected_execution_parity_journal_row_not_reached")
    if expected_credit == 0 and actual_row_delta > 0:
        blockers.append("unexpected_execution_parity_credit_without_pre_apply_forecast")
    if actual_row_delta < 0:
        blockers.append("execution_parity_journal_row_regressed")
    if expected_credit > 0 and identity_check["journal_row_identity_check_available"] is True:
        if int(identity_check["new_journal_row_count"] or 0) < expected_credit:
            blockers.append("expected_new_execution_parity_journal_row_missing")
        elif identity_check["matching_new_row_found"] is not True:
            blockers.append("new_execution_parity_journal_row_does_not_match_expected_signal")
    if blockers and "live_order_flag_detected_in_evidence_report" in blockers:
        status = "blocked_live_order_flag_detected"
    elif expected_credit > 0 and not blockers:
        status = "paper_apply_parity_credit_confirmed"
    elif expected_credit > 0:
        status = "paper_apply_parity_credit_missing"
    elif actual_row_delta > 0:
        status = "unexpected_execution_parity_credit_review_required"
    else:
        status = "no_credit_expected_or_observed"
    return {
        "generated_at": generated_at.isoformat(),
        "status": status,
        "no_live_order_sent": before["no_live_order_sent"] is True and after["no_live_order_sent"] is True,
        "input_before_report": input_before_report,
        "input_after_report": input_after_report,
        "before": before,
        "after": after,
        "expected_credit_from_before_forecast": expected_credit,
        "expected_after_journal_rows": int(expected_after_rows),
        "actual_journal_row_delta": actual_row_delta,
        "actual_missing_sample_delta": actual_missing_delta,
        "new_journal_row_count": identity_check["new_journal_row_count"],
        "expected_journal_row_identity_check": identity_check,
        "credit_confirmed": expected_credit > 0 and actual_row_delta >= expected_credit and not blockers,
        "blockers": blockers,
        "next_actions": _next_actions(status=status, blockers=blockers, expected_credit=expected_credit),
        "order_submission_allowed": False,
    }


def _next_actions(*, status: str, blockers: list[str], expected_credit: int) -> list[str]:
    if status == "paper_apply_parity_credit_confirmed":
        return [
            "rerun_live_readiness_with_updated_execution_parity_contract",
            "continue_collecting_real_paper_apply_samples_until_execution_parity_reaches_20",
        ]
    if "expected_execution_parity_credit_missing" in blockers:
        return [
            "inspect_paper_bridge_apply_result_and_lifecycle_export",
            "verify_paper_fill_qty_price_timestamp_source_event_and_slippage_fields",
            "rerun_evidence_cycle_after_lifecycle_row_is_complete",
        ]
    if "new_execution_parity_journal_row_does_not_match_expected_signal" in blockers:
        return [
            "inspect_new_execution_parity_journal_row_identity",
            "verify_actual_action_side_source_bar_ts_match_pre_apply_signal",
            "review_whether_an_unrelated_lifecycle_row_was_collected_between_reports",
        ]
    if "unexpected_execution_parity_credit_without_pre_apply_forecast" in blockers:
        return [
            "review_before_after_evidence_pairing_and_recent_lifecycle_rows",
            "verify_no_unrelated_paper_apply_was_collected_between_reports",
        ]
    if expected_credit <= 0:
        return [
            "wait_for_fresh_creditable_add_or_remove_signal_before_expectation_of_parity_credit",
            "continue_no_live_shadow_watch",
        ]
    return ["review_execution_parity_contract_blockers"]


def _markdown(report: dict[str, Any]) -> str:
    before = dict(report.get("before") or {})
    after = dict(report.get("after") or {})
    identity = dict(report.get("expected_journal_row_identity_check") or {})
    return "\n".join(
        [
            "# Market State Rotation V6 Paper Apply Parity Review",
            "",
            f"- status: `{report.get('status')}`",
            f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
            f"- expected_credit_from_before_forecast: `{report.get('expected_credit_from_before_forecast')}`",
            f"- expected_after_journal_rows: `{report.get('expected_after_journal_rows')}`",
            f"- before_journal_rows: `{before.get('execution_parity_journal_rows')}`",
            f"- after_journal_rows: `{after.get('execution_parity_journal_rows')}`",
            f"- actual_journal_row_delta: `{report.get('actual_journal_row_delta')}`",
            f"- before_missing_samples: `{before.get('execution_parity_missing_samples')}`",
            f"- after_missing_samples: `{after.get('execution_parity_missing_samples')}`",
            f"- actual_missing_sample_delta: `{report.get('actual_missing_sample_delta')}`",
            f"- new_journal_row_count: `{report.get('new_journal_row_count')}`",
            f"- expected_action: `{identity.get('expected_action')}`",
            f"- expected_side: `{identity.get('expected_side')}`",
            f"- expected_source_ts: `{identity.get('expected_source_ts')}`",
            f"- matching_new_row_found: `{identity.get('matching_new_row_found')}`",
            f"- blockers: `{report.get('blockers')}`",
            "",
            "## Next Actions",
            "",
            *[f"- {item}" for item in list(report.get("next_actions") or [])],
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review v6 PAPER apply execution parity credit.")
    parser.add_argument("--before-evidence-report", required=True)
    parser.add_argument("--after-evidence-report", required=True)
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    before_path = _resolve(args.before_evidence_report)
    after_path = _resolve(args.after_evidence_report)
    report_dir = _resolve(args.report_dir)
    if before_path is None or after_path is None or report_dir is None:
        raise ValueError("before, after, and report-dir paths are required")
    report = build_paper_apply_parity_review(
        before_report=_load_json(before_path),
        after_report=_load_json(after_path),
        input_before_report=_display_path(before_path),
        input_after_report=_display_path(after_path),
    )
    if args.write_report:
        _write_json(report_dir / REPORT_NAME, report)
        _write_text(report_dir / "market_state_rotation_v6_paper_apply_parity_review.md", _markdown(report))
        print(f"wrote {_display_path(report_dir / REPORT_NAME)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
