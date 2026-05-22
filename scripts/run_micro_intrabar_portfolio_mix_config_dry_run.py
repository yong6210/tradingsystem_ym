#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.repositories import CandleRepository
from app.db.session import SessionLocal, init_db
from app.services.report_io import atomic_write_text
from scripts.run_micro_live_runtime_guard import (
    _live_candle_depth_check,
    _live_leverage_cap_sync_report_check,
    _session_impulse_retest_exit_contract_check,
)


DEFAULT_CONFIG_PROPOSAL = ROOT_DIR / "reports/operations/micro_intrabar_portfolio_mix_live_config_proposal/latest.json"
DEFAULT_PORTFOLIO_MIX = (
    ROOT_DIR / "reports/operations/micro_intrabar_long_short_portfolio_mix_review_drop_arb/latest.json"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run the active micro intrabar portfolio mix config proposal without editing .env or enabling orders."
    )
    parser.add_argument("--config-proposal-path", default=str(DEFAULT_CONFIG_PROPOSAL))
    parser.add_argument("--portfolio-mix-review-path", default=str(DEFAULT_PORTFOLIO_MIX))
    parser.add_argument("--min-trades", type=int, default=80)
    parser.add_argument("--min-ev-r", type=float, default=0.10)
    parser.add_argument("--min-positive-year-fraction", type=float, default=0.80)
    parser.add_argument("--report-dir", default="reports/operations/micro_intrabar_portfolio_mix_config_dry_run")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--no-fail-exit", action="store_true")
    return parser.parse_args()


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


def _display_path(path: Path) -> str:
    return str(path.relative_to(ROOT_DIR) if path.is_relative_to(ROOT_DIR) else path)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
        return False
    return bool(value)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if parsed == parsed else float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _csv_upper_set(value: Any) -> set[str]:
    return {item.strip().upper() for item in str(value or "").split(",") if item.strip()}


def _env_value(value: Any) -> Any:
    text = str(value or "").strip()
    lowered = text.lower()
    if lowered in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
        return _safe_bool(text)
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def _env_settings_namespace(env: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(**{str(key).lower(): _env_value(value) for key, value in env.items()})


def _direction_contract_from_env(value: Any) -> dict[str, set[str]]:
    contract: dict[str, set[str]] = {}
    for raw_item in str(value or "").split(","):
        item = raw_item.strip()
        if not item or ":" not in item:
            continue
        symbol, raw_directions = item.split(":", 1)
        directions = {part.strip().upper() for part in raw_directions.replace("|", "/").split("/") if part.strip()}
        contract[symbol.strip().upper()] = directions
    return contract


def _proposal_authority_check(config_proposal: dict[str, Any]) -> dict[str, Any]:
    env = dict(config_proposal.get("env_proposal") or {})
    mismatches: list[str] = []
    if str(config_proposal.get("authority") or "") != "config_proposal_only_no_file_edit_no_order_submission":
        mismatches.append("authority")
    if str(config_proposal.get("live_action") or "") != "KEEP_CLOSE_ONLY":
        mismatches.append("live_action")
    if _safe_bool(config_proposal.get("live_ready")):
        mismatches.append("live_ready")
    if _safe_bool(config_proposal.get("order_submission_allowed")):
        mismatches.append("order_submission_allowed")
    if not _safe_bool(env.get("AUTO_TRADING_CLOSE_ONLY"), default=False):
        mismatches.append("AUTO_TRADING_CLOSE_ONLY")
    return {
        "name": "proposal_no_live_authority",
        "status": "PASS" if not mismatches else "FAIL",
        "severity": "blocking",
        "message": f"mismatches={','.join(mismatches) if mismatches else 'none'}",
        "mismatches": mismatches,
    }


def _proposal_state_check(config_proposal: dict[str, Any]) -> dict[str, Any]:
    blockers = list(config_proposal.get("proposal_blockers") or [])
    gaps = list(config_proposal.get("runtime_support_gaps") or [])
    state = str(config_proposal.get("recommended_state") or "")
    mismatches: list[str] = []
    if state != "CONFIG_PROPOSAL_READY_FOR_MANUAL_REVIEW":
        mismatches.append(f"state={state or 'missing'}")
    if blockers:
        mismatches.append("proposal_blockers")
    if gaps:
        mismatches.append("runtime_support_gaps")
    return {
        "name": "proposal_ready_for_manual_review",
        "status": "PASS" if not mismatches else "FAIL",
        "severity": "blocking",
        "message": (
            f"state={state}; proposal_blockers={blockers}; runtime_support_gaps={gaps}; "
            f"mismatches={','.join(mismatches) if mismatches else 'none'}"
        ),
        "mismatches": mismatches,
    }


def _portfolio_performance_check(
    portfolio_mix: dict[str, Any],
    *,
    min_trades: int,
    min_ev_r: float,
    min_positive_year_fraction: float,
) -> dict[str, Any]:
    summary = dict(dict(portfolio_mix.get("combined") or {}).get("summary") or {})
    stress = dict(dict(portfolio_mix.get("combined") or {}).get("cost_stress") or {})
    cost_x2 = dict(stress.get("cost_x2_0") or {})
    extra_005 = dict(stress.get("extra_0_05r_per_trade") or {})
    mismatches: list[str] = []
    closed = _safe_int(summary.get("closed"))
    ev_r = _safe_float(summary.get("ev_r"))
    positive_year_fraction = _safe_float(summary.get("positive_year_fraction"))
    if str(portfolio_mix.get("recommended_state") or "") != "PORTFOLIO_MIX_PAPER_WATCH":
        mismatches.append("portfolio_state")
    if closed < max(1, int(min_trades)):
        mismatches.append(f"closed_{closed}_below_{int(min_trades)}")
    if ev_r < float(min_ev_r):
        mismatches.append(f"ev_{ev_r}_below_{float(min_ev_r)}")
    if positive_year_fraction < float(min_positive_year_fraction):
        mismatches.append(f"positive_year_fraction_{positive_year_fraction}_below_{float(min_positive_year_fraction)}")
    if _safe_float(cost_x2.get("total_r")) <= 0.0:
        mismatches.append("cost_x2_total_r_non_positive")
    if _safe_float(extra_005.get("total_r")) <= 0.0:
        mismatches.append("extra_0_05r_total_r_non_positive")
    return {
        "name": "portfolio_mix_performance",
        "status": "PASS" if not mismatches else "FAIL",
        "severity": "blocking",
        "message": (
            f"closed={closed}; ev_r={ev_r}; positive_year_fraction={positive_year_fraction}; "
            f"cost_x2_total_r={_safe_float(cost_x2.get('total_r'))}; "
            f"extra_0_05r_total_r={_safe_float(extra_005.get('total_r'))}; "
            f"mismatches={','.join(mismatches) if mismatches else 'none'}"
        ),
        "mismatches": mismatches,
    }


def _env_symbol_contract_check(config_proposal: dict[str, Any], portfolio_mix: dict[str, Any]) -> dict[str, Any]:
    env = dict(config_proposal.get("env_proposal") or {})
    portfolio_symbols = {str(symbol or "").upper() for symbol in list(portfolio_mix.get("combined_symbols") or []) if str(symbol or "").strip()}
    proposal_symbols = {str(symbol or "").upper() for symbol in list(config_proposal.get("symbols") or []) if str(symbol or "").strip()}
    env_symbols = _csv_upper_set(env.get("AUTO_TRADING_MICRO_LIVE_ALLOWED_SYMBOLS"))
    env_priority = _csv_upper_set(env.get("AUTO_TRADING_MICRO_LIVE_SYMBOL_PRIORITY"))
    env_sir_symbols = _csv_upper_set(env.get("SESSION_IMPULSE_RETEST_ALLOWED_SYMBOLS"))
    env_directions = _direction_contract_from_env(env.get("AUTO_TRADING_MICRO_LIVE_DIRECTION_CONTRACT"))
    proposal_directions = {
        str(symbol or "").upper(): {str(direction or "").upper() for direction in list(values or [])}
        for symbol, values in dict(config_proposal.get("direction_contract") or {}).items()
    }
    mismatches: list[str] = []
    for label, symbols in (
        ("proposal_symbols", proposal_symbols),
        ("env_symbols", env_symbols),
        ("env_priority", env_priority),
        ("env_sir_symbols", env_sir_symbols),
    ):
        if symbols != portfolio_symbols:
            mismatches.append(label)
    if set(env_directions) != portfolio_symbols:
        mismatches.append("env_direction_symbols")
    if env_directions != proposal_directions:
        mismatches.append("env_direction_values")
    return {
        "name": "env_symbol_direction_contract",
        "status": "PASS" if not mismatches else "FAIL",
        "severity": "blocking",
        "message": (
            f"portfolio_symbols={len(portfolio_symbols)}; env_symbols={len(env_symbols)}; "
            f"direction_symbols={len(env_directions)}; mismatches={','.join(mismatches) if mismatches else 'none'}"
        ),
        "mismatches": mismatches,
    }


def _candle_depth_check(candle_repo: Any | None, symbols: list[str]) -> dict[str, Any]:
    if candle_repo is None:
        return {
            "name": "candidate_live_candle_depth",
            "status": "SKIP",
            "severity": "warning",
            "message": "candle_repo_unavailable_in_unit_context",
        }
    check = _live_candle_depth_check(candle_repo, symbols=symbols)
    check["name"] = "candidate_live_candle_depth"
    return check


def _leverage_sync_warning_check() -> dict[str, Any]:
    check = _live_leverage_cap_sync_report_check()
    check = dict(check)
    check["name"] = "candidate_leverage_cap_sync_report"
    check["severity"] = "warning"
    return check


def build_payload(
    *,
    config_proposal_path: Path,
    portfolio_mix_review_path: Path,
    min_trades: int = 80,
    min_ev_r: float = 0.10,
    min_positive_year_fraction: float = 0.80,
    generated_at: datetime | None = None,
    candle_repo: Any | None = None,
    include_leverage_check: bool = True,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    config_proposal = _load_json(config_proposal_path)
    portfolio_mix = _load_json(portfolio_mix_review_path)
    env = dict(config_proposal.get("env_proposal") or {})
    settings = _env_settings_namespace(env)
    symbols = [str(symbol or "").upper() for symbol in list(config_proposal.get("symbols") or []) if str(symbol or "").strip()]
    checks = [
        _proposal_authority_check(config_proposal),
        _proposal_state_check(config_proposal),
        _portfolio_performance_check(
            portfolio_mix,
            min_trades=int(min_trades),
            min_ev_r=float(min_ev_r),
            min_positive_year_fraction=float(min_positive_year_fraction),
        ),
        _env_symbol_contract_check(config_proposal, portfolio_mix),
        _session_impulse_retest_exit_contract_check(settings),
        _candle_depth_check(candle_repo, symbols),
    ]
    if include_leverage_check:
        checks.append(_leverage_sync_warning_check())
    blocking_failures = [
        dict(check)
        for check in checks
        if str(check.get("severity") or "").lower() == "blocking" and str(check.get("status") or "").upper() != "PASS"
    ]
    warning_failures = [
        dict(check)
        for check in checks
        if str(check.get("severity") or "").lower() != "blocking" and str(check.get("status") or "").upper() not in {"PASS", "SKIP"}
    ]
    recommended_state = "DRY_RUN_PASS_NO_LIVE_AUTHORITY" if not blocking_failures else "DRY_RUN_BLOCKED"
    return {
        "schema_version": "micro_intrabar_portfolio_mix_config_dry_run_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "dry_run_only_no_file_edit_no_order_submission",
        "config_proposal_path": _display_path(config_proposal_path),
        "portfolio_mix_review_path": _display_path(portfolio_mix_review_path),
        "recommended_state": recommended_state,
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": False,
        "order_submission_allowed": False,
        "symbol_count": len(symbols),
        "symbols": symbols,
        "exit_policy_name": str(config_proposal.get("exit_policy_name") or ""),
        "blocking_failures": blocking_failures,
        "warning_failures": warning_failures,
        "checks": checks,
        "operator_summary": {
            "action": (
                "Proposal checks pass in dry-run only; do not submit orders until it is applied in a controlled staging/live promotion path."
                if not blocking_failures
                else "Fix blocking dry-run failures before considering any config application."
            ),
            "order_submission_allowed": False,
        },
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Micro Intrabar Portfolio Mix Config Dry Run",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- authority: {payload.get('authority')}",
        f"- recommended_state: {payload.get('recommended_state')}",
        f"- live_action: {payload.get('live_action')}",
        f"- order_submission_allowed: {payload.get('order_submission_allowed')}",
        f"- symbols: {payload.get('symbol_count')}",
        f"- exit_policy_name: {payload.get('exit_policy_name')}",
        f"- blocking_failures: {len(payload.get('blocking_failures') or [])}",
        f"- warning_failures: {len(payload.get('warning_failures') or [])}",
        "",
        "## Checks",
        "",
    ]
    for check in list(payload.get("checks") or []):
        lines.append(f"- {check.get('name')}: {check.get('status')} {check.get('severity')} | {check.get('message')}")
    lines.extend(["", "This dry run does not edit `.env`, submit orders, or enable live routing."])
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    generated_at = datetime.now(UTC)
    init_db()
    with SessionLocal() as db:
        payload = build_payload(
            config_proposal_path=_resolve_path(args.config_proposal_path),
            portfolio_mix_review_path=_resolve_path(args.portfolio_mix_review_path),
            min_trades=int(args.min_trades),
            min_ev_r=float(args.min_ev_r),
            min_positive_year_fraction=float(args.min_positive_year_fraction),
            generated_at=generated_at,
            candle_repo=CandleRepository(db),
            include_leverage_check=True,
        )
    if args.write_report:
        report_dir = _resolve_path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = generated_at.strftime("%Y%m%dT%H%M%S%fZ")
        json_path = report_dir / f"micro_intrabar_portfolio_mix_config_dry_run_{stamp}.json"
        md_path = report_dir / f"micro_intrabar_portfolio_mix_config_dry_run_{stamp}.md"
        payload["report_path"] = _display_path(json_path)
        payload["latest_report_path"] = _display_path(report_dir / "latest.json")
        atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(md_path, _render_markdown(payload))
        atomic_write_text(report_dir / "latest.json", json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(report_dir / "latest.md", _render_markdown(payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if payload["recommended_state"] != "DRY_RUN_PASS_NO_LIVE_AUTHORITY" and not bool(args.no_fail_exit):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
