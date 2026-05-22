#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text


DEFAULT_CONTRACT_PATH = ROOT_DIR / "reports/operations/micro_intrabar_paper_candidate_contract/latest.json"
DEFAULT_WATCH_REVIEW_PATH = ROOT_DIR / "reports/operations/micro_intrabar_paper_candidate_review/latest.json"
DEFAULT_REPLAY_REVIEW_PATH = ROOT_DIR / "reports/operations/micro_intrabar_candidate_replay_review/latest.json"
DEFAULT_EXPANSION_REVIEW_PATH = ROOT_DIR / "reports/operations/micro_intrabar_candidate_expansion_review/latest.json"
DEFAULT_EXPANSION_SHADOW_REVIEW_PATH = ROOT_DIR / "reports/operations/micro_intrabar_expansion_shadow_review/latest.json"
DEFAULT_EXIT_POLICY_UPGRADE_REVIEW_PATH = ROOT_DIR / "reports/operations/micro_intrabar_exit_policy_upgrade_review/latest.json"
DEFAULT_FILTER_UPGRADE_REVIEW_PATH = ROOT_DIR / "reports/operations/micro_intrabar_filter_upgrade_review/latest.json"
DEFAULT_PORTFOLIO_MIX_REVIEW_PATH = (
    ROOT_DIR / "reports/operations/micro_intrabar_long_short_portfolio_mix_review_drop_arb/latest.json"
)
DEFAULT_CONFIG_PROPOSAL_PATH = ROOT_DIR / "reports/operations/micro_intrabar_portfolio_mix_live_config_proposal/latest.json"
DEFAULT_CONFIG_DRY_RUN_PATH = ROOT_DIR / "reports/operations/micro_intrabar_portfolio_mix_config_dry_run/latest.json"
DEFAULT_RUNTIME_GUARD_PATH = ROOT_DIR / "reports/operations/micro_live_runtime_guard/latest.json"
DEFAULT_SAFETY_URL = "http://127.0.0.1:8000/execution/safety-state"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a single governance decision for the micro intrabar paper candidate.")
    parser.add_argument("--contract-path", default=str(DEFAULT_CONTRACT_PATH))
    parser.add_argument("--watch-review-path", default=str(DEFAULT_WATCH_REVIEW_PATH))
    parser.add_argument("--replay-review-path", default=str(DEFAULT_REPLAY_REVIEW_PATH))
    parser.add_argument("--expansion-review-path", default=str(DEFAULT_EXPANSION_REVIEW_PATH))
    parser.add_argument("--expansion-shadow-review-path", default=str(DEFAULT_EXPANSION_SHADOW_REVIEW_PATH))
    parser.add_argument("--exit-policy-upgrade-review-path", default=str(DEFAULT_EXIT_POLICY_UPGRADE_REVIEW_PATH))
    parser.add_argument("--filter-upgrade-review-path", default=str(DEFAULT_FILTER_UPGRADE_REVIEW_PATH))
    parser.add_argument("--portfolio-mix-review-path", default=str(DEFAULT_PORTFOLIO_MIX_REVIEW_PATH))
    parser.add_argument("--config-proposal-path", default=str(DEFAULT_CONFIG_PROPOSAL_PATH))
    parser.add_argument("--config-dry-run-path", default=str(DEFAULT_CONFIG_DRY_RUN_PATH))
    parser.add_argument("--runtime-guard-path", default=str(DEFAULT_RUNTIME_GUARD_PATH))
    parser.add_argument("--safety-url", default=DEFAULT_SAFETY_URL)
    parser.add_argument("--skip-safety-fetch", action="store_true")
    parser.add_argument("--report-dir", default="reports/operations/micro_intrabar_candidate_governance")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


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
        return default
    return parsed if parsed == parsed else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _report_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def _fetch_json(url: str, *, timeout_seconds: float = 10.0) -> tuple[dict[str, Any] | None, str | None]:
    request = Request(url=url, headers={"Accept": "application/json"}, method="GET")  # noqa: S310
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8")), None
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return None, str(exc)


def _safety_assessment(safety_payload: dict[str, Any] | None, *, error: str | None = None) -> dict[str, Any]:
    hard_blockers: list[str] = []
    warnings: list[str] = []
    if error or safety_payload is None:
        hard_blockers.append("safety_state_unavailable")
        return {
            "available": False,
            "hard_blockers": hard_blockers,
            "warnings": warnings,
            "error": error,
        }
    new_entry_allowed = _safe_bool(safety_payload.get("new_entry_allowed"))
    config_close_only_active = _safe_bool(safety_payload.get("config_close_only_active"))
    close_only_active = _safe_bool(safety_payload.get("close_only_active"))
    live_protection = dict(safety_payload.get("live_account_protection") or {})
    open_positions = _safe_int(live_protection.get("open_position_count"))
    open_orders = _safe_int(live_protection.get("open_order_count"))
    if new_entry_allowed:
        hard_blockers.append("new_entries_unexpectedly_allowed")
    if not config_close_only_active:
        warnings.append("static_close_only_not_active")
    if open_positions > 0:
        warnings.append("open_positions_present")
    if open_orders > 0:
        warnings.append("open_orders_present")
    return {
        "available": True,
        "hard_blockers": hard_blockers,
        "warnings": warnings,
        "new_entry_allowed": new_entry_allowed,
        "blocking_reason_code": safety_payload.get("blocking_reason_code"),
        "config_close_only_active": config_close_only_active,
        "close_only_active": close_only_active,
        "open_position_count": open_positions,
        "open_order_count": open_orders,
    }


def _contract_assessment(contract: dict[str, Any]) -> dict[str, Any]:
    paper_contract = dict(contract.get("paper_contract") or {})
    hard_blockers: list[str] = []
    warnings: list[str] = []
    if str(contract.get("authority") or "") != "paper_only_no_live_authority_change":
        hard_blockers.append("contract_authority_not_paper_only")
    if str(contract.get("live_action") or "") != "KEEP_CLOSE_ONLY":
        hard_blockers.append("contract_live_action_not_close_only")
    if _safe_bool(contract.get("live_ready")):
        hard_blockers.append("contract_live_ready_true")
    if _safe_float(paper_contract.get("live_risk_r")) != 0.0:
        hard_blockers.append("contract_live_risk_not_zero")
    if _safe_int(dict(contract.get("candidate") or {}).get("symbol_count")) < 8:
        warnings.append("candidate_symbol_count_below_live_review_floor")
    return {
        "hard_blockers": hard_blockers,
        "warnings": warnings,
        "policy_name": paper_contract.get("policy_name"),
        "symbols": paper_contract.get("symbols") or [],
        "live_risk_r": paper_contract.get("live_risk_r"),
    }


def _runtime_guard_assessment(
    runtime_guard: dict[str, Any] | None,
    *,
    error: str | None = None,
    required: bool = False,
) -> dict[str, Any]:
    if runtime_guard is None:
        return {
            "available": False,
            "error": error,
            "hard_blockers": ["runtime_guard_unavailable"] if required else [],
            "overall_status": None,
            "operational_status": None,
            "blocking_failures": [],
        }
    overall_status = str(runtime_guard.get("overall_status") or "").upper()
    operational_status = str(runtime_guard.get("operational_status") or "").upper()
    blocking_failures = [dict(item) for item in list(runtime_guard.get("blocking_failures") or []) if isinstance(item, dict)]
    hard_blockers: list[str] = []
    if overall_status != "PASS" or operational_status not in {"PASS", "OK"} or blocking_failures:
        hard_blockers.append("runtime_guard_not_passing")
    return {
        "available": True,
        "error": None,
        "hard_blockers": hard_blockers,
        "overall_status": overall_status,
        "operational_status": operational_status,
        "blocking_failure_count": len(blocking_failures),
        "blocking_failures": [
            {
                "name": item.get("name"),
                "message": item.get("message"),
            }
            for item in blocking_failures[:8]
        ],
    }


def _portfolio_mix_assessment(
    portfolio_mix: dict[str, Any] | None,
    *,
    error: str | None = None,
    required: bool = False,
) -> dict[str, Any]:
    if portfolio_mix is None:
        return {
            "available": False,
            "error": error,
            "hard_blockers": ["portfolio_mix_review_unavailable"] if required else [],
            "warnings": [],
        }
    hard_blockers: list[str] = []
    warnings: list[str] = []
    recommended_state = str(portfolio_mix.get("recommended_state") or "")
    if recommended_state != "PORTFOLIO_MIX_PAPER_WATCH":
        hard_blockers.append("portfolio_mix_not_supportive")
    if str(portfolio_mix.get("live_action") or "") != "KEEP_CLOSE_ONLY":
        hard_blockers.append("portfolio_mix_live_action_not_close_only")
    if _safe_bool(portfolio_mix.get("live_ready")):
        hard_blockers.append("portfolio_mix_live_ready_true")
    if _safe_bool(portfolio_mix.get("order_submission_allowed")):
        hard_blockers.append("portfolio_mix_order_submission_allowed")
    if _safe_int(portfolio_mix.get("combined_symbol_count")) < 4:
        warnings.append("portfolio_mix_symbol_count_thin")
    summary = dict(dict(portfolio_mix.get("combined") or {}).get("summary") or {})
    cost_stress = dict(dict(portfolio_mix.get("combined") or {}).get("cost_stress") or {})
    recommended_scenarios = [
        dict(item)
        for item in list(portfolio_mix.get("recommended_portfolio_replay_scenarios") or [])
        if isinstance(item, dict)
    ]
    return {
        "available": True,
        "error": None,
        "hard_blockers": hard_blockers,
        "warnings": warnings,
        "recommended_state": recommended_state,
        "reasons": portfolio_mix.get("reasons") or [],
        "live_action": portfolio_mix.get("live_action"),
        "live_ready": portfolio_mix.get("live_ready"),
        "order_submission_allowed": portfolio_mix.get("order_submission_allowed"),
        "combined_symbol_count": portfolio_mix.get("combined_symbol_count"),
        "combined_symbols": portfolio_mix.get("combined_symbols") or [],
        "summary": {
            "closed": summary.get("closed"),
            "total_r": summary.get("total_r"),
            "ev_r": summary.get("ev_r"),
            "max_dd_r": summary.get("max_dd_r"),
            "positive_year_fraction": summary.get("positive_year_fraction"),
        },
        "cost_stress": {
            "extra_0_05r_per_trade_total_r": dict(cost_stress.get("extra_0_05r_per_trade") or {}).get("total_r"),
            "cost_x2_total_r": dict(cost_stress.get("cost_x2_0") or {}).get("total_r"),
        },
        "recommended_portfolio_replay_scenarios": recommended_scenarios,
        "operator_summary": portfolio_mix.get("operator_summary") or {},
    }


def _config_proposal_assessment(
    config_proposal: dict[str, Any] | None,
    *,
    error: str | None = None,
    required: bool = False,
) -> dict[str, Any]:
    if config_proposal is None:
        return {
            "available": False,
            "error": error,
            "hard_blockers": ["config_proposal_unavailable"] if required else [],
            "warnings": [],
        }
    hard_blockers: list[str] = []
    recommended_state = str(config_proposal.get("recommended_state") or "")
    if recommended_state != "CONFIG_PROPOSAL_READY_FOR_MANUAL_REVIEW":
        hard_blockers.append("live_config_proposal_not_ready")
    if str(config_proposal.get("live_action") or "") != "KEEP_CLOSE_ONLY":
        hard_blockers.append("config_proposal_live_action_not_close_only")
    if _safe_bool(config_proposal.get("live_ready")) or _safe_bool(config_proposal.get("order_submission_allowed")):
        hard_blockers.append("config_proposal_has_live_authority")
    return {
        "available": True,
        "error": None,
        "hard_blockers": hard_blockers,
        "warnings": [],
        "recommended_state": recommended_state,
        "proposal_blockers": config_proposal.get("proposal_blockers") or [],
        "runtime_support_gaps": config_proposal.get("runtime_support_gaps") or [],
        "symbol_count": config_proposal.get("symbol_count"),
        "exit_policy_name": config_proposal.get("exit_policy_name"),
        "recommended_max_concurrent_positions": config_proposal.get("recommended_max_concurrent_positions"),
        "order_submission_allowed": config_proposal.get("order_submission_allowed"),
    }


def _config_dry_run_assessment(
    config_dry_run: dict[str, Any] | None,
    *,
    error: str | None = None,
    required: bool = False,
) -> dict[str, Any]:
    if config_dry_run is None:
        return {
            "available": False,
            "error": error,
            "hard_blockers": ["config_dry_run_unavailable"] if required else [],
            "warnings": [],
        }
    hard_blockers: list[str] = []
    warnings: list[str] = []
    recommended_state = str(config_dry_run.get("recommended_state") or "")
    blocking_failures = [
        dict(item) for item in list(config_dry_run.get("blocking_failures") or []) if isinstance(item, dict)
    ]
    warning_failures = [
        dict(item) for item in list(config_dry_run.get("warning_failures") or []) if isinstance(item, dict)
    ]
    checks = [dict(item) for item in list(config_dry_run.get("checks") or []) if isinstance(item, dict)]
    if recommended_state != "DRY_RUN_PASS_NO_LIVE_AUTHORITY" or blocking_failures:
        hard_blockers.append("config_dry_run_not_passing")
    if str(config_dry_run.get("live_action") or "") != "KEEP_CLOSE_ONLY":
        hard_blockers.append("config_dry_run_live_action_not_close_only")
    if _safe_bool(config_dry_run.get("live_ready")) or _safe_bool(config_dry_run.get("order_submission_allowed")):
        hard_blockers.append("config_dry_run_has_live_authority")
    if warning_failures:
        warnings.append("config_dry_run_warning_failures_present")
    return {
        "available": True,
        "error": None,
        "hard_blockers": hard_blockers,
        "warnings": warnings,
        "recommended_state": recommended_state,
        "live_action": config_dry_run.get("live_action"),
        "live_ready": config_dry_run.get("live_ready"),
        "order_submission_allowed": config_dry_run.get("order_submission_allowed"),
        "symbol_count": config_dry_run.get("symbol_count"),
        "exit_policy_name": config_dry_run.get("exit_policy_name"),
        "blocking_failure_count": len(blocking_failures),
        "warning_failure_count": len(warning_failures),
        "blocking_failures": [
            {
                "name": item.get("name"),
                "message": item.get("message"),
            }
            for item in blocking_failures[:8]
        ],
        "warning_failures": [
            {
                "name": item.get("name"),
                "message": item.get("message"),
            }
            for item in warning_failures[:8]
        ],
        "checks": [
            {
                "name": item.get("name"),
                "status": item.get("status"),
                "severity": item.get("severity"),
                "message": item.get("message"),
            }
            for item in checks
        ],
    }


def _summarize_expansion_report_reviews(expansion_review: dict[str, Any] | None) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for item in list((expansion_review or {}).get("report_reviews") or []):
        if not isinstance(item, dict):
            continue
        scope = dict(item.get("scope") or {})
        matched = dict(item.get("matched_summary") or {})
        gate = dict(item.get("expansion_gate") or {})
        cost_stress = dict(item.get("cost_stress") or {})
        stress_summary: dict[str, dict[str, Any]] = {}
        for key in ("extra_0_05r_per_trade", "cost_x2_0"):
            stress = dict(cost_stress.get(key) or {})
            if not stress:
                continue
            stress_summary[key] = {
                "closed": stress.get("closed"),
                "total_r": stress.get("total_r"),
                "ev_r": stress.get("ev_r"),
                "profit_to_dd": stress.get("profit_to_dd"),
            }
        summaries.append(
            {
                "path": item.get("path"),
                "days": scope.get("days"),
                "symbol_count": scope.get("symbol_count"),
                "closed": matched.get("closed"),
                "total_r": matched.get("total_r"),
                "ev_r": matched.get("ev_r"),
                "win_rate": matched.get("win_rate"),
                "positive_symbol_fraction": matched.get("positive_symbol_fraction"),
                "positive_year_fraction": matched.get("positive_year_fraction"),
                "expansion_gate": {
                    "state": gate.get("state"),
                    "reasons": gate.get("reasons") or [],
                    "warnings": gate.get("warnings") or [],
                },
                "cost_stress": stress_summary,
            }
        )
    return summaries


def _summarize_expansion_symbols(expansion_review: dict[str, Any] | None, *, limit: int = 12) -> list[dict[str, Any]]:
    symbols = [item for item in list((expansion_review or {}).get("symbol_rollup") or []) if isinstance(item, dict)]
    symbols = sorted(
        symbols,
        key=lambda item: (
            _safe_float(item.get("positive_report_fraction")),
            _safe_float(item.get("best_total_r")),
            _safe_float(item.get("best_ev_r")),
        ),
        reverse=True,
    )
    return [
        {
            "symbol": item.get("symbol"),
            "in_current_contract": item.get("in_current_contract"),
            "best_days": item.get("best_days"),
            "best_total_r": item.get("best_total_r"),
            "best_ev_r": item.get("best_ev_r"),
            "positive_report_fraction": item.get("positive_report_fraction"),
        }
        for item in symbols[:limit]
    ]


def _decision(
    *,
    contract_assessment: dict[str, Any],
    watch_review: dict[str, Any],
    replay_review: dict[str, Any],
    expansion_review: dict[str, Any] | None,
    expansion_shadow_review: dict[str, Any] | None,
    exit_policy_upgrade_review: dict[str, Any] | None,
    filter_upgrade_review: dict[str, Any] | None,
    portfolio_mix_review: dict[str, Any] | None,
    config_proposal_review: dict[str, Any] | None,
    config_dry_run_review: dict[str, Any] | None,
    runtime_guard_review: dict[str, Any] | None,
    safety_assessment: dict[str, Any],
    portfolio_mix_required: bool = False,
    config_proposal_required: bool = False,
    config_dry_run_required: bool = False,
    runtime_guard_required: bool = False,
) -> tuple[str, list[str]]:
    hard_blockers: list[str] = []
    hard_blockers.extend(str(item) for item in list(contract_assessment.get("hard_blockers") or []))
    portfolio_mix_status = _portfolio_mix_assessment(portfolio_mix_review, required=portfolio_mix_required)
    config_proposal_status = _config_proposal_assessment(
        config_proposal_review,
        required=config_proposal_required,
    )
    config_dry_run_status = _config_dry_run_assessment(config_dry_run_review, required=config_dry_run_required)
    runtime_guard_status = _runtime_guard_assessment(runtime_guard_review, required=runtime_guard_required)
    runtime_active_supported = _runtime_active_supported(
        safety_assessment=safety_assessment,
        portfolio_mix_status=portfolio_mix_status,
        config_proposal_status=config_proposal_status,
        config_dry_run_status=config_dry_run_status,
        runtime_guard_status=runtime_guard_status,
    )
    safety_blockers = [str(item) for item in list(safety_assessment.get("hard_blockers") or [])]
    if runtime_active_supported:
        safety_blockers = [item for item in safety_blockers if item != "new_entries_unexpectedly_allowed"]
    hard_blockers.extend(safety_blockers)
    hard_blockers.extend(
        str(item)
        for item in list(portfolio_mix_status.get("hard_blockers") or [])
    )
    hard_blockers.extend(
        str(item)
        for item in list(config_proposal_status.get("hard_blockers") or [])
    )
    hard_blockers.extend(
        str(item)
        for item in list(config_dry_run_status.get("hard_blockers") or [])
    )
    hard_blockers.extend(
        str(item)
        for item in list(runtime_guard_status.get("hard_blockers") or [])
    )
    replay_state = str(replay_review.get("recommended_state") or "")
    watch_state = str(watch_review.get("recommended_state") or "")
    expansion_state = str((expansion_review or {}).get("recommended_state") or "")
    expansion_shadow_state = str((expansion_shadow_review or {}).get("recommended_state") or "")
    exit_policy_upgrade_state = str((exit_policy_upgrade_review or {}).get("recommended_state") or "")
    filter_upgrade_state = str((filter_upgrade_review or {}).get("recommended_state") or "")
    if replay_state != "REPLAY_SUPPORTS_PAPER_ONLY_WATCH":
        hard_blockers.append("replay_review_not_supportive")
    if exit_policy_upgrade_review is not None and exit_policy_upgrade_state != "UPGRADE_SUPPORTED_FOR_PAPER_ONLY":
        hard_blockers.append("exit_policy_upgrade_review_not_supportive")
    if filter_upgrade_review is not None and filter_upgrade_state != "UPGRADE_SUPPORTED_FOR_PAPER_ONLY":
        hard_blockers.append("filter_upgrade_review_not_supportive")
    if expansion_state == "EXPANSION_REVIEW_READY":
        hard_blockers.append("expansion_review_requires_manual_governance_before_live")
    if expansion_shadow_state == "PAPER_SAMPLE_REVIEW_READY":
        hard_blockers.append("expansion_shadow_sample_ready_requires_manual_review")
    if hard_blockers:
        return "GOVERNANCE_HOLD", hard_blockers
    if runtime_active_supported:
        return "RUNTIME_ACTIVE_OBSERVE", ["runtime_active_with_passing_governance_surfaces"]
    if watch_state == "PAPER_SAMPLE_REVIEW_READY":
        return "PAPER_SAMPLE_REVIEW_READY_NO_LIVE", ["paper_sample_gate_met_but_live_still_disabled"]
    return "CONTINUE_PAPER_WATCH_AND_REPLAY", ["watch_sample_not_ready_live_disabled"]


def _runtime_active_supported(
    *,
    safety_assessment: dict[str, Any],
    portfolio_mix_status: dict[str, Any],
    config_proposal_status: dict[str, Any],
    config_dry_run_status: dict[str, Any],
    runtime_guard_status: dict[str, Any],
) -> bool:
    return (
        _safe_bool(safety_assessment.get("new_entry_allowed"))
        and not str(safety_assessment.get("blocking_reason_code") or "").strip()
        and bool(portfolio_mix_status.get("available"))
        and bool(config_proposal_status.get("available"))
        and bool(config_dry_run_status.get("available"))
        and bool(runtime_guard_status.get("available"))
        and not list(portfolio_mix_status.get("hard_blockers") or [])
        and not list(config_proposal_status.get("hard_blockers") or [])
        and not list(config_dry_run_status.get("hard_blockers") or [])
        and not list(runtime_guard_status.get("hard_blockers") or [])
    )


def _operator_action(state: str) -> str:
    if state == "RUNTIME_ACTIVE_OBSERVE":
        return "Runtime is active and supporting governance surfaces pass; observe live flow and protection state."
    if state == "CONTINUE_PAPER_WATCH_AND_REPLAY":
        return "Keep live entries disabled; continue paper watch and replay review."
    if state == "PAPER_SAMPLE_REVIEW_READY_NO_LIVE":
        return "Paper sample gate is ready, but live entries remain disabled until manual promotion review."
    return "Hold and inspect blockers before any further promotion."


def build_payload(
    contract_path: Path,
    watch_review_path: Path,
    replay_review_path: Path,
    expansion_review_path: Path | None = None,
    expansion_shadow_review_path: Path | None = None,
    exit_policy_upgrade_review_path: Path | None = None,
    filter_upgrade_review_path: Path | None = None,
    portfolio_mix_review_path: Path | None = None,
    config_proposal_path: Path | None = None,
    runtime_guard_path: Path | None = None,
    config_dry_run_path: Path | None = None,
    *,
    safety_payload: dict[str, Any] | None = None,
    safety_error: str | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    contract = _load_json(contract_path)
    watch_review = _load_json(watch_review_path)
    replay_review = _load_json(replay_review_path)
    expansion_review: dict[str, Any] | None = None
    expansion_error: str | None = None
    if expansion_review_path is not None:
        try:
            expansion_review = _load_json(expansion_review_path)
        except (OSError, json.JSONDecodeError) as exc:
            expansion_error = str(exc)
    expansion_shadow_review: dict[str, Any] | None = None
    expansion_shadow_error: str | None = None
    if expansion_shadow_review_path is not None:
        try:
            expansion_shadow_review = _load_json(expansion_shadow_review_path)
        except (OSError, json.JSONDecodeError) as exc:
            expansion_shadow_error = str(exc)
    exit_policy_upgrade_review: dict[str, Any] | None = None
    exit_policy_upgrade_error: str | None = None
    if exit_policy_upgrade_review_path is not None:
        try:
            exit_policy_upgrade_review = _load_json(exit_policy_upgrade_review_path)
        except (OSError, json.JSONDecodeError) as exc:
            exit_policy_upgrade_error = str(exc)
    filter_upgrade_review: dict[str, Any] | None = None
    filter_upgrade_error: str | None = None
    if filter_upgrade_review_path is not None:
        try:
            filter_upgrade_review = _load_json(filter_upgrade_review_path)
        except (OSError, json.JSONDecodeError) as exc:
            filter_upgrade_error = str(exc)
    portfolio_mix_review: dict[str, Any] | None = None
    portfolio_mix_error: str | None = None
    if portfolio_mix_review_path is not None:
        try:
            portfolio_mix_review = _load_json(portfolio_mix_review_path)
        except (OSError, json.JSONDecodeError) as exc:
            portfolio_mix_error = str(exc)
    config_proposal_review: dict[str, Any] | None = None
    config_proposal_error: str | None = None
    if config_proposal_path is not None:
        try:
            config_proposal_review = _load_json(config_proposal_path)
        except (OSError, json.JSONDecodeError) as exc:
            config_proposal_error = str(exc)
    config_dry_run_review: dict[str, Any] | None = None
    config_dry_run_error: str | None = None
    if config_dry_run_path is not None:
        try:
            config_dry_run_review = _load_json(config_dry_run_path)
        except (OSError, json.JSONDecodeError) as exc:
            config_dry_run_error = str(exc)
    runtime_guard_review: dict[str, Any] | None = None
    runtime_guard_error: str | None = None
    if runtime_guard_path is not None:
        try:
            runtime_guard_review = _load_json(runtime_guard_path)
        except (OSError, json.JSONDecodeError) as exc:
            runtime_guard_error = str(exc)
    contract_status = _contract_assessment(contract)
    safety_status = _safety_assessment(safety_payload, error=safety_error)
    portfolio_mix_status = _portfolio_mix_assessment(
        portfolio_mix_review,
        error=portfolio_mix_error,
        required=portfolio_mix_review_path is not None,
    )
    config_proposal_status = _config_proposal_assessment(
        config_proposal_review,
        error=config_proposal_error,
        required=config_proposal_path is not None,
    )
    config_dry_run_status = _config_dry_run_assessment(
        config_dry_run_review,
        error=config_dry_run_error,
        required=config_dry_run_path is not None,
    )
    runtime_guard_status = _runtime_guard_assessment(
        runtime_guard_review,
        error=runtime_guard_error,
        required=runtime_guard_path is not None,
    )
    state, reasons = _decision(
        contract_assessment=contract_status,
        watch_review=watch_review,
        replay_review=replay_review,
        expansion_review=expansion_review,
        expansion_shadow_review=expansion_shadow_review,
        exit_policy_upgrade_review=exit_policy_upgrade_review,
        filter_upgrade_review=filter_upgrade_review,
        portfolio_mix_review=portfolio_mix_review,
        config_proposal_review=config_proposal_review,
        config_dry_run_review=config_dry_run_review,
        runtime_guard_review=runtime_guard_review,
        portfolio_mix_required=portfolio_mix_review_path is not None,
        config_proposal_required=config_proposal_path is not None,
        config_dry_run_required=config_dry_run_path is not None,
        runtime_guard_required=runtime_guard_path is not None,
        safety_assessment=safety_status,
    )
    runtime_active_supported = _runtime_active_supported(
        safety_assessment=safety_status,
        portfolio_mix_status=portfolio_mix_status,
        config_proposal_status=config_proposal_status,
        config_dry_run_status=config_dry_run_status,
        runtime_guard_status=runtime_guard_status,
    )
    runtime_entries_allowed = state == "RUNTIME_ACTIVE_OBSERVE" and runtime_active_supported
    safety_status = dict(safety_status)
    safety_status["runtime_active_expected"] = runtime_entries_allowed
    if runtime_entries_allowed:
        safety_status["hard_blockers"] = [
            item for item in list(safety_status.get("hard_blockers") or []) if item != "new_entries_unexpectedly_allowed"
        ]
    return {
        "schema_version": "micro_intrabar_candidate_governance_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "governance_only_no_order_submission",
        "contract_path": str(contract_path.relative_to(ROOT_DIR) if contract_path.is_relative_to(ROOT_DIR) else contract_path),
        "watch_review_path": str(watch_review_path.relative_to(ROOT_DIR) if watch_review_path.is_relative_to(ROOT_DIR) else watch_review_path),
        "replay_review_path": str(replay_review_path.relative_to(ROOT_DIR) if replay_review_path.is_relative_to(ROOT_DIR) else replay_review_path),
        "expansion_review_path": (
            str(expansion_review_path.relative_to(ROOT_DIR) if expansion_review_path.is_relative_to(ROOT_DIR) else expansion_review_path)
            if expansion_review_path is not None
            else None
        ),
        "expansion_shadow_review_path": (
            str(
                expansion_shadow_review_path.relative_to(ROOT_DIR)
                if expansion_shadow_review_path.is_relative_to(ROOT_DIR)
                else expansion_shadow_review_path
            )
            if expansion_shadow_review_path is not None
            else None
        ),
        "exit_policy_upgrade_review_path": (
            str(
                exit_policy_upgrade_review_path.relative_to(ROOT_DIR)
                if exit_policy_upgrade_review_path.is_relative_to(ROOT_DIR)
                else exit_policy_upgrade_review_path
            )
            if exit_policy_upgrade_review_path is not None
            else None
        ),
        "filter_upgrade_review_path": (
            str(
                filter_upgrade_review_path.relative_to(ROOT_DIR)
                if filter_upgrade_review_path.is_relative_to(ROOT_DIR)
                else filter_upgrade_review_path
            )
            if filter_upgrade_review_path is not None
            else None
        ),
        "portfolio_mix_review_path": (
            str(
                portfolio_mix_review_path.relative_to(ROOT_DIR)
                if portfolio_mix_review_path.is_relative_to(ROOT_DIR)
                else portfolio_mix_review_path
            )
            if portfolio_mix_review_path is not None
            else None
        ),
        "config_proposal_path": (
            str(config_proposal_path.relative_to(ROOT_DIR) if config_proposal_path.is_relative_to(ROOT_DIR) else config_proposal_path)
            if config_proposal_path is not None
            else None
        ),
        "config_dry_run_path": (
            str(config_dry_run_path.relative_to(ROOT_DIR) if config_dry_run_path.is_relative_to(ROOT_DIR) else config_dry_run_path)
            if config_dry_run_path is not None
            else None
        ),
        "runtime_guard_path": (
            str(runtime_guard_path.relative_to(ROOT_DIR) if runtime_guard_path.is_relative_to(ROOT_DIR) else runtime_guard_path)
            if runtime_guard_path is not None
            else None
        ),
        "recommended_state": state,
        "reasons": reasons,
        "live_action": "OBSERVE_ACTIVE_RUNTIME" if runtime_entries_allowed else "KEEP_CLOSE_ONLY",
        "live_ready": runtime_entries_allowed,
        "runtime_entries_allowed": runtime_entries_allowed,
        "governance_order_submission_allowed": False,
        "contract_assessment": contract_status,
        "watch_assessment": {
            "recommended_state": watch_review.get("recommended_state"),
            "blockers": watch_review.get("blockers") or [],
            "unique_candidate_summary": watch_review.get("unique_candidate_summary") or {},
            "base_signal_summary": watch_review.get("base_signal_summary") or {},
            "base_signal_rejection_summary": watch_review.get("base_signal_rejection_summary") or {},
            "collection_estimate": watch_review.get("collection_estimate") or {},
        },
        "replay_assessment": {
            "recommended_state": replay_review.get("recommended_state"),
            "reasons": replay_review.get("reasons") or [],
            "matched_trade_count": replay_review.get("matched_trade_count"),
            "replay_end_ts": replay_review.get("replay_end_ts"),
            "windows": replay_review.get("windows") or [],
        },
        "expansion_assessment": {
            "available": expansion_review is not None,
            "error": expansion_error,
            "recommended_state": (expansion_review or {}).get("recommended_state"),
            "reasons": (expansion_review or {}).get("reasons") or [],
            "shadow_watchlist_symbols": (expansion_review or {}).get("shadow_watchlist_symbols") or [],
            "report_review_count": len(list((expansion_review or {}).get("report_reviews") or [])),
            "report_review_summaries": _summarize_expansion_report_reviews(expansion_review),
            "top_symbol_rollup": _summarize_expansion_symbols(expansion_review),
        },
        "expansion_shadow_watch_assessment": {
            "available": expansion_shadow_review is not None,
            "error": expansion_shadow_error,
            "recommended_state": (expansion_shadow_review or {}).get("recommended_state"),
            "blockers": (expansion_shadow_review or {}).get("blockers") or [],
            "unique_candidate_summary": (expansion_shadow_review or {}).get("unique_candidate_summary") or {},
            "base_signal_summary": (expansion_shadow_review or {}).get("base_signal_summary") or {},
            "base_signal_rejection_summary": (expansion_shadow_review or {}).get("base_signal_rejection_summary") or {},
            "collection_estimate": (expansion_shadow_review or {}).get("collection_estimate") or {},
        },
        "exit_policy_upgrade_assessment": {
            "available": exit_policy_upgrade_review is not None,
            "error": exit_policy_upgrade_error,
            "recommended_state": (exit_policy_upgrade_review or {}).get("recommended_state"),
            "reasons": (exit_policy_upgrade_review or {}).get("reasons") or [],
            "baseline_exit_policy": (exit_policy_upgrade_review or {}).get("baseline_exit_policy"),
            "candidate_exit_policy": (exit_policy_upgrade_review or {}).get("candidate_exit_policy"),
            "delta_candidate_minus_baseline": (exit_policy_upgrade_review or {}).get("delta_candidate_minus_baseline") or {},
            "candidate": (exit_policy_upgrade_review or {}).get("candidate") or {},
            "baseline": (exit_policy_upgrade_review or {}).get("baseline") or {},
        },
        "filter_upgrade_assessment": {
            "available": filter_upgrade_review is not None,
            "error": filter_upgrade_error,
            "recommended_state": (filter_upgrade_review or {}).get("recommended_state"),
            "reasons": (filter_upgrade_review or {}).get("reasons") or [],
            "baseline_filter_policy": (filter_upgrade_review or {}).get("baseline_filter_policy"),
            "candidate_filter_policy": (filter_upgrade_review or {}).get("candidate_filter_policy"),
            "exit_policy": (filter_upgrade_review or {}).get("exit_policy"),
            "delta_candidate_minus_baseline": (filter_upgrade_review or {}).get("delta_candidate_minus_baseline") or {},
            "candidate": (filter_upgrade_review or {}).get("candidate") or {},
            "baseline": (filter_upgrade_review or {}).get("baseline") or {},
        },
        "portfolio_mix_assessment": portfolio_mix_status,
        "config_proposal_assessment": config_proposal_status,
        "config_dry_run_assessment": config_dry_run_status,
        "runtime_guard_assessment": runtime_guard_status,
        "safety_assessment": safety_status,
        "operator_summary": {
            "action": _operator_action(state),
            "order_submission_allowed": runtime_entries_allowed,
            "governance_order_submission_allowed": False,
        },
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    watch = dict(payload.get("watch_assessment") or {})
    replay = dict(payload.get("replay_assessment") or {})
    expansion = dict(payload.get("expansion_assessment") or {})
    expansion_shadow = dict(payload.get("expansion_shadow_watch_assessment") or {})
    exit_upgrade = dict(payload.get("exit_policy_upgrade_assessment") or {})
    filter_upgrade = dict(payload.get("filter_upgrade_assessment") or {})
    portfolio_mix = dict(payload.get("portfolio_mix_assessment") or {})
    portfolio_summary = dict(portfolio_mix.get("summary") or {})
    config_proposal = dict(payload.get("config_proposal_assessment") or {})
    config_dry_run = dict(payload.get("config_dry_run_assessment") or {})
    runtime_guard = dict(payload.get("runtime_guard_assessment") or {})
    safety = dict(payload.get("safety_assessment") or {})
    unique = dict(watch.get("unique_candidate_summary") or {})
    base_signal_rejections = dict(watch.get("base_signal_rejection_summary") or {})
    expansion_shadow_unique = dict(expansion_shadow.get("unique_candidate_summary") or {})
    expansion_shadow_rejections = dict(expansion_shadow.get("base_signal_rejection_summary") or {})
    lines = [
        "# Micro Intrabar Candidate Governance",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- authority: {payload.get('authority')}",
        f"- recommended_state: {payload.get('recommended_state')}",
        f"- reasons: {payload.get('reasons')}",
        f"- live_action: {payload.get('live_action')}",
        f"- runtime_entries_allowed: {payload.get('runtime_entries_allowed')}",
        f"- governance_order_submission_allowed: {payload.get('governance_order_submission_allowed')}",
        f"- order_submission_allowed: {dict(payload.get('operator_summary') or {}).get('order_submission_allowed')}",
        f"- unique_candidate_signals: {unique.get('count')}",
        f"- rejected_base_signals: {base_signal_rejections.get('rejected_count')}",
        f"- rejection_reasons: {base_signal_rejections.get('by_filter_reason')}",
        f"- replay_state: {replay.get('recommended_state')}",
        f"- exit_policy_upgrade_state: {exit_upgrade.get('recommended_state')}",
        f"- exit_policy_candidate: {exit_upgrade.get('candidate_exit_policy')}",
        f"- filter_upgrade_state: {filter_upgrade.get('recommended_state')}",
        f"- filter_candidate: {filter_upgrade.get('candidate_filter_policy')}",
        f"- portfolio_mix_state: {portfolio_mix.get('recommended_state')}",
        f"- portfolio_mix_symbols: {portfolio_mix.get('combined_symbol_count')}",
        (
            "- portfolio_mix_summary: "
            f"trades={portfolio_summary.get('closed')} total_r={portfolio_summary.get('total_r')} "
            f"ev={portfolio_summary.get('ev_r')} max_dd={portfolio_summary.get('max_dd_r')}"
        ),
        f"- portfolio_mix_order_submission_allowed: {portfolio_mix.get('order_submission_allowed')}",
        f"- config_proposal_state: {config_proposal.get('recommended_state')}",
        f"- config_proposal_runtime_gaps: {config_proposal.get('runtime_support_gaps')}",
        f"- config_dry_run_state: {config_dry_run.get('recommended_state')}",
        f"- config_dry_run_blocking_failures: {config_dry_run.get('blocking_failure_count')}",
        f"- config_dry_run_warning_failures: {config_dry_run.get('warning_failure_count')}",
        f"- runtime_guard_status: {runtime_guard.get('overall_status')}",
        f"- runtime_guard_blocking_failures: {runtime_guard.get('blocking_failure_count')}",
        f"- expansion_state: {expansion.get('recommended_state')}",
        f"- expansion_shadow_watchlist: {','.join(list(expansion.get('shadow_watchlist_symbols') or []))}",
        f"- expansion_shadow_review_state: {expansion_shadow.get('recommended_state')}",
        f"- expansion_shadow_unique_candidate_signals: {expansion_shadow_unique.get('count')}",
        f"- expansion_shadow_rejected_base_signals: {expansion_shadow_rejections.get('rejected_count')}",
        f"- expansion_shadow_rejection_reasons: {expansion_shadow_rejections.get('by_filter_reason')}",
        f"- safety_new_entry_allowed: {safety.get('new_entry_allowed')}",
        f"- safety_blocking_reason: {safety.get('blocking_reason_code')}",
        "",
        "This governance report does not submit orders or enable live routing.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    generated_at = datetime.now(UTC)
    safety_payload: dict[str, Any] | None = None
    safety_error: str | None = "safety_fetch_skipped" if args.skip_safety_fetch else None
    if not args.skip_safety_fetch:
        safety_payload, safety_error = _fetch_json(str(args.safety_url))
    payload = build_payload(
        _resolve_path(args.contract_path),
        _resolve_path(args.watch_review_path),
        _resolve_path(args.replay_review_path),
        _resolve_path(args.expansion_review_path) if str(args.expansion_review_path or "").strip() else None,
        _resolve_path(args.expansion_shadow_review_path) if str(args.expansion_shadow_review_path or "").strip() else None,
        _resolve_path(args.exit_policy_upgrade_review_path) if str(args.exit_policy_upgrade_review_path or "").strip() else None,
        _resolve_path(args.filter_upgrade_review_path) if str(args.filter_upgrade_review_path or "").strip() else None,
        _resolve_path(args.portfolio_mix_review_path) if str(args.portfolio_mix_review_path or "").strip() else None,
        _resolve_path(args.config_proposal_path) if str(args.config_proposal_path or "").strip() else None,
        _resolve_path(args.runtime_guard_path) if str(args.runtime_guard_path or "").strip() else None,
        config_dry_run_path=_resolve_path(args.config_dry_run_path) if str(args.config_dry_run_path or "").strip() else None,
        safety_payload=safety_payload,
        safety_error=safety_error,
        generated_at=generated_at,
    )
    if args.write_report:
        report_dir = _resolve_path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = _report_stamp(generated_at)
        json_path = report_dir / f"micro_intrabar_candidate_governance_{stamp}.json"
        md_path = report_dir / f"micro_intrabar_candidate_governance_{stamp}.md"
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
