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
    safety_assessment: dict[str, Any],
) -> tuple[str, list[str]]:
    hard_blockers: list[str] = []
    hard_blockers.extend(str(item) for item in list(contract_assessment.get("hard_blockers") or []))
    hard_blockers.extend(str(item) for item in list(safety_assessment.get("hard_blockers") or []))
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
    if watch_state == "PAPER_SAMPLE_REVIEW_READY":
        return "PAPER_SAMPLE_REVIEW_READY_NO_LIVE", ["paper_sample_gate_met_but_live_still_disabled"]
    return "CONTINUE_PAPER_WATCH_AND_REPLAY", ["watch_sample_not_ready_live_disabled"]


def build_payload(
    contract_path: Path,
    watch_review_path: Path,
    replay_review_path: Path,
    expansion_review_path: Path | None = None,
    expansion_shadow_review_path: Path | None = None,
    exit_policy_upgrade_review_path: Path | None = None,
    filter_upgrade_review_path: Path | None = None,
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
    contract_status = _contract_assessment(contract)
    safety_status = _safety_assessment(safety_payload, error=safety_error)
    state, reasons = _decision(
        contract_assessment=contract_status,
        watch_review=watch_review,
        replay_review=replay_review,
        expansion_review=expansion_review,
        expansion_shadow_review=expansion_shadow_review,
        exit_policy_upgrade_review=exit_policy_upgrade_review,
        filter_upgrade_review=filter_upgrade_review,
        safety_assessment=safety_status,
    )
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
        "recommended_state": state,
        "reasons": reasons,
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": False,
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
        "safety_assessment": safety_status,
        "operator_summary": {
            "action": (
                "Keep live entries disabled; continue paper watch and replay review."
                if state == "CONTINUE_PAPER_WATCH_AND_REPLAY"
                else "Hold and inspect blockers before any further promotion."
            ),
            "order_submission_allowed": False,
        },
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    watch = dict(payload.get("watch_assessment") or {})
    replay = dict(payload.get("replay_assessment") or {})
    expansion = dict(payload.get("expansion_assessment") or {})
    expansion_shadow = dict(payload.get("expansion_shadow_watch_assessment") or {})
    exit_upgrade = dict(payload.get("exit_policy_upgrade_assessment") or {})
    filter_upgrade = dict(payload.get("filter_upgrade_assessment") or {})
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
        f"- order_submission_allowed: {dict(payload.get('operator_summary') or {}).get('order_submission_allowed')}",
        f"- unique_candidate_signals: {unique.get('count')}",
        f"- rejected_base_signals: {base_signal_rejections.get('rejected_count')}",
        f"- rejection_reasons: {base_signal_rejections.get('by_filter_reason')}",
        f"- replay_state: {replay.get('recommended_state')}",
        f"- exit_policy_upgrade_state: {exit_upgrade.get('recommended_state')}",
        f"- exit_policy_candidate: {exit_upgrade.get('candidate_exit_policy')}",
        f"- filter_upgrade_state: {filter_upgrade.get('recommended_state')}",
        f"- filter_candidate: {filter_upgrade.get('candidate_filter_policy')}",
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
