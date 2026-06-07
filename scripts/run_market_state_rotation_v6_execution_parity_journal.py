#!/usr/bin/env python3
"""Build a v6 execution parity journal from PAPER/live lifecycle rows.

This script is read-only with respect to execution.  It converts observed
market_state_rotation_v6 lifecycle rows into the narrow journal schema consumed
by run_market_state_rotation_v6_execution_parity_contract.py, then runs that
contract so readiness can see exactly which real execution fields are still
missing.
"""

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
from app.services.live_order_lifecycle import LiveOrderLifecycleReporter
from scripts.run_market_state_rotation_v6_execution_parity_contract import (
    build_execution_parity_contract_report,
)


EXPECTED_SYMBOL = "BTCUSDT"
EXPECTED_STRATEGY_FAMILY = "market_state_rotation_v6"
DEFAULT_WALK_FORWARD_REPORT = (
    "reports/validation/diagnostics/market_state_rotation_v6_meta_router_shadow_wfo/"
    "one_way_trim_tax_light_formal/market_state_rotation_v6_walk_forward_BTCUSDT_5m_latest.json"
)
DEFAULT_REPORT_DIR = "reports/validation/diagnostics/market_state_rotation_v6_execution_parity_journal"
DEFAULT_JOURNAL_NAME = "market_state_rotation_v6_execution_parity_journal.jsonl"


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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _parse_dt(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _float_or_none(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _event_action(event: dict[str, Any], fallback: str) -> str:
    action = str(event.get("action") or "").strip().lower()
    return action if action in {"add", "remove", "flip"} else fallback


def _event_side(event: dict[str, Any], fallback: Any) -> str:
    side = str(event.get("side") or fallback or "").strip().lower()
    return side


def _event_role(event: dict[str, Any]) -> str:
    for key in ("role", "entry_role", "sizing_role"):
        value = str(event.get(key) or "").strip().lower()
        if value:
            return value
    return ""


def _source_ts(row: dict[str, Any], event: dict[str, Any]) -> str | None:
    for value in (
        event.get("ts"),
        event.get("source_bar_ts"),
        row.get("plan_source_event_ts"),
        row.get("source_bar_ts"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return None


def _signal_lag_bars(*, source_ts: Any, execution_ts: Any, interval_minutes: int = 5) -> float | None:
    source_dt = _parse_dt(source_ts)
    execution_dt = _parse_dt(execution_ts)
    if source_dt is None or execution_dt is None:
        return None
    seconds_per_bar = max(1, int(interval_minutes)) * 60
    return round(max((execution_dt - source_dt).total_seconds(), 0.0) / seconds_per_bar, 4)


def _fee_slippage_bps(row: dict[str, Any], *, action: str) -> float | None:
    if action == "add":
        value = _float_or_none(row.get("entry_slippage_bps"))
        return round(abs(value), 4) if value is not None else None
    value = _float_or_none(row.get("exit_slippage_bps"))
    return round(abs(value), 4) if value is not None else None


def _position_diff_units(row: dict[str, Any], *, action: str) -> float | None:
    adapter = str(row.get("adapter") or "").strip().lower()
    fill_count_key = "entry_fill_count" if action == "add" else "exit_fill_count"
    fill_qty_key = "entry_fill_qty" if action == "add" else "exit_fill_qty"
    if adapter == "paper" and _int_value(row.get(fill_count_key)) > 0 and (_float_or_none(row.get(fill_qty_key)) or 0.0) > 0.0:
        return 0.0
    orig_qty = _float_or_none(row.get("binance_orig_qty"))
    executed_qty = _float_or_none(row.get("binance_executed_qty"))
    if orig_qty is not None and executed_qty is not None:
        return round(abs(orig_qty - executed_qty), 8)
    return None


def _entry_journal_row(row: dict[str, Any], *, interval_minutes: int) -> dict[str, Any]:
    event = _safe_dict(row.get("plan_source_event"))
    timestamp = row.get("entry_first_fill_at") or row.get("acknowledged_at") or row.get("submitted_at")
    source_ts = _source_ts(row, event)
    return {
        "timestamp": timestamp,
        "symbol": row.get("symbol"),
        "strategy_family": row.get("strategy_family"),
        "decision_id": row.get("client_order_id") or row.get("intent_id") or row.get("submission_id"),
        "source_bar_ts": source_ts,
        "actual_action": "add",
        "expected_action": _event_action(event, "add"),
        "actual_side": row.get("side") or row.get("plan_direction"),
        "expected_side": _event_side(event, row.get("plan_direction")),
        "role": _event_role(event),
        "signal_lag_bars": _signal_lag_bars(
            source_ts=source_ts,
            execution_ts=timestamp,
            interval_minutes=interval_minutes,
        ),
        "position_diff_units": _position_diff_units(row, action="add"),
        "fee_slippage_bps": _fee_slippage_bps(row, action="add"),
        "effective_exposure": row.get("effective_exposure"),
        "source": "market_state_rotation_v6_lifecycle_to_parity_journal",
        "source_plan_id": row.get("plan_id"),
        "source_submission_id": row.get("submission_id"),
    }


def _exit_journal_row(row: dict[str, Any], *, interval_minutes: int) -> dict[str, Any]:
    event = _safe_dict(row.get("exit_source_event"))
    timestamp = row.get("exit_last_fill_at")
    source_ts = _source_ts(row, event)
    return {
        "timestamp": timestamp,
        "symbol": row.get("symbol"),
        "strategy_family": row.get("strategy_family"),
        "decision_id": f"{row.get('client_order_id') or row.get('intent_id') or row.get('submission_id')}:exit",
        "source_bar_ts": source_ts,
        "actual_action": "remove",
        "expected_action": _event_action(event, "remove"),
        "actual_side": row.get("plan_direction") or row.get("side"),
        "expected_side": _event_side(event, row.get("plan_direction") or row.get("side")),
        "role": _event_role(event),
        "signal_lag_bars": _signal_lag_bars(
            source_ts=source_ts,
            execution_ts=timestamp,
            interval_minutes=interval_minutes,
        ),
        "position_diff_units": _position_diff_units(row, action="remove"),
        "fee_slippage_bps": _fee_slippage_bps(row, action="remove"),
        "effective_exposure": row.get("effective_exposure"),
        "source": "market_state_rotation_v6_lifecycle_to_parity_journal",
        "source_plan_id": row.get("plan_id"),
        "source_submission_id": row.get("submission_id"),
    }


def build_execution_parity_journal_rows(
    lifecycle_payload: dict[str, Any],
    *,
    symbol: str = EXPECTED_SYMBOL,
    strategy_family: str = EXPECTED_STRATEGY_FAMILY,
    interval_minutes: int = 5,
    include_exit_rows: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    expected_symbol = str(symbol or EXPECTED_SYMBOL).upper()
    expected_family = str(strategy_family or EXPECTED_STRATEGY_FAMILY)
    for raw in list(lifecycle_payload.get("rows") or []):
        row = dict(raw or {})
        if str(row.get("symbol") or "").upper() != expected_symbol:
            continue
        if str(row.get("strategy_family") or "") != expected_family:
            continue
        if _int_value(row.get("entry_fill_count")) > 0:
            rows.append(_entry_journal_row(row, interval_minutes=interval_minutes))
        if include_exit_rows and _int_value(row.get("exit_fill_count")) > 0:
            rows.append(_exit_journal_row(row, interval_minutes=interval_minutes))
    rows.sort(key=lambda item: str(item.get("timestamp") or ""))
    return rows


def _load_lifecycle_from_db(
    *,
    symbol: str,
    strategy_family: str,
    days: int,
    limit: int,
) -> dict[str, Any]:
    init_db()
    with SessionLocal() as db:
        return LiveOrderLifecycleReporter(db).generate(
            days=max(1, int(days)),
            symbol=str(symbol or EXPECTED_SYMBOL).upper(),
            live_only=False,
            limit=max(1, int(limit)),
            strategy_families=[str(strategy_family or EXPECTED_STRATEGY_FAMILY)],
        )


def _collection_plan(
    *,
    conversion: dict[str, Any],
    summary: dict[str, Any],
    include_exit_rows: bool,
) -> dict[str, Any]:
    sample_count = _int_value(summary.get("sample_count"))
    required = max(1, _int_value(summary.get("min_sample_count"), 20))
    missing_samples = max(required - sample_count, 0)
    blockers = list(summary.get("blockers") or [])
    accepted_actions = ["add", "remove"] if include_exit_rows else ["add"]
    if bool(summary.get("passed")):
        status = "passed"
        next_step = "rerun_live_readiness_with_this_execution_parity_contract_report"
    elif missing_samples > 0:
        status = "collecting_samples"
        next_step = "collect_completed_paper_add_or_remove_lifecycle_rows_and_rerun_journal"
    else:
        status = "schema_or_threshold_blocked"
        next_step = "fix_contract_blockers_before_promotion"
    return {
        "status": status,
        "sample_count": sample_count,
        "required_samples": required,
        "missing_samples": missing_samples,
        "estimated_future_paper_apply_events_needed": missing_samples,
        "sample_credit_per_completed_paper_apply_event": 1,
        "accepted_actions": accepted_actions,
        "entry_rows_written": _int_value(conversion.get("entry_rows_written")),
        "exit_rows_written": _int_value(conversion.get("exit_rows_written")),
        "include_exit_rows": bool(include_exit_rows),
        "blockers": blockers,
        "next_step": next_step,
        "sample_credit_policy": {
            "add": "one_completed_paper_add_lifecycle_row_counts_as_one_execution_parity_sample",
            "remove": (
                "one_completed_paper_remove_exit_lifecycle_row_counts_as_one_execution_parity_sample"
                if include_exit_rows
                else "remove_rows_are_not_enabled_for_this_journal_run"
            ),
            "backtest_rows": "not_creditable_for_execution_parity",
            "manual_or_synthetic_rows": "not_creditable_for_execution_parity",
        },
        "non_substitutable": True,
        "backtest_substitution_allowed": False,
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def build_execution_parity_journal_report(
    *,
    walk_report: dict[str, Any],
    lifecycle_payload: dict[str, Any],
    input_walk_report: str | None = None,
    input_lifecycle_report: str | None = None,
    input_execution_journal: str | None = None,
    symbol: str = EXPECTED_SYMBOL,
    strategy_family: str = EXPECTED_STRATEGY_FAMILY,
    interval_minutes: int = 5,
    min_sample_count: int = 20,
    include_exit_rows: bool = False,
    generated_at: datetime | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    generated_at = generated_at or datetime.now(UTC)
    journal_rows = build_execution_parity_journal_rows(
        lifecycle_payload,
        symbol=symbol,
        strategy_family=strategy_family,
        interval_minutes=interval_minutes,
        include_exit_rows=include_exit_rows,
    )
    contract_report = build_execution_parity_contract_report(
        walk_report,
        journal_rows,
        input_walk_report=input_walk_report,
        input_execution_journal=input_execution_journal,
        expected_strategy_family=strategy_family,
        min_sample_count=max(1, int(min_sample_count)),
    )
    summary = dict(contract_report.get("summary") or {})
    observed = dict(contract_report.get("observed") or {})
    sample_count = int(summary.get("sample_count") or 0)
    missing_samples = max(int(summary.get("min_sample_count") or min_sample_count) - sample_count, 0)
    conversion = {
        "lifecycle_row_count": len(list(lifecycle_payload.get("rows") or [])),
        "journal_row_count": len(journal_rows),
        "entry_rows_written": sum(1 for row in journal_rows if str(row.get("actual_action")) == "add"),
        "exit_rows_written": sum(1 for row in journal_rows if str(row.get("actual_action")) == "remove"),
        "include_exit_rows": bool(include_exit_rows),
        "missing_to_min_sample_count": missing_samples,
    }
    report = {
        "generated_at": generated_at.isoformat(),
        "status": "execution_parity_journal_passed" if bool(summary.get("passed")) else "execution_parity_journal_collecting",
        "no_live_order_sent": True,
        "input_walk_forward_report": input_walk_report,
        "input_lifecycle_report": input_lifecycle_report,
        "input_execution_journal": input_execution_journal,
        "symbol": str(symbol or EXPECTED_SYMBOL).upper(),
        "strategy_family": str(strategy_family or EXPECTED_STRATEGY_FAMILY),
        "conversion": conversion,
        "collection_plan": _collection_plan(
            conversion=conversion,
            summary=summary,
            include_exit_rows=bool(include_exit_rows),
        ),
        "contract_summary": summary,
        "contract_observed": observed,
        "contract_report": contract_report,
        "next_actions": [
            "collect_more_market_state_rotation_v6_paper_lifecycle_rows"
            if missing_samples > 0
            else "review_schema_or_threshold_blockers_in_contract_report",
            "rerun_live_readiness_with_this_execution_parity_contract_report",
        ],
    }
    return report, journal_rows


def _markdown(report: dict[str, Any]) -> str:
    conversion = dict(report.get("conversion") or {})
    summary = dict(report.get("contract_summary") or {})
    plan = dict(report.get("collection_plan") or {})
    return "\n".join(
        [
            "# Market State Rotation V6 Execution Parity Journal",
            "",
            f"- status: `{report.get('status')}`",
            f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
            f"- journal rows: `{conversion.get('journal_row_count')}/{summary.get('min_sample_count')}`",
            f"- missing samples: `{conversion.get('missing_to_min_sample_count')}`",
            f"- contract passed: `{summary.get('passed')}`",
            f"- order match rate: `{summary.get('order_match_rate')}`",
            f"- max signal lag bars: `{summary.get('max_signal_lag_bars')}`",
            f"- max position diff units: `{summary.get('max_position_diff_units')}`",
            f"- max fee/slippage bps: `{summary.get('max_fee_slippage_bps')}`",
            f"- blockers: `{', '.join(summary.get('blockers') or [])}`",
            f"- collection status: `{plan.get('status')}`",
            f"- paper apply events needed: `{plan.get('estimated_future_paper_apply_events_needed')}`",
            f"- accepted actions: `{plan.get('accepted_actions')}`",
            f"- next step: `{plan.get('next_step')}`",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v6 execution parity journal from lifecycle evidence.")
    parser.add_argument("--walk-forward-report", default=DEFAULT_WALK_FORWARD_REPORT)
    parser.add_argument("--lifecycle-report", default="")
    parser.add_argument("--symbol", default=EXPECTED_SYMBOL)
    parser.add_argument("--strategy-family", default=EXPECTED_STRATEGY_FAMILY)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--interval-minutes", type=int, default=5)
    parser.add_argument("--min-sample-count", type=int, default=20)
    parser.add_argument("--include-exit-rows", action="store_true")
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--journal-jsonl", default="")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    walk_path = _resolve(args.walk_forward_report)
    if walk_path is None:
        raise ValueError("walk-forward report is required")
    lifecycle_path = _resolve(args.lifecycle_report)
    walk_report = _load_json(walk_path)
    lifecycle_payload = (
        _load_json(lifecycle_path)
        if lifecycle_path is not None and lifecycle_path.exists()
        else _load_lifecycle_from_db(
            symbol=str(args.symbol or EXPECTED_SYMBOL),
            strategy_family=str(args.strategy_family or EXPECTED_STRATEGY_FAMILY),
            days=max(1, int(args.days)),
            limit=max(1, int(args.limit)),
        )
    )
    report_dir = _resolve(args.report_dir)
    assert report_dir is not None
    journal_path = _resolve(args.journal_jsonl) if args.journal_jsonl else report_dir / DEFAULT_JOURNAL_NAME
    assert journal_path is not None
    report, journal_rows = build_execution_parity_journal_report(
        walk_report=walk_report,
        lifecycle_payload=lifecycle_payload,
        input_walk_report=_display_path(walk_path),
        input_lifecycle_report=_display_path(lifecycle_path) if lifecycle_path is not None else "generated_from_db",
        input_execution_journal=_display_path(journal_path),
        symbol=str(args.symbol or EXPECTED_SYMBOL),
        strategy_family=str(args.strategy_family or EXPECTED_STRATEGY_FAMILY),
        interval_minutes=max(1, int(args.interval_minutes)),
        min_sample_count=max(1, int(args.min_sample_count)),
        include_exit_rows=bool(args.include_exit_rows),
    )
    if args.write_report:
        report_dir.mkdir(parents=True, exist_ok=True)
        _write_jsonl(journal_path, journal_rows)
        _write_json(report_dir / "market_state_rotation_v6_execution_parity_journal.json", report)
        _write_json(
            report_dir / "market_state_rotation_v6_execution_parity_contract.json",
            dict(report.get("contract_report") or {}),
        )
        (report_dir / "market_state_rotation_v6_execution_parity_journal.md").write_text(
            _markdown(report),
            encoding="utf-8",
        )
        print(f"wrote {_display_path(journal_path)}")
        print(f"wrote {_display_path(report_dir / 'market_state_rotation_v6_execution_parity_journal.json')}")
        print(f"wrote {_display_path(report_dir / 'market_state_rotation_v6_execution_parity_contract.json')}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
