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

from app.core.config import get_settings
from app.db.repositories import CandleRepository
from app.db.session import SessionLocal, init_db
from app.services.live_order_lifecycle import LiveOrderLifecycleReporter
from app.services.runtime_worker_heartbeat import read_worker_heartbeat
from scripts.operation_report_io import atomic_write_text, display_path, parse_report_generated_at, write_latest_aliases
from scripts.run_micro_live_preflight import _micro_live_config_drift_checks


SESSION_IMPULSE_RETEST_MIN_1M_CANDLES = 600
SESSION_IMPULSE_RETEST_MIN_5M_CANDLES = 200


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run fast MICRO_LIVE runtime guard checks without calling the local API preflight surfaces."
    )
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--check-binance-rules", action="store_true")
    parser.add_argument("--report-dir", default="reports/operations/micro_live_runtime_guard")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-fail-exit", action="store_true", help="Always return exit code 0 after printing the report.")
    parser.add_argument("--quiet", action="store_true", help="Do not print the JSON payload to stdout.")
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    return display_path(path, ROOT_DIR)


def _csv_set(value: Any) -> set[str]:
    return {item.strip() for item in str(value or "").split(",") if item.strip()}


def _csv_upper_set(value: Any) -> set[str]:
    return {item.strip().upper() for item in str(value or "").split(",") if item.strip()}


def _parse_utc_ts(value: Any) -> datetime | None:
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


def _ws_runtime_started_at() -> datetime | None:
    payload = read_worker_heartbeat("ws")
    details = dict(payload.get("details") or {}) if isinstance(payload, dict) else {}
    return _parse_utc_ts(details.get("started_at"))


def _blocking_failures(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in checks
        if str(item.get("severity") or "").lower() == "blocking" and str(item.get("status") or "").upper() != "PASS"
    ]


def _warning_failures(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in checks
        if str(item.get("severity") or "").lower() != "blocking" and str(item.get("status") or "").upper() != "PASS"
    ]


def _live_candle_depth_check(
    candle_repo: Any,
    *,
    symbols: list[str],
    min_1m: int = SESSION_IMPULSE_RETEST_MIN_1M_CANDLES,
    min_5m: int = SESSION_IMPULSE_RETEST_MIN_5M_CANDLES,
) -> dict[str, Any]:
    normalized_symbols = sorted({str(symbol or "").upper().strip() for symbol in symbols if str(symbol or "").strip()})
    deficits: list[dict[str, Any]] = []
    min_observed_1m: int | None = None
    min_observed_5m: int | None = None
    for symbol in normalized_symbols:
        count_1m = len(candle_repo.list_recent(symbol=symbol, timeframe="1m", limit=max(1, int(min_1m))))
        count_5m = len(candle_repo.list_recent(symbol=symbol, timeframe="5m", limit=max(1, int(min_5m))))
        min_observed_1m = count_1m if min_observed_1m is None else min(min_observed_1m, count_1m)
        min_observed_5m = count_5m if min_observed_5m is None else min(min_observed_5m, count_5m)
        if count_1m < int(min_1m) or count_5m < int(min_5m):
            deficits.append(
                {
                    "symbol": symbol,
                    "candles_1m": count_1m,
                    "candles_5m": count_5m,
                    "required_1m": int(min_1m),
                    "required_5m": int(min_5m),
                }
            )

    if not normalized_symbols:
        return {
            "name": "live_candle_depth",
            "status": "FAIL",
            "severity": "blocking",
            "message": "live_symbols=0; cannot verify SIR candle depth",
            "deficits": [],
        }

    deficient_symbols = [str(item["symbol"]) for item in deficits[:8]]
    status = "PASS" if not deficits else "FAIL"
    return {
        "name": "live_candle_depth",
        "status": status,
        "severity": "blocking",
        "message": (
            f"symbols={len(normalized_symbols)}; min_1m={int(min_1m)}; min_5m={int(min_5m)}; "
            f"min_observed_1m={min_observed_1m}; min_observed_5m={min_observed_5m}; "
            f"deficient={','.join(deficient_symbols) if deficient_symbols else 'none'}"
        ),
        "deficient_count": len(deficits),
        "deficits": deficits[:20],
    }


_BLOCK_REASON_ACTIONS = {
    "validation_do_not_deploy": "inspect_validation_report_approval_surface",
    "rollout_session_not_allowed": "inspect_session_time_contract_or_wait_for_allowed_window",
    "symbol_not_live_enabled": "align_live_symbol_allowlists_before_enabling",
    "strategy_family_not_live_enabled": "align_live_family_allowlists_before_enabling",
    "entry_model_not_live_enabled": "align_live_entry_model_allowlist_before_enabling",
    "adjusted_score_non_positive": "inspect_scoring_and_risk_gate_inputs",
    "live_liquidity_gate_blocked": "inspect_orderbook_liquidity_gate_snapshot",
    "safety_lock_active": "inspect_execution_safety_state",
}


def _blocked_intent_diagnostics(lifecycle: dict[str, Any]) -> list[dict[str, Any]]:
    live_intents = dict((dict(lifecycle.get("summary") or {}).get("live_intents")) or {})
    top_reasons = dict(live_intents.get("top_block_reasons") or {})
    samples = [dict(item) for item in list(live_intents.get("recent_blocked_intents") or []) if isinstance(item, dict)]
    diagnostics: list[dict[str, Any]] = []
    for reason, count in top_reasons.items():
        reason_text = str(reason or "none")
        diagnostics.append(
            {
                "reason": reason_text,
                "count": int(count or 0),
                "action": _BLOCK_REASON_ACTIONS.get(reason_text, "inspect_recent_blocked_intent_samples"),
                "recent_samples": [
                    sample
                    for sample in samples
                    if str(sample.get("decision_reason_code") or "none") == reason_text
                ][:3],
                "detail": next(
                    (
                        dict(sample.get("block_detail") or {})
                        for sample in samples
                        if str(sample.get("decision_reason_code") or "none") == reason_text
                        and isinstance(sample.get("block_detail"), dict)
                        and sample.get("block_detail")
                    ),
                    {},
                ),
            }
        )
    return diagnostics


def _recommendations(*, blocking_failures: list[dict[str, Any]], lifecycle: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    if blocking_failures:
        names = ",".join(str(item.get("name") or "unknown") for item in blocking_failures[:8])
        recommendations.append(f"fix_blocking_runtime_checks:{names}")

    live_intents = dict((dict(lifecycle.get("summary") or {}).get("live_intents")) or {})
    total_intents = int(live_intents.get("total") or 0)
    submit_ready = int(live_intents.get("submit_ready") or 0)
    blocked = int(live_intents.get("blocked") or 0)
    if total_intents > 0 and submit_ready == 0 and blocked >= total_intents:
        top_reasons = dict(live_intents.get("top_block_reasons") or {})
        reason_text = ",".join(f"{key}={value}" for key, value in list(top_reasons.items())[:4])
        recommendations.append(f"all_recent_live_intents_blocked:{reason_text or 'unknown'}")
        for item in _blocked_intent_diagnostics(lifecycle)[:3]:
            recommendations.append(f"{item['action']}:{item['reason']}={item['count']}")

    summary = dict(lifecycle.get("summary") or {})
    if int(summary.get("rejected_or_error_count") or 0) > 0:
        recommendations.append("inspect_rejected_or_error_order_submissions")
    if int(summary.get("submitted_without_entry_fill_count") or 0) > 0:
        recommendations.append("inspect_submitted_orders_without_entry_fills")
    return recommendations


def _operational_status(
    *,
    blocking_failures: list[dict[str, Any]],
    lifecycle: dict[str, Any],
    warning_failures: list[dict[str, Any]] | None = None,
) -> str:
    if blocking_failures:
        return "FAIL"
    if warning_failures:
        return "WATCH"
    live_intents = dict((dict(lifecycle.get("summary") or {}).get("live_intents")) or {})
    total_intents = int(live_intents.get("total") or 0)
    submit_ready = int(live_intents.get("submit_ready") or 0)
    blocked = int(live_intents.get("blocked") or 0)
    if total_intents > 0 and submit_ready == 0 and blocked >= total_intents:
        return "WATCH"
    summary = dict(lifecycle.get("summary") or {})
    if int(summary.get("rejected_or_error_count") or 0) > 0:
        return "WATCH"
    return "PASS"


def build_payload(*, days: int, limit: int, check_binance_rules: bool) -> dict[str, Any]:
    settings = get_settings()
    family_filter = _csv_set(getattr(settings, "auto_trading_micro_live_allowed_families", ""))
    if not family_filter:
        family_filter = _csv_set(getattr(settings, "auto_trading_allowed_families", ""))
    symbol_filter = _csv_upper_set(getattr(settings, "auto_trading_micro_live_allowed_symbols", ""))
    if not symbol_filter:
        symbol_filter = _csv_upper_set(getattr(settings, "auto_trading_allowed_symbols", ""))
    runtime_started_at = _ws_runtime_started_at()
    checks = _micro_live_config_drift_checks(check_binance_rules=check_binance_rules)
    init_db()
    with SessionLocal() as db:
        checks.append(_live_candle_depth_check(CandleRepository(db), symbols=sorted(symbol_filter)))
        lifecycle = LiveOrderLifecycleReporter(db).generate(
            days=days,
            live_only=True,
            limit=limit,
            start_at=runtime_started_at,
            symbols=sorted(symbol_filter),
            strategy_families=sorted(family_filter),
        )
    failures = _blocking_failures(checks)
    warnings = _warning_failures(checks)
    blocked_diagnostics = _blocked_intent_diagnostics(lifecycle)
    recommendations = _recommendations(blocking_failures=failures, lifecycle=lifecycle)
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "runtime_started_at": runtime_started_at.isoformat() if runtime_started_at else None,
        "family_filter": sorted(family_filter),
        "symbol_filter": sorted(symbol_filter),
        "overall_status": "FAIL" if failures else ("WATCH" if warnings else "PASS"),
        "operational_status": _operational_status(
            blocking_failures=failures,
            warning_failures=warnings,
            lifecycle=lifecycle,
        ),
        "blocking_failures": failures,
        "warning_failures": warnings,
        "checks": checks,
        "lifecycle": lifecycle,
        "blocked_intent_diagnostics": blocked_diagnostics,
        "recommendations": recommendations,
    }


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lifecycle_summary = dict((dict(payload.get("lifecycle") or {}).get("summary")) or {})
    live_intents = dict(lifecycle_summary.get("live_intents") or {})
    lines = [
        "# MICRO_LIVE Runtime Guard",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- runtime_started_at: {payload.get('runtime_started_at') or 'none'}",
        f"- family_filter: {','.join(payload.get('family_filter') or []) or 'none'}",
        f"- symbol_filter: {','.join(payload.get('symbol_filter') or []) or 'none'}",
        f"- overall_status: {payload.get('overall_status')}",
        f"- operational_status: {payload.get('operational_status')}",
        f"- blocking_failures: {len(payload.get('blocking_failures') or [])}",
        f"- warning_failures: {len(payload.get('warning_failures') or [])}",
        "",
        "## Config Drift",
        "",
    ]
    for check in payload.get("checks") or []:
        lines.append(
            f"- {check.get('name')}: {check.get('status')} {check.get('severity')} | {check.get('message')}"
        )
    lines.extend(
        [
            "",
            "## Live Order Funnel",
            "",
            f"- submissions: {lifecycle_summary.get('submission_count', 0)}",
            f"- entry_fills: {lifecycle_summary.get('entry_fill_count', 0)}",
            f"- rejected_or_error: {lifecycle_summary.get('rejected_or_error_count', 0)}",
            f"- intents: {live_intents.get('total', 0)}",
            f"- submit_ready: {live_intents.get('submit_ready', 0)}",
            f"- blocked: {live_intents.get('blocked', 0)}",
        ]
    )
    top_reasons = dict(live_intents.get("top_block_reasons") or {})
    if top_reasons:
        lines.append("- top_reasons: " + ", ".join(f"{key}={value}" for key, value in list(top_reasons.items())[:8]))
    diagnostics = list(payload.get("blocked_intent_diagnostics") or [])
    if diagnostics:
        lines.extend(["", "## Blocked Intent Diagnostics", ""])
        for item in diagnostics[:8]:
            detail = dict(item.get("detail") or {})
            detail_text = ""
            if detail:
                metrics = dict(detail.get("metrics") or {})
                metric_bits = []
                if "sample_size" in metrics:
                    metric_bits.append(f"sample={metrics.get('sample_size')}")
                if "ev" in metrics or "expectancy_r" in metrics:
                    metric_bits.append(f"ev={metrics.get('expectancy_r', metrics.get('ev'))}")
                metric_text = f" {' '.join(metric_bits)}" if metric_bits else ""
                detail_text = (
                    f" | cause={detail.get('primary_cause', '') or 'unknown'} grade={detail.get('grade', '')} "
                    f"risk={detail.get('risk_state', '')}/{detail.get('risk_reason', '')} "
                    f"deployment={detail.get('deployment_code', '')}{metric_text}"
                )
            lines.append(f"- {item.get('reason')}: {item.get('count')} | action={item.get('action')}{detail_text}")
    lines.extend(["", "## Recommendations", ""])
    recommendations = list(payload.get("recommendations") or [])
    if recommendations:
        lines.extend(f"- {item}" for item in recommendations)
    else:
        lines.append("- none")
    lines.extend(["", "## Raw Payload", "", "```json"])
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    lines.append("```")
    content = "\n".join(lines)
    if atomic:
        atomic_write_text(path, content)
    else:
        atomic_write_text(path, content)


def main() -> int:
    args = parse_args()
    payload = build_payload(
        days=max(1, int(args.days)),
        limit=max(1, int(args.limit)),
        check_binance_rules=bool(args.check_binance_rules),
    )
    if not args.no_write_report:
        generated = parse_report_generated_at(payload.get("generated_at"))
        report_dir = ROOT_DIR / args.report_dir
        report_path = report_dir / f"micro_live_runtime_guard_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        payload["report_path"] = _display_path(report_path)
        payload["latest_report_path"] = _display_path(report_dir / "latest.md")
        payload["latest_json_path"] = _display_path(report_dir / "latest.json")
        _write_report(report_path, payload, atomic=True)
        payload.update(
            write_latest_aliases(
                report_dir=report_dir,
                payload=payload,
                write_markdown_report=_write_report,
                root_dir=ROOT_DIR,
                json_default=_json_default,
            )
        )
    if not bool(args.quiet):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    if payload["overall_status"] == "FAIL" and not bool(args.no_fail_exit):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
