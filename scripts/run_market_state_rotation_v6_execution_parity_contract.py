#!/usr/bin/env python3
"""Validate market-state rotation v6 paper/live execution evidence.

This checker is intentionally narrower than a generic live replay audit.  It
only accepts evidence that is tied back to the market_state_rotation_v6 decision
lineage, so readiness cannot be unlocked by an unrelated strategy family or by
an empty runtime window.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPECTED_STRATEGY_FAMILY = "market_state_rotation_v6"
KNOWN_ENTRY_ROLES = {"base", "probe", "chase"}

EXECUTION_TS_ALIASES = ("timestamp", "ts", "executed_at", "created_at")
ACTION_ALIASES = ("actual_action", "action", "event_type", "kind", "order_action")
EXPECTED_ACTION_ALIASES = ("expected_action", "replay_action", "backtest_action")
SIDE_ALIASES = ("actual_side", "side", "direction", "position_side")
EXPECTED_SIDE_ALIASES = ("expected_side", "replay_side", "backtest_side")
ROLE_ALIASES = ("role", "entry_role", "sizing_role")
DECISION_ID_ALIASES = (
    "decision_id",
    "lineage_id",
    "lineage_event_id",
    "intent_id",
    "client_order_id",
)
SOURCE_BAR_TS_ALIASES = ("source_bar_ts", "bar_ts", "signal_ts", "signal_timestamp")
SIGNAL_LAG_ALIASES = ("signal_lag_bars", "decision_lag_bars", "execution_lag_bars")
POSITION_DIFF_ALIASES = ("position_diff_units", "position_delta_units", "exposure_diff_units")
FEE_SLIPPAGE_ALIASES = ("fee_slippage_bps", "total_cost_bps", "slippage_bps")
EXPOSURE_ALIASES = ("effective_exposure", "target_exposure", "position_exposure", "account_exposure")


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct(value: float) -> float:
    return round(float(value), 4)


def _first(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for key in aliases:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _normalize_action(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not text:
        return ""
    if text in {"open", "entry", "enter", "add", "increase", "scale_in", "buy", "sell"}:
        return "add"
    if text in {
        "reduce",
        "trim",
        "partial",
        "partial_close",
        "take_profit",
        "tp",
        "close",
        "exit",
        "stop",
        "stop_loss",
        "sl",
        "time_stop",
    }:
        return "remove"
    if text in {"flip", "reverse", "stop_flip"}:
        return "flip"
    return text


def _normalize_side(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"1", "+1", "long", "buy", "bid"}:
        return "long"
    if text in {"-1", "short", "sell", "ask"}:
        return "short"
    if text in {"0", "flat", "none", "neutral"}:
        return "flat"
    return text


def _normalize_role(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"base", "probe", "chase"}:
        return text
    return text


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _load_journal(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        rows: list[dict[str, Any]] = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
        return rows
    if suffix == ".csv":
        with path.open(newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    payload = _load_json(path)
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("events", "orders", "intents", "submissions", "journal", "rows"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, dict)]
    return []


def _walk_contract(
    walk_report: dict[str, Any],
    *,
    expected_strategy_family: str = EXPECTED_STRATEGY_FAMILY,
) -> dict[str, Any]:
    role_counts: dict[str, int] = {}
    unknown_role_counts: dict[str, int] = {}
    hour_counts: dict[str, int] = {}
    remove_hour_counts: dict[str, int] = {}
    baseline_exposures: list[float] = []
    for fold in walk_report.get("folds") or []:
        result = dict(fold.get("test_result") or {})
        config = dict(result.get("config") or {})
        baseline_exposures.append(
            _float(config.get("unit_account_exposure"), _float(result.get("max_abs_account_exposure")))
        )
        diagnostics = dict(result.get("event_diagnostics") or {})
        for role, count in dict(diagnostics.get("add_by_role") or {}).items():
            key = _normalize_role(role)
            if key:
                if key in KNOWN_ENTRY_ROLES:
                    role_counts[key] = role_counts.get(key, 0) + int(_float(count))
                else:
                    unknown_role_counts[key] = unknown_role_counts.get(key, 0) + int(_float(count))
        for hour, count in dict(diagnostics.get("add_by_kst_hour") or {}).items():
            key = f"{int(_float(hour)):02d}"
            hour_counts[key] = hour_counts.get(key, 0) + int(_float(count))
        for hour, count in dict(diagnostics.get("remove_by_kst_hour") or {}).items():
            key = f"{int(_float(hour)):02d}"
            remove_hour_counts[key] = remove_hour_counts.get(key, 0) + int(_float(count))
    return {
        "symbol": str(walk_report.get("symbol") or "").upper(),
        "exec_interval": walk_report.get("exec_interval"),
        "expected_strategy_family": expected_strategy_family,
        "baseline_unit_account_exposure": _pct(max(baseline_exposures, default=0.0)),
        "expected_add_by_role": dict(sorted(role_counts.items())),
        "ignored_unknown_add_by_role": dict(sorted(unknown_role_counts.items())),
        "expected_add_by_kst_hour": dict(sorted(hour_counts.items())),
        "expected_remove_by_kst_hour": dict(sorted(remove_hour_counts.items())),
    }


def build_execution_parity_contract_report(
    walk_report: dict[str, Any],
    execution_journal: list[dict[str, Any]] | None = None,
    *,
    input_walk_report: str | None = None,
    input_execution_journal: str | None = None,
    expected_symbol: str | None = None,
    expected_strategy_family: str = EXPECTED_STRATEGY_FAMILY,
    min_sample_count: int = 20,
    min_order_match_rate: float = 0.99,
    max_signal_lag_bars: float = 1.0,
    max_position_diff_units: float = 0.05,
    max_fee_slippage_bps: float = 25.0,
    max_effective_exposure: float | None = None,
) -> dict[str, Any]:
    contract = _walk_contract(walk_report, expected_strategy_family=expected_strategy_family)
    expected_symbol_value = str(expected_symbol or contract.get("symbol") or "").upper()
    rows = list(execution_journal or [])
    blockers: list[str] = []
    warnings: list[str] = []
    schema_issue_counts = {
        "missing_execution_ts": 0,
        "missing_symbol": 0,
        "missing_strategy_family": 0,
        "missing_action": 0,
        "missing_expected_action": 0,
        "missing_side": 0,
        "missing_expected_side": 0,
        "missing_decision_id": 0,
        "missing_source_bar_ts": 0,
        "missing_signal_lag_bars": 0,
        "missing_position_diff_units": 0,
        "missing_fee_slippage_bps": 0,
    }
    event_type_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    symbol_mismatches = 0
    family_mismatches = 0
    actionable = 0
    matched = 0
    mismatches: list[dict[str, Any]] = []
    signal_lags: list[float] = []
    position_diffs: list[float] = []
    fee_slippage_values: list[float] = []
    exposure_values: list[float] = []

    if not rows:
        blockers.append("execution_journal_missing")

    for idx, row in enumerate(rows):
        if _first(row, EXECUTION_TS_ALIASES) is None:
            schema_issue_counts["missing_execution_ts"] += 1
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            schema_issue_counts["missing_symbol"] += 1
        if expected_symbol_value and symbol and symbol != expected_symbol_value:
            symbol_mismatches += 1
        family = str(row.get("strategy_family") or row.get("family") or "")
        if not family:
            schema_issue_counts["missing_strategy_family"] += 1
        if family and family != expected_strategy_family:
            family_mismatches += 1

        action = _normalize_action(_first(row, ACTION_ALIASES))
        expected_action = _normalize_action(_first(row, EXPECTED_ACTION_ALIASES))
        side = _normalize_side(_first(row, SIDE_ALIASES))
        expected_side = _normalize_side(_first(row, EXPECTED_SIDE_ALIASES))
        role = _normalize_role(_first(row, ROLE_ALIASES))
        if not action:
            schema_issue_counts["missing_action"] += 1
            continue
        event_type_counts[action] = event_type_counts.get(action, 0) + 1
        if role:
            role_counts[role] = role_counts.get(role, 0) + 1
        if not expected_action:
            schema_issue_counts["missing_expected_action"] += 1
        if not side:
            schema_issue_counts["missing_side"] += 1
        if not expected_side:
            schema_issue_counts["missing_expected_side"] += 1
        if _first(row, DECISION_ID_ALIASES) is None:
            schema_issue_counts["missing_decision_id"] += 1
        if _first(row, SOURCE_BAR_TS_ALIASES) is None:
            schema_issue_counts["missing_source_bar_ts"] += 1
        lag_value = _first(row, SIGNAL_LAG_ALIASES)
        if lag_value is None:
            schema_issue_counts["missing_signal_lag_bars"] += 1
        else:
            signal_lags.append(abs(_float(lag_value)))
        diff_value = _first(row, POSITION_DIFF_ALIASES)
        if diff_value is None:
            schema_issue_counts["missing_position_diff_units"] += 1
        else:
            position_diffs.append(abs(_float(diff_value)))
        cost_value = _first(row, FEE_SLIPPAGE_ALIASES)
        if cost_value is None:
            schema_issue_counts["missing_fee_slippage_bps"] += 1
        else:
            fee_slippage_values.append(abs(_float(cost_value)))
        exposure_value = _first(row, EXPOSURE_ALIASES)
        if exposure_value is not None:
            exposure_values.append(abs(_float(exposure_value)))

        if action in {"add", "remove", "flip"}:
            actionable += 1
            action_match = action == expected_action
            side_match = expected_side in {"", "flat"} or side == expected_side
            if action_match and side_match:
                matched += 1
            elif len(mismatches) < 10:
                mismatches.append(
                    {
                        "row": idx,
                        "actual_action": action,
                        "expected_action": expected_action,
                        "actual_side": side,
                        "expected_side": expected_side,
                    }
                )

    if symbol_mismatches:
        blockers.append("execution_parity_symbol_mismatch")
    if family_mismatches:
        blockers.append("execution_parity_strategy_family_mismatch")
    if any(schema_issue_counts.values()):
        blockers.append("execution_journal_schema_missing_required_fields")
    if actionable < min_sample_count:
        blockers.append("insufficient_execution_sample_count")
    order_match_rate = matched / actionable if actionable > 0 else 0.0
    if actionable > 0 and order_match_rate < min_order_match_rate:
        blockers.append("order_match_rate_below_threshold")
    max_lag = max(signal_lags, default=None)
    if max_lag is not None and max_lag > max_signal_lag_bars:
        blockers.append("signal_lag_bars_above_threshold")
    max_position_diff = max(position_diffs, default=None)
    if max_position_diff is not None and max_position_diff > max_position_diff_units:
        blockers.append("position_diff_above_threshold")
    max_cost = max(fee_slippage_values, default=None)
    if max_cost is not None and max_cost > max_fee_slippage_bps:
        blockers.append("fee_slippage_bps_above_threshold")
    max_exposure = max(exposure_values, default=None)
    if (
        max_effective_exposure is not None
        and max_effective_exposure > 0.0
        and max_exposure is not None
        and max_exposure > max_effective_exposure
    ):
        blockers.append("effective_exposure_above_contract_cap")

    expected_roles = {
        role
        for role, count in dict(contract.get("expected_add_by_role") or {}).items()
        if int(count or 0) > 0
    }
    missing_roles = sorted(expected_roles - set(role_counts))
    if actionable >= min_sample_count * 3 and missing_roles:
        warnings.append("expected_entry_role_not_observed_in_runtime_window")

    status = "PASS" if not blockers else "WATCH"
    hard_fail_markers = {
        "execution_parity_symbol_mismatch",
        "execution_parity_strategy_family_mismatch",
        "order_match_rate_below_threshold",
        "signal_lag_bars_above_threshold",
        "position_diff_above_threshold",
        "fee_slippage_bps_above_threshold",
        "effective_exposure_above_contract_cap",
    }
    if hard_fail_markers.intersection(blockers):
        status = "FAIL"
    summary = {
        "status": status,
        "passed": status == "PASS",
        "symbol": expected_symbol_value,
        "walk_forward_symbol": contract.get("symbol"),
        "strategy_families": [expected_strategy_family],
        "sample_count": actionable,
        "min_sample_count": min_sample_count,
        "order_match_rate": round(order_match_rate, 6),
        "min_order_match_rate": min_order_match_rate,
        "max_signal_lag_bars": _pct(max_lag) if max_lag is not None else None,
        "max_allowed_signal_lag_bars": max_signal_lag_bars,
        "max_position_diff_units": _pct(max_position_diff) if max_position_diff is not None else None,
        "max_allowed_position_diff_units": max_position_diff_units,
        "max_fee_slippage_bps": _pct(max_cost) if max_cost is not None else None,
        "max_allowed_fee_slippage_bps": max_fee_slippage_bps,
        "max_effective_exposure": _pct(max_exposure) if max_exposure is not None else None,
        "max_allowed_effective_exposure": max_effective_exposure,
        "blockers": blockers,
        "warnings": warnings,
    }
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "overall_status": status,
        "input_walk_forward_report": input_walk_report,
        "input_execution_journal": input_execution_journal,
        "contract": contract,
        "summary": summary,
        "observed": {
            "row_count": len(rows),
            "actionable_event_count": actionable,
            "matched_event_count": matched,
            "event_type_counts": dict(sorted(event_type_counts.items())),
            "role_counts": dict(sorted(role_counts.items())),
            "symbol_mismatch_count": symbol_mismatches,
            "strategy_family_mismatch_count": family_mismatches,
            "schema_issue_counts": schema_issue_counts,
            "sample_mismatches": mismatches,
            "missing_expected_roles": missing_roles,
        },
        "required_fields": {
            "execution_timestamp": list(EXECUTION_TS_ALIASES),
            "symbol": ["symbol"],
            "strategy_family": ["strategy_family", "family"],
            "actual_action": list(ACTION_ALIASES),
            "expected_action": list(EXPECTED_ACTION_ALIASES),
            "actual_side": list(SIDE_ALIASES),
            "expected_side": list(EXPECTED_SIDE_ALIASES),
            "decision_lineage_id": list(DECISION_ID_ALIASES),
            "source_bar_timestamp": list(SOURCE_BAR_TS_ALIASES),
            "signal_lag_bars": list(SIGNAL_LAG_ALIASES),
            "position_diff_units": list(POSITION_DIFF_ALIASES),
            "fee_slippage_bps": list(FEE_SLIPPAGE_ALIASES),
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary") or {})
    observed = dict(report.get("observed") or {})
    lines = [
        "# Market State Rotation V6 Execution Parity Contract",
        "",
        f"- Status: `{report.get('overall_status')}`",
        f"- Passed: `{summary.get('passed')}`",
        f"- Symbol: `{summary.get('symbol')}`",
        f"- Strategy families: `{', '.join(summary.get('strategy_families') or [])}`",
        f"- Sample count: `{summary.get('sample_count')}/{summary.get('min_sample_count')}`",
        f"- Order match rate: `{summary.get('order_match_rate')}`",
        f"- Max signal lag bars: `{summary.get('max_signal_lag_bars')}`",
        f"- Max position diff units: `{summary.get('max_position_diff_units')}`",
        f"- Max fee/slippage bps: `{summary.get('max_fee_slippage_bps')}`",
        f"- Blockers: `{', '.join(summary.get('blockers') or [])}`",
        f"- Warnings: `{', '.join(summary.get('warnings') or [])}`",
        "",
        "## Observed",
        "",
        f"- Rows: `{observed.get('row_count')}`",
        f"- Actionable events: `{observed.get('actionable_event_count')}`",
        f"- Matched events: `{observed.get('matched_event_count')}`",
        f"- Event type counts: `{json.dumps(observed.get('event_type_counts'), ensure_ascii=False)}`",
        f"- Role counts: `{json.dumps(observed.get('role_counts'), ensure_ascii=False)}`",
        f"- Schema issues: `{json.dumps(observed.get('schema_issue_counts'), ensure_ascii=False)}`",
    ]
    mismatches = list(observed.get("sample_mismatches") or [])
    if mismatches:
        lines.extend(["", "## Sample Mismatches", ""])
        for item in mismatches:
            lines.append(f"- `{json.dumps(item, ensure_ascii=False)}`")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate market-state rotation v6 paper/live execution parity evidence."
    )
    parser.add_argument("--walk-forward-report", required=True)
    parser.add_argument("--execution-journal", default="")
    parser.add_argument("--expected-symbol", default="")
    parser.add_argument("--report-dir", default="reports/validation/diagnostics/market_state_rotation_v6_execution_parity_contract")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--min-sample-count", type=int, default=20)
    parser.add_argument("--min-order-match-rate", type=float, default=0.99)
    parser.add_argument("--max-signal-lag-bars", type=float, default=1.0)
    parser.add_argument("--max-position-diff-units", type=float, default=0.05)
    parser.add_argument("--max-fee-slippage-bps", type=float, default=25.0)
    parser.add_argument("--max-effective-exposure", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    walk_path = Path(args.walk_forward_report)
    if not walk_path.is_absolute():
        walk_path = ROOT_DIR / walk_path
    journal_path = Path(args.execution_journal) if args.execution_journal else None
    if journal_path is not None and not journal_path.is_absolute():
        journal_path = ROOT_DIR / journal_path
    walk_report = _load_json(walk_path)
    journal = _load_journal(journal_path) if journal_path is not None else None
    report = build_execution_parity_contract_report(
        walk_report,
        journal,
        input_walk_report=str(walk_path.relative_to(ROOT_DIR)) if walk_path.is_relative_to(ROOT_DIR) else str(walk_path),
        input_execution_journal=(
            str(journal_path.relative_to(ROOT_DIR))
            if journal_path is not None and journal_path.is_relative_to(ROOT_DIR)
            else (str(journal_path) if journal_path is not None else None)
        ),
        expected_symbol=str(args.expected_symbol or "").upper() or None,
        min_sample_count=args.min_sample_count,
        min_order_match_rate=args.min_order_match_rate,
        max_signal_lag_bars=args.max_signal_lag_bars,
        max_position_diff_units=args.max_position_diff_units,
        max_fee_slippage_bps=args.max_fee_slippage_bps,
        max_effective_exposure=args.max_effective_exposure or None,
    )
    if args.write_report:
        report_dir = Path(args.report_dir)
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / "market_state_rotation_v6_execution_parity_contract.json"
        md_path = report_dir / "market_state_rotation_v6_execution_parity_contract.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        md_path.write_text(_markdown(report))
        print(f"wrote {json_path.relative_to(ROOT_DIR)}")
        print(f"wrote {md_path.relative_to(ROOT_DIR)}")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
