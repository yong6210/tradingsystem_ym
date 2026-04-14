#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import notify_stage_change, ops_stage_board, run_runtime_signoff_review
from app.services.family_rollout import RolloutPolicyBootstrap
from app.services.operating_lock import OperatingLockService
from app.services.split_review_followup_ledger import summarize_split_review_followup_ledger


DEFAULT_STAGE_DIR = ROOT_DIR / "reports/operations/stage_monitor"
_LATEST_PAPER_LINEAGE_WATCH_FILE = ROOT_DIR / "reports/operations/paper_candidate_watch/latest_launchd_run.json"
_POST_UNLOCK_BUNDLE_CACHE_SECONDS = 900
_APPROVAL_TEMPLATE_FOCUS_CACHE_SECONDS = 900
_PAPER_LINEAGE_WATCH_FRESH_SECONDS = 7200
_MICRO_LIVE_PREFLIGHT_CACHE_SECONDS = 900
_STAGE_BOARD_REQUEST_TIMEOUT_SECONDS = 20
_STAGE_BOARD_REQUEST_RETRY_ATTEMPTS = 2
_STAGE_BOARD_REQUEST_RETRY_BASE_DELAY_SECONDS = 0.5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the stage monitor board build and stage-change notifier in one Python process."
    )
    parser.add_argument("--base-url", default=os.environ.get("STAGE_MONITOR_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--symbol", default=os.environ.get("STAGE_MONITOR_SYMBOL", "BTCUSDC"))
    parser.add_argument("--universe", default=os.environ.get("STAGE_MONITOR_UNIVERSE", "usdc_perp_top30"))
    parser.add_argument("--limit", type=int, default=int(os.environ.get("STAGE_MONITOR_LIMIT", "20")))
    parser.add_argument("--days", type=int, default=int(os.environ.get("STAGE_MONITOR_DAYS", "30")))
    parser.add_argument(
        "--lineage-sample-scope",
        choices=["symbol_edge_proof", "family_global"],
        default=os.environ.get("STAGE_MONITOR_LINEAGE_SAMPLE_SCOPE", "family_global"),
    )
    parser.add_argument(
        "--lineage-families",
        default=os.environ.get("STAGE_MONITOR_LINEAGE_FAMILIES", "sweep_reversal,trend_continuation"),
    )
    parser.add_argument(
        "--lineage-proof-goal-closed-trades",
        type=int,
        default=int(os.environ.get("STAGE_MONITOR_LINEAGE_PROOF_GOAL_CLOSED_TRADES", "100")),
    )
    parser.add_argument(
        "--lineage-sample-days",
        type=int,
        default=int(os.environ.get("STAGE_MONITOR_LINEAGE_SAMPLE_DAYS", "180")),
    )
    parser.add_argument(
        "--alert-test-lookback-hours",
        type=int,
        default=int(os.environ.get("STAGE_MONITOR_ALERT_TEST_LOOKBACK_HOURS", "24")),
    )
    parser.add_argument(
        "--stage-file",
        default=os.environ.get("STAGE_MONITOR_STAGE_FILE", str(DEFAULT_STAGE_DIR / "current_stage.json")),
    )
    parser.add_argument(
        "--latest-board-file",
        default=os.environ.get("STAGE_MONITOR_LATEST_BOARD_FILE", str(DEFAULT_STAGE_DIR / "latest_stage_board.json")),
    )
    parser.add_argument(
        "--state-file",
        default=os.environ.get("STAGE_MONITOR_STATE_FILE", str(DEFAULT_STAGE_DIR / "last_alert_state.json")),
    )
    parser.add_argument("--webhook-url", default=os.environ.get("STAGE_MONITOR_DISCORD_WEBHOOK_URL", ""))
    parser.add_argument(
        "--edge-sample-stall-hours",
        type=int,
        default=int(os.environ.get("STAGE_MONITOR_EDGE_SAMPLE_STALL_HOURS", "24")),
    )
    parser.add_argument("--dry-run", action="store_true", default=os.environ.get("STAGE_MONITOR_DRY_RUN", "0") == "1")
    return parser.parse_args()


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _load_stage_board_fallback(
    stage_file: Path,
    latest_board_file: Path,
    state_file: Path | None = None,
) -> dict[str, Any]:
    def _read_payload(path: Path | None) -> dict[str, Any] | None:
        if path is None:
            return None
        try:
            payload = notify_stage_change._read_json(path)
        except Exception:
            payload = {}
        return dict(payload) if isinstance(payload, dict) and payload else None

    def _score(payload: dict[str, Any]) -> tuple[int, int]:
        richness = 0
        if str(payload.get("runtime_decision_band") or "").strip():
            richness += 3
        if str(payload.get("runtime_effective_action") or "").strip():
            richness += 3
        if str(payload.get("runtime_allowed_reopen_scope") or "").strip():
            richness += 2
        if str(dict(payload.get("runtime_preflight_summary") or {}).get("status") or "").strip():
            richness += 2
        if str(dict(payload.get("runtime_operator_signoff_summary") or {}).get("status") or "").strip():
            richness += 2
        if str(dict(payload.get("runtime_signoff_summary") or {}).get("status") or "").strip():
            richness += 1
        if dict(payload.get("runtime_reopen_gate_summary") or {}):
            richness += 1
        generated_at = str(payload.get("generated_at") or "")
        recency = 0
        try:
            recency = int(datetime.fromisoformat(generated_at.replace("Z", "+00:00")).timestamp())
        except Exception:
            recency = 0
        return (richness, recency)

    candidates = [
        item
        for item in (
            _read_payload(stage_file),
            _read_payload(latest_board_file),
            _read_payload(state_file),
        )
        if item
    ]
    if not candidates:
        return {}
    return dict(max(candidates, key=_score))


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _runtime_preflight_fingerprint(snapshot: dict[str, Any]) -> str:
    payload = {
        "dashboard_approval_strip": dict(snapshot.get("dashboard_approval_strip") or {}),
        "validation_approval_strip": dict(snapshot.get("validation_approval_strip") or {}),
        "checklist_approval_strip": dict(snapshot.get("checklist_approval_strip") or {}),
        "runtime_effective_action": str(snapshot.get("runtime_effective_action") or ""),
        "runtime_allowed_reopen_scope": str(snapshot.get("runtime_allowed_reopen_scope") or ""),
        "post_patch_closed_trade_count": int(snapshot.get("post_patch_closed_trade_count") or 0),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _lineage_closed_trade_count(payload: dict[str, Any] | None) -> int:
    summary = dict((payload or {}).get("lineage_sample_summary") or {})
    if summary:
        return int(summary.get("closed_trade_count", 0) or 0)
    source = dict((payload or {}).get("edge_experiment_review") or {})
    kpis = dict(source.get("daily_edge_kpis") or {})
    return int(kpis.get("closed_trade_count", source.get("closed_trade_count", 0)) or 0)


def _latest_closed_trade_ts(
    *,
    symbol: str,
    scope: str,
    families: list[str],
    sample_days: int,
) -> datetime | None:
    if str(scope or "symbol_edge_proof") != "family_global":
        return _latest_symbol_closed_trade_ts(symbol)
    return _latest_family_closed_trade_ts(families=families, sample_days=sample_days)


def _load_latest_lineage_watch_summary(*, max_age_seconds: int = _PAPER_LINEAGE_WATCH_FRESH_SECONDS) -> dict[str, Any]:
    path = _LATEST_PAPER_LINEAGE_WATCH_FILE
    if not path.exists():
        return {"available": False, "fresh": False}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"available": False, "fresh": False}

    generated_at = _parse_ts(payload.get("generated_at"))
    age_seconds = None
    if generated_at is not None:
        age_seconds = max((datetime.now(timezone.utc) - generated_at).total_seconds(), 0.0)
    fresh = age_seconds is not None and age_seconds <= float(max_age_seconds)

    candidate_focus = dict(payload.get("candidate_edge_experiment_focus") or {})
    final_result = dict(payload.get("final_result") or {})
    approval = dict(final_result.get("approval") or {})
    return {
        "available": True,
        "fresh": fresh,
        "generated_at": generated_at.isoformat() if generated_at else "",
        "age_seconds": age_seconds,
        "tick_status": str(payload.get("tick_status") or ""),
        "summary_line": str(payload.get("summary_line") or ""),
        "candidate_symbol": str(candidate_focus.get("symbol") or approval.get("symbol") or ""),
        "candidate_family": str(candidate_focus.get("strategy_family") or approval.get("strategy_family") or ""),
        "candidate_status": str(approval.get("approval_state") or ""),
        "candidate_reason": str(candidate_focus.get("block_reason") or ""),
    }


def _runtime_mitigation_session_context(*, family: str | None) -> dict[str, Any]:
    session = OperatingLockService().current_session(now=datetime.now(timezone.utc)).to_dict()
    policy = RolloutPolicyBootstrap().get(family)
    allowed_sessions = [str(item).strip().lower() for item in list(policy.allowed_sessions or []) if str(item).strip()]
    return {
        "current_session": str(session.get("name") or "inactive").lower(),
        "session_active": bool(session.get("active", False)),
        "allowed_sessions": allowed_sessions,
    }


def _latest_symbol_closed_trade_ts(symbol: str) -> datetime | None:
    from app.core.enums import PlanState
    from app.db.models import Plan
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        rows = db.query(Plan).filter(Plan.symbol == symbol, Plan.state == PlanState.CLOSED.value).all()
        latest: datetime | None = None
        for row in rows:
            validity = dict(getattr(row, "validity", {}) or {})
            candidate = _parse_ts(validity.get("final_exit_ts") or validity.get("last_exit_ts"))
            if candidate is None:
                continue
            if latest is None or candidate > latest:
                latest = candidate
        return latest
    finally:
        db.close()


def _latest_family_closed_trade_ts(*, families: list[str], sample_days: int) -> datetime | None:
    _, latest = ops_stage_board._family_closed_fill_metrics(families=families, sample_days=sample_days)
    return latest


def _apply_edge_sample_stall(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    *,
    symbol: str,
    lineage_sample_scope: str,
    lineage_families: list[str],
    lineage_sample_days: int,
    threshold_hours: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    snapshot = dict(current or {})
    current_generated_at = _parse_ts(snapshot.get("generated_at")) or now or datetime.now(timezone.utc)
    current_closed_count = _lineage_closed_trade_count(snapshot)
    previous_stall = dict((previous or {}).get("edge_sample_stall") or {})

    prior_progress_count = int(previous_stall.get("progress_count", current_closed_count) or 0)
    prior_progress_at = _parse_ts(previous_stall.get("last_progress_at")) or _parse_ts((previous or {}).get("generated_at"))
    latest_closed_at = _latest_closed_trade_ts(
        symbol=symbol,
        scope=lineage_sample_scope,
        families=lineage_families,
        sample_days=lineage_sample_days,
    )

    if previous is None or current_closed_count != prior_progress_count:
        progress_count = current_closed_count
        last_progress_at = latest_closed_at or current_generated_at
    elif prior_progress_at is None:
        progress_count = current_closed_count
        last_progress_at = latest_closed_at or current_generated_at
    else:
        progress_count = prior_progress_count
        last_progress_at = prior_progress_at
        if latest_closed_at is not None and latest_closed_at < last_progress_at:
            last_progress_at = latest_closed_at

    elapsed_hours = max((current_generated_at - last_progress_at).total_seconds() / 3600.0, 0.0)
    active = (
        current_closed_count > 0
        and not bool(snapshot.get("edge_sample_gate_ready", False))
        and elapsed_hours >= float(max(1, threshold_hours))
    )
    snapshot["edge_sample_stall"] = {
        "active": active,
        "threshold_hours": int(max(1, threshold_hours)),
        "hours_since_progress": round(elapsed_hours, 2),
        "progress_count": int(progress_count),
        "current_closed_trade_count": int(current_closed_count),
        "last_progress_at": last_progress_at.isoformat(),
        "scope": str(lineage_sample_scope),
        "families": list(lineage_families),
        "status": "stalled" if active else "tracking",
        "summary": (
            f"closed_trade_count unchanged at {current_closed_count} for {elapsed_hours:.1f}h "
            f"(threshold={max(1, threshold_hours)}h)"
        ),
    }
    return snapshot


def _run_post_unlock_review_bundle(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT_DIR / "scripts/run_post_unlock_review.py"),
        "--base-url",
        args.base_url,
        "--symbol",
        args.symbol,
        "--universe",
        args.universe,
        "--days",
        str(args.days),
        "--no-write-report",
    ]
    completed = subprocess.run(
        command,
        cwd=str(ROOT_DIR),
        check=True,
        capture_output=True,
        text=True,
    )
    stdout = str(completed.stdout or "").strip()
    if not stdout:
        raise RuntimeError("post-unlock review bundle returned empty stdout")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("post-unlock review bundle did not return valid JSON") from exc


def _run_micro_live_preflight(args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT_DIR / "scripts/run_micro_live_preflight.py"),
        "--base-url",
        args.base_url,
        "--symbol",
        args.symbol,
        "--universe",
        args.universe,
        "--days",
        str(args.days),
        "--no-write-report",
    ]
    completed = subprocess.run(
        command,
        cwd=str(ROOT_DIR),
        check=True,
        capture_output=True,
        text=True,
    )
    stdout = str(completed.stdout or "").strip()
    if not stdout:
        raise RuntimeError("micro-live preflight returned empty stdout")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("micro-live preflight did not return valid JSON") from exc


def _apply_post_unlock_review_bundle(
    current: dict[str, Any],
    args: argparse.Namespace,
    *,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = dict(current or {})
    summary = dict(snapshot.get("post_unlock_review_summary") or {})
    review_window_open = bool(summary.get("review_window_open", False)) or _post_patch_review_window_open(
        snapshot,
        previous=previous,
    )
    bundle_command = str(summary.get("bundle_review_command") or "")
    if review_window_open and not bool(summary.get("review_window_open", False)):
        summary["review_window_open"] = True
        summary["active"] = True
        if not str(summary.get("next_review_step") or "").strip():
            summary["next_review_step"] = "review_validation_and_checklist_before_runtime_reopen"
        snapshot["post_unlock_review_summary"] = summary
    if not review_window_open:
        snapshot["post_unlock_bundle_result"] = {
            "active": bool(summary.get("active", False)),
            "executed": False,
            "status": "waiting_for_review_window",
            "summary": "post-unlock bundle review is waiting for the review window to open",
            "bundle_review_command": bundle_command,
        }
        return snapshot

    previous_bundle = dict((previous or {}).get("post_unlock_bundle_result") or {})
    previous_bundle_computed_at = _parse_ts(previous_bundle.get("computed_at"))
    previous_bundle_recent = (
        previous_bundle_computed_at is not None
        and (datetime.now(timezone.utc) - previous_bundle_computed_at).total_seconds()
        <= float(_POST_UNLOCK_BUNDLE_CACHE_SECONDS)
    )
    if (
        previous_bundle_recent
        and str(previous_bundle.get("bundle_review_command") or "") == bundle_command
        and str(previous_bundle.get("status") or "").upper() not in {"", "WAITING_FOR_REVIEW_WINDOW"}
    ):
        reused = dict(previous_bundle)
        reused["cache_reused"] = True
        snapshot["post_unlock_bundle_result"] = reused
        return snapshot

    computed_at = datetime.now(timezone.utc).isoformat()
    try:
        result = _run_post_unlock_review_bundle(args)
    except Exception as exc:
        snapshot["post_unlock_bundle_result"] = {
            "active": True,
            "executed": True,
            "status": "ERROR",
            "summary": f"post-unlock bundle failed: {exc}",
            "bundle_review_command": bundle_command,
            "computed_at": computed_at,
            "micro_live_preflight_status": "",
            "post_live_pruning_review_decision": "",
        }
        return snapshot
    snapshot["post_unlock_bundle_result"] = {
        "active": True,
        "executed": True,
        "status": str(result.get("status") or "UNKNOWN"),
        "summary": str(result.get("summary_line") or ""),
        "bundle_review_command": str(result.get("bundle_review_command") or bundle_command),
        "computed_at": computed_at,
        "micro_live_preflight_status": str(
            ((result.get("micro_live_preflight") or {}).get("overall_status") or "")
        ),
        "post_live_pruning_review_decision": str(
            ((result.get("post_live_pruning_review") or {}).get("decision") or "")
        ),
    }
    return snapshot


def _apply_runtime_reopen_status(current: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(current or {})
    review_summary = dict(snapshot.get("post_unlock_review_summary") or {})
    bundle_result = dict(snapshot.get("post_unlock_bundle_result") or {})
    risk_gate_summary = dict(snapshot.get("risk_gate_summary") or {})

    risk_closed = str(risk_gate_summary.get("risk_state") or "").upper() == "CLOSED"
    review_window_open = bool(review_summary.get("review_window_open", False)) or _post_patch_review_window_open(snapshot)
    bundle_status = str(bundle_result.get("status") or "").upper()

    if risk_closed:
        status = "waiting_for_operating_lock"
        ready = False
    elif not review_window_open:
        status = "waiting_for_review_window"
        ready = False
    elif bundle_status == "REVIEW_WINDOW_OPEN_PENDING_BUNDLE":
        status = "review_window_open_pending_bundle"
        ready = False
    elif bundle_status == "READY_TO_REOPEN_RUNTIME":
        status = "ready_to_reopen_runtime"
        ready = True
    elif bundle_status and bundle_status != "WAITING_FOR_REVIEW_WINDOW":
        status = "manual_review_required"
        ready = False
    else:
        status = "review_window_open_pending_bundle"
        ready = False

    snapshot["runtime_reopen_status"] = {
        "status": status,
        "ready": ready,
        "summary": f"runtime_reopen_status={status}",
    }
    return snapshot


def _runtime_signoff_eligible(runtime_status: str) -> bool:
    return str(runtime_status or "").strip().lower() in {
        "ready_to_reopen_runtime",
        "manual_review_required",
        "review_window_open_pending_bundle",
    }


def _post_patch_review_window_open(
    current: dict[str, Any],
    *,
    previous: dict[str, Any] | None = None,
) -> bool:
    snapshot = dict(current or {})
    previous_snapshot = dict(previous or {})
    risk_gate_summary = dict(snapshot.get("risk_gate_summary") or {})
    risk_open = (
        str(risk_gate_summary.get("status") or "").upper() == "PASS"
        and str(risk_gate_summary.get("risk_state") or "").upper() == "OPEN"
    )
    if not risk_open or not bool(snapshot.get("all_readiness_gates_ready", False)):
        return False
    if bool(snapshot.get("post_patch_ready_for_replay_refresh", False)):
        return True
    if bool(previous_snapshot.get("post_patch_ready_for_replay_refresh", False)):
        return True
    current_focus = dict(snapshot.get("approval_template_focus") or {})
    previous_focus = dict(previous_snapshot.get("approval_template_focus") or {})
    return bool(dict(current_focus.get("post_patch_sample_summary") or {}).get("ready_for_replay_refresh", False)) or bool(
        dict(previous_focus.get("post_patch_sample_summary") or {}).get("ready_for_replay_refresh", False)
    )


def _apply_runtime_signoff_summary(current: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(current or {})
    signoff = dict(snapshot.get("runtime_signoff_summary") or {})
    runtime = dict(snapshot.get("runtime_reopen_status") or {})
    required_reviews = list(signoff.get("required_reviews") or [])
    advisory_reviews = list(signoff.get("advisory_reviews") or [])
    runtime_ready = _runtime_signoff_eligible(str(runtime.get("status") or ""))
    approval_template_focus = dict(signoff.get("approval_template_focus") or snapshot.get("approval_template_focus") or {})
    approval_template_focus_error = str(
        signoff.get("approval_template_focus_error") or snapshot.get("approval_template_focus_error") or ""
    )

    if not runtime_ready:
        status = "not_ready"
    elif required_reviews:
        status = "manual_signoff_required"
    else:
        status = "ready_for_operator_signoff"

    approval_review = next(
        (item for item in required_reviews if str(item.get("code") or "") == "approval_template_review"),
        None,
    )
    if not runtime_ready:
        operator_recommendation = "wait_until_runtime_ready"
        operator_recommendation_reason = "runtime reopen status is not ready yet"
    elif approval_review is not None and str(approval_review.get("worst_scenario_status") or "").upper() == "FAIL":
        operator_recommendation = "hold_runtime_reopen"
        operator_recommendation_reason = (
            "replay-derived worst scenario still fails; keep runtime closed unless the operator explicitly accepts the risk"
        )
    elif required_reviews:
        operator_recommendation = "manual_signoff_required"
        operator_recommendation_reason = "runtime is reopen-ready but required operator review items remain"
    else:
        operator_recommendation = "proceed_to_operator_signoff"
        operator_recommendation_reason = "runtime is reopen-ready and no required operator review items remain"

    review_labels = ",".join(str(item.get("code") or "") for item in required_reviews) or "none"
    summary = (
        f"runtime sign-off status={status} | required={review_labels}"
        if runtime_ready
        else f"runtime sign-off is pending until reopen status becomes ready | required={review_labels}"
    )
    snapshot["runtime_signoff_summary"] = {
        "status": status,
        "required_reviews": required_reviews,
        "advisory_reviews": advisory_reviews,
        "required_count": len(required_reviews),
        "advisory_count": len(advisory_reviews),
        "required_clearance_line": " | ".join(
            f"{item.get('code') or 'unknown'}=>{item.get('clear_when') or 'clear when warning is removed'}"
            for item in required_reviews
        ),
        "operator_recommendation": operator_recommendation,
        "operator_recommendation_reason": operator_recommendation_reason,
        "summary": summary,
        "approval_template_focus": approval_template_focus,
        "approval_template_focus_error": approval_template_focus_error,
        "approval_template_focus_cached_at": str(signoff.get("approval_template_focus_cached_at") or ""),
    }
    return snapshot


def _apply_runtime_signoff_decision(current: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(current or {})
    signoff = dict(snapshot.get("runtime_signoff_summary") or {})
    runtime = dict(snapshot.get("runtime_reopen_status") or {})
    decision = run_runtime_signoff_review._build_runtime_decision(
        runtime_ready=_runtime_signoff_eligible(str(runtime.get("status") or "")),
        required_reviews=[dict(item) for item in list(signoff.get("required_reviews") or [])],
        approval_template_focus=dict(signoff.get("approval_template_focus") or {}),
    )
    signoff["runtime_decision"] = decision
    action = str(decision.get("effective_action") or "")
    if action:
        signoff["operator_recommendation"] = action
        if action == "conditional_micro_live_signoff":
            signoff["operator_recommendation_reason"] = (
                "legacy replay remains red, but the post-patch mitigation cohort cleared the red thresholds; "
                "limit any reopen to MICRO_LIVE while operator sign-off remains manual"
            )
        elif action == "conditional_full_live_signoff":
            signoff["operator_recommendation_reason"] = (
                "legacy replay remains red, but the post-patch mitigation cohort cleared the conditional FULL LIVE "
                "thresholds; any reopen still requires explicit operator sign-off"
            )
        elif action == "hold_runtime_reopen":
            signoff["operator_recommendation_reason"] = "replay downside exceeds operating tolerance; keep runtime closed"
        elif action == "manual_signoff_required":
            signoff["operator_recommendation_reason"] = "runtime is reopen-ready but required operator review items remain"
        elif action == "proceed_to_operator_signoff":
            signoff["operator_recommendation_reason"] = "runtime is reopen-ready and no required operator review items remain"
    signoff["runtime_reopen_gate_summary"] = run_runtime_signoff_review._build_runtime_reopen_gate_summary(
        signoff.get("approval_template_focus"),
        decision,
    )
    snapshot["runtime_signoff_summary"] = signoff
    return snapshot


def _apply_runtime_signoff_projection(current: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(current or {})
    signoff = dict(snapshot.get("runtime_signoff_summary") or {})
    focus = dict(signoff.get("approval_template_focus") or {})
    decision = dict(signoff.get("runtime_decision") or {})
    post_patch = dict(focus.get("post_patch_sample_summary") or {})
    gate_summary = dict(signoff.get("runtime_reopen_gate_summary") or {})

    snapshot["approval_template_focus"] = focus
    if signoff.get("approval_template_focus_error"):
        snapshot["approval_template_focus_error"] = str(signoff.get("approval_template_focus_error") or "")
    else:
        snapshot.pop("approval_template_focus_error", None)

    snapshot["runtime_decision"] = decision
    snapshot["runtime_signoff_status"] = str(signoff.get("status") or "")
    snapshot["runtime_operator_recommendation"] = str(signoff.get("operator_recommendation") or "")
    snapshot["runtime_decision_band"] = str(decision.get("band") or "")
    snapshot["runtime_effective_action"] = str(decision.get("effective_action") or "")
    snapshot["runtime_allowed_reopen_scope"] = str(decision.get("allowed_reopen_scope") or "")
    snapshot["approval_worst"] = str(focus.get("worst_scenario") or "")
    snapshot["approval_worst_status"] = str(focus.get("worst_scenario_status") or "")
    snapshot["post_patch_sample_summary"] = post_patch
    snapshot["runtime_reopen_gate_summary"] = gate_summary
    snapshot["post_patch_closed_trade_count"] = int(post_patch.get("closed_trade_count", 0) or 0)
    snapshot["post_patch_target_closed_trades"] = int(post_patch.get("target_closed_trades", 0) or 0)
    snapshot["post_patch_remaining_to_target"] = int(post_patch.get("remaining_to_target", 0) or 0)
    snapshot["post_patch_ready_for_replay_refresh"] = bool(post_patch.get("ready_for_replay_refresh", False))
    return snapshot


def _apply_runtime_preflight_summary(
    current: dict[str, Any],
    args: argparse.Namespace,
    *,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = dict(current or {})
    action = str(snapshot.get("runtime_effective_action") or "")
    command = (
        f"{sys.executable} scripts/run_micro_live_preflight.py "
        f"--base-url {args.base_url} --symbol {args.symbol} --universe {args.universe} --days {args.days} --no-write-report"
    )
    applicable_actions = {
        "conditional_micro_live_signoff",
        "conditional_full_live_signoff",
        "proceed_to_operator_signoff",
    }
    if action not in applicable_actions:
        snapshot["runtime_preflight_summary"] = {
            "active": False,
            "status": "not_applicable",
            "summary": "runtime preflight is only applicable once runtime sign-off enters an operator review stage",
            "command": command,
        }
        return snapshot

    current_closed = int(snapshot.get("post_patch_closed_trade_count") or 0)
    fingerprint = _runtime_preflight_fingerprint(snapshot)
    previous_summary = dict((previous or {}).get("runtime_preflight_summary") or {})
    previous_computed_at = _parse_ts(previous_summary.get("computed_at"))
    previous_recent = (
        previous_computed_at is not None
        and (datetime.now(timezone.utc) - previous_computed_at).total_seconds()
        <= float(_MICRO_LIVE_PREFLIGHT_CACHE_SECONDS)
    )
    if (
        previous_recent
        and str(previous_summary.get("command") or "") == command
        and str(previous_summary.get("effective_action") or "") == action
        and int(previous_summary.get("post_patch_closed_trade_count") or 0) == current_closed
        and str(previous_summary.get("fingerprint") or "") == fingerprint
        and str(previous_summary.get("status") or "").upper() not in {"", "ERROR"}
    ):
        reused = dict(previous_summary)
        reused["cache_reused"] = True
        snapshot["runtime_preflight_summary"] = reused
        return snapshot

    computed_at = datetime.now(timezone.utc).isoformat()
    try:
        result = _run_micro_live_preflight(args)
        checks = list(result.get("checks") or [])
        failed = [dict(item) for item in checks if str(item.get("status") or "") != "PASS"]
        snapshot["runtime_preflight_summary"] = {
            "active": True,
            "executed": True,
            "status": str(result.get("overall_status") or "UNKNOWN"),
            "summary": str(result.get("summary_line") or ""),
            "command": command,
            "effective_action": action,
            "post_patch_closed_trade_count": current_closed,
            "fingerprint": fingerprint,
            "computed_at": computed_at,
            "failed_checks": failed,
        }
    except Exception as exc:
        snapshot["runtime_preflight_summary"] = {
            "active": True,
            "executed": True,
            "status": "ERROR",
            "summary": f"micro-live preflight failed: {exc}",
            "command": command,
            "effective_action": action,
            "post_patch_closed_trade_count": current_closed,
            "fingerprint": fingerprint,
            "computed_at": computed_at,
            "failed_checks": [],
        }
    return snapshot


def _apply_runtime_operator_signoff_summary(current: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(current or {})
    snapshot["runtime_operator_signoff_summary"] = run_runtime_signoff_review._build_runtime_operator_signoff_summary(
        runtime_decision=dict(snapshot.get("runtime_decision") or {}),
        runtime_preflight_summary=dict(snapshot.get("runtime_preflight_summary") or {}),
        runtime_signoff_summary=dict(snapshot.get("runtime_signoff_summary") or {}),
    )
    return snapshot


def _apply_runtime_signoff_approval_focus(
    current: dict[str, Any],
    *,
    symbol: str,
    base_url: str,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = dict(current or {})
    signoff = dict(snapshot.get("runtime_signoff_summary") or {})
    required_reviews = list(signoff.get("required_reviews") or [])
    approval_review = next(
        (item for item in required_reviews if str(item.get("code") or "") == "approval_template_review"),
        None,
    )
    if approval_review is None:
        signoff.pop("approval_template_focus", None)
        signoff.pop("approval_template_focus_error", None)
        signoff.pop("approval_template_focus_cached_at", None)
        snapshot["runtime_signoff_summary"] = signoff
        return snapshot

    worst_scenario = str(approval_review.get("worst_scenario") or "")
    focus_symbol = run_runtime_signoff_review._approval_template_focus_symbol(snapshot, symbol=symbol)
    previous_signoff = dict((previous or {}).get("runtime_signoff_summary") or {})
    previous_focus = dict(previous_signoff.get("approval_template_focus") or {})
    current_focus = dict(snapshot.get("approval_template_focus") or {})
    if not previous_focus and current_focus:
        previous_focus = current_focus
    previous_focus_cached_at = _parse_ts(
        previous_signoff.get("approval_template_focus_cached_at")
        or previous_focus.get("computed_at")
        or current_focus.get("computed_at")
    )
    previous_focus_recent = (
        previous_focus_cached_at is not None
        and (datetime.now(timezone.utc) - previous_focus_cached_at).total_seconds()
        <= float(_APPROVAL_TEMPLATE_FOCUS_CACHE_SECONDS)
    )
    if (
        previous_focus_recent
        and str(previous_focus.get("focus_symbol") or "") == focus_symbol
        and str(previous_focus.get("worst_scenario") or "") == worst_scenario
    ):
        signoff["approval_template_focus"] = previous_focus
        signoff["approval_template_focus_cached_at"] = str(
            previous_signoff.get("approval_template_focus_cached_at") or previous_focus.get("computed_at") or ""
        )
        previous_focus_error = str(previous_signoff.get("approval_template_focus_error") or "").strip()
        if previous_focus_error:
            signoff["approval_template_focus_error"] = previous_focus_error
        else:
            signoff.pop("approval_template_focus_error", None)
        snapshot["runtime_signoff_summary"] = signoff
        return snapshot

    try:
        enriched = run_runtime_signoff_review._attach_approval_template_focus(
            {"primary_required_review": approval_review},
            stage=snapshot,
            symbol=symbol,
            base_url=base_url,
            request_json_fn=lambda request_base_url, path, query: ops_stage_board._request_json(
                request_base_url,
                "GET",
                path,
                query=query,
            ),
        )
        focus = dict(enriched.get("approval_template_focus") or {})
        focus_error = str(enriched.get("approval_template_focus_error") or "").strip()
    except Exception as exc:
        focus = {}
        focus_error = f"approval template focus refresh failed: {exc}"
    if focus:
        computed_at = datetime.now(timezone.utc).isoformat()
        focus["computed_at"] = computed_at
        signoff["approval_template_focus"] = focus
        signoff["approval_template_focus_cached_at"] = computed_at
    else:
        if (
            previous_focus
            and str(previous_focus.get("focus_symbol") or "") == focus_symbol
            and str(previous_focus.get("worst_scenario") or "") == worst_scenario
        ):
            signoff["approval_template_focus"] = previous_focus
            signoff["approval_template_focus_cached_at"] = str(
                previous_signoff.get("approval_template_focus_cached_at")
                or previous_focus.get("computed_at")
                or ""
            )
            focus_error = ""
        else:
            signoff.pop("approval_template_focus", None)
            signoff.pop("approval_template_focus_cached_at", None)
    if focus_error:
        signoff["approval_template_focus_error"] = focus_error
    else:
        signoff.pop("approval_template_focus_error", None)
    snapshot["runtime_signoff_summary"] = signoff
    return snapshot


def _apply_runtime_mitigation_summary(current: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(current or {})
    signoff = dict(snapshot.get("runtime_signoff_summary") or {})
    focus = dict(signoff.get("approval_template_focus") or {})
    review_summary = dict(focus.get("mitigation_review_summary") or {})
    execution_plan = dict(focus.get("mitigation_execution_plan") or {})
    items = list(review_summary.get("items") or [])
    primary_action_code = str(review_summary.get("primary_action_code") or "")
    primary_action_status = str(review_summary.get("primary_action_status") or "")
    primary_action_command = str(review_summary.get("primary_action_command") or "")
    primary_item = next(
        (dict(item) for item in items if str(item.get("code") or "") == primary_action_code),
        dict(items[0]) if items else {},
    )
    snapshot["runtime_mitigation_summary"] = {
        "available": bool(items),
        "primary_action_code": primary_action_code,
        "primary_action_status": primary_action_status,
        "primary_action_command": primary_action_command,
        "primary_action_constraint": str(primary_item.get("current_constraint") or ""),
        "primary_focus_code": str(execution_plan.get("primary_focus_code") or ""),
        "primary_focus_label": str(execution_plan.get("primary_focus_label") or ""),
        "secondary_focus_code": str(execution_plan.get("secondary_focus_code") or ""),
        "secondary_focus_label": str(execution_plan.get("secondary_focus_label") or ""),
        "secondary_status": str(execution_plan.get("secondary_status") or ""),
        "actionable_now_count": int(review_summary.get("actionable_now_count", 0) or 0),
        "candidate_pending_count": int(review_summary.get("candidate_pending_count", 0) or 0),
        "deferred_count": int(review_summary.get("deferred_count", 0) or 0),
        "research_only_count": int(review_summary.get("research_only_count", 0) or 0),
        "items": items,
        "summary": (
            f"runtime mitigation={primary_action_code or 'none'}/{primary_action_status or 'none'}"
            f" | primary_focus={str(execution_plan.get('primary_focus_label') or primary_action_code or 'none')}"
            if items
            else "runtime mitigation=none"
        ),
    }
    return snapshot


def _runtime_mitigation_action_key(current: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    summary = dict((current or {}).get("runtime_mitigation_summary") or {})
    code = str(summary.get("primary_action_code") or "")
    if code == "range_entry_timing_review":
        target = dict((current or {}).get("entry_timing_review_target") or {})
        return "run_entry_timing_split_review", target, str(target.get("preferred_variant") or "")
    if code == "execution_style_review":
        target = dict((current or {}).get("execution_style_review_target") or {})
        return "run_execution_style_split_review", target, str(target.get("preferred_variant") or "")
    return "", {}, ""


def _find_fresh_runtime_mitigation_packet(
    *,
    symbol: str,
    universe: str,
    action: str,
    target_symbol: str,
    preferred_variant: str,
) -> dict[str, Any] | None:
    summary = summarize_split_review_followup_ledger(symbol=symbol, universe=universe)
    for packet in list(summary.get("recent_packets") or []):
        item = dict(packet or {})
        target = dict(item.get("target_contract") or {})
        if str(item.get("generated_status") or item.get("status") or "") != "READY":
            continue
        if str(item.get("action") or "") != action:
            continue
        if str(target.get("symbol") or "").upper() != str(target_symbol or "").upper():
            continue
        if preferred_variant and str(target.get("preferred_variant") or "") != preferred_variant:
            continue
        return item
    return None


def _run_runtime_mitigation_packet_command(command: str) -> dict[str, Any]:
    completed = subprocess.run(
        shlex.split(command),
        cwd=str(ROOT_DIR),
        check=True,
        capture_output=True,
        text=True,
    )
    stdout = str(completed.stdout or "").strip()
    if not stdout:
        raise RuntimeError("runtime mitigation packet command returned empty stdout")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("runtime mitigation packet command did not return valid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("runtime mitigation packet command did not return an object")
    return payload


def _apply_runtime_mitigation_packet(current: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    snapshot = dict(current or {})
    summary = dict(snapshot.get("runtime_mitigation_summary") or {})
    status = str(summary.get("primary_action_status") or "")
    command = str(summary.get("primary_action_command") or "")
    focus_label = str(summary.get("primary_focus_label") or summary.get("primary_action_code") or "")
    wait_constraint = str(summary.get("primary_action_constraint") or "")
    action, target, preferred_variant = _runtime_mitigation_action_key(snapshot)

    result: dict[str, Any] = {
        "available": bool(summary.get("available", False)),
        "status": "inactive",
        "executed": False,
        "packet_id": "",
        "command": command,
        "target_symbol": str(target.get("symbol") or ""),
        "target_variant": preferred_variant,
        "focus_label": focus_label,
        "wait_constraint": wait_constraint,
        "primary_action_status": status,
        "summary": "runtime mitigation packet is inactive",
    }
    if not bool(summary.get("available", False)):
        snapshot["runtime_mitigation_packet_result"] = result
        return snapshot
    watch_summary = _load_latest_lineage_watch_summary()
    if (
        status == "candidate_review_pending"
        and action == "run_entry_timing_split_review"
        and not str(target.get("symbol") or "").strip()
        and bool(watch_summary.get("fresh"))
        and str(watch_summary.get("tick_status") or "") == "found_eligible_candidate"
        and str(watch_summary.get("candidate_symbol") or "").strip()
    ):
        candidate_symbol = str(watch_summary.get("candidate_symbol") or "").strip().upper()
        candidate_family = str(watch_summary.get("candidate_family") or "").strip().lower()
        target = {
            "symbol": candidate_symbol,
            "strategy_family": candidate_family,
            "status": str(watch_summary.get("candidate_status") or "WATCH_ELIGIBLE"),
        }
        preferred_variant = ""
        command = (
            f"./.venv/bin/python scripts/run_split_review_followup.py "
            f"--symbol {candidate_symbol} --universe {args.universe} --days {max(int(args.days), 1)} "
            f"--action run_entry_timing_split_review"
        )
        result["command"] = command
        result["target_symbol"] = candidate_symbol
        status = "actionable_now"

    if status != "actionable_now" or not action or not command:
        result["status"] = "waiting_for_actionable_mitigation"
        result["summary"] = (
            "runtime mitigation packet is waiting; "
            f"focus={focus_label or 'none'}; primary_action_status={status or 'none'}; "
            f"constraint={wait_constraint or 'none'}"
        )
        snapshot["runtime_mitigation_packet_result"] = result
        return snapshot

    fresh_packet = _find_fresh_runtime_mitigation_packet(
        symbol=str(target.get("symbol") or args.symbol),
        universe=args.universe,
        action=action,
        target_symbol=str(target.get("symbol") or ""),
        preferred_variant=preferred_variant,
    )
    if fresh_packet:
        result.update(
            {
                "status": "fresh_packet_ready_exists",
                "packet_id": str(fresh_packet.get("packet_id") or ""),
                "target_symbol": str(dict(fresh_packet.get("target_contract") or {}).get("symbol") or target.get("symbol") or ""),
                "target_variant": str(dict(fresh_packet.get("target_contract") or {}).get("preferred_variant") or preferred_variant),
                "summary": "a fresh READY runtime mitigation packet already exists",
            }
        )
        snapshot["runtime_mitigation_packet_result"] = result
        return snapshot

    if bool(getattr(args, "dry_run", False)):
        result["status"] = "actionable_pending_dry_run"
        result["summary"] = "runtime mitigation is actionable but packet generation is skipped in dry-run mode"
        snapshot["runtime_mitigation_packet_result"] = result
        return snapshot

    try:
        payload = _run_runtime_mitigation_packet_command(command)
    except Exception as exc:
        result.update(
            {
                "status": "ERROR",
                "executed": True,
                "summary": f"runtime mitigation packet failed: {exc}",
            }
        )
        snapshot["runtime_mitigation_packet_result"] = result
        return snapshot
    result.update(
        {
            "status": str(payload.get("status") or "UNKNOWN"),
            "executed": True,
            "packet_id": str(payload.get("packet_id") or ""),
            "target_symbol": str(dict(payload.get("target_contract") or {}).get("symbol") or target.get("symbol") or ""),
            "target_variant": str(dict(payload.get("target_contract") or {}).get("preferred_variant") or preferred_variant),
            "summary": f"runtime mitigation packet generated with status={str(payload.get('status') or 'UNKNOWN')}",
        }
    )
    snapshot["runtime_mitigation_packet_result"] = result
    snapshot["review_followup_ledger"] = summarize_split_review_followup_ledger(
        symbol=str(result.get("target_symbol") or args.symbol),
        universe=args.universe,
    )
    return snapshot


def _apply_runtime_mitigation_wait_summary(current: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(current or {})
    mitigation = dict(snapshot.get("runtime_mitigation_summary") or {})
    packet = dict(snapshot.get("runtime_mitigation_packet_result") or {})
    entry_target = dict(snapshot.get("entry_timing_review_target") or {})
    accepted_focus = dict(snapshot.get("accepted_candidate_focus") or {})
    blocked_focus = dict(snapshot.get("blocked_candidate_focus") or {})
    lineage_summary = dict(snapshot.get("lineage_sample_summary") or {})
    lineage_families = [str(item).strip().lower() for item in list(lineage_summary.get("families") or []) if str(item).strip()]
    focus_family = (
        str(entry_target.get("strategy_family") or "")
        or str(accepted_focus.get("strategy_family") or "")
        or str(blocked_focus.get("strategy_family") or "")
        or (lineage_families[0] if lineage_families else "")
    ).strip().lower()
    session_context = _runtime_mitigation_session_context(family=focus_family or None)
    watch_summary = _load_latest_lineage_watch_summary()

    result: dict[str, Any] = {
        "available": bool(mitigation.get("available", False)),
        "status": "inactive",
        "focus_label": str(mitigation.get("primary_focus_label") or mitigation.get("primary_action_code") or ""),
        "wait_constraint": str(mitigation.get("primary_action_constraint") or ""),
        "next_trigger": "",
        "current_session": str(session_context.get("current_session") or ""),
        "session_active": bool(session_context.get("session_active", False)),
        "allowed_sessions": list(session_context.get("allowed_sessions") or []),
        "candidate_symbol": "",
        "candidate_family": "",
        "candidate_status": "",
        "candidate_reason": "",
        "watch_tick_status": str(watch_summary.get("tick_status") or ""),
        "watch_generated_at": str(watch_summary.get("generated_at") or ""),
        "summary": "runtime mitigation wait is inactive",
    }
    if not bool(mitigation.get("available", False)):
        snapshot["runtime_mitigation_wait_summary"] = result
        return snapshot

    packet_status = str(packet.get("status") or "")
    if packet_status in {"READY", "fresh_packet_ready_exists", "actionable_pending_dry_run"}:
        result.update(
            {
                "status": "packet_ready_for_review",
                "next_trigger": "operator_reviews_ready_packet",
                "candidate_symbol": str(packet.get("target_symbol") or ""),
                "candidate_family": str(
                    entry_target.get("strategy_family")
                    or accepted_focus.get("strategy_family")
                    or blocked_focus.get("strategy_family")
                    or watch_summary.get("candidate_family")
                    or ""
                ),
                "candidate_status": packet_status,
                "candidate_reason": str(packet.get("packet_id") or packet.get("summary") or ""),
                "summary": "runtime mitigation packet is ready for operator review",
            }
        )
        snapshot["runtime_mitigation_wait_summary"] = result
        return snapshot

    primary_status = str(mitigation.get("primary_action_status") or "")
    if primary_status == "actionable_now" and entry_target:
        result.update(
            {
                "status": "actionable_target_present",
                "next_trigger": "generate_runtime_mitigation_packet",
                "candidate_symbol": str(entry_target.get("symbol") or ""),
                "candidate_family": str(entry_target.get("strategy_family") or ""),
                "candidate_status": str(entry_target.get("status") or ""),
                "summary": "runtime mitigation is actionable; review target is present",
            }
        )
        snapshot["runtime_mitigation_wait_summary"] = result
        return snapshot

    if entry_target:
        result.update(
            {
                "status": "review_target_present_but_not_actionable",
                "next_trigger": "entry_timing_review_target_status_actionable",
                "candidate_symbol": str(entry_target.get("symbol") or ""),
                "candidate_family": str(entry_target.get("strategy_family") or ""),
                "candidate_status": str(entry_target.get("status") or ""),
                "summary": "entry timing review target exists but is not actionable yet",
            }
        )
        snapshot["runtime_mitigation_wait_summary"] = result
        return snapshot

    if accepted_focus:
        result.update(
            {
                "status": "accepted_candidate_present_without_review_target",
                "next_trigger": "entry_timing_review_target_materializes",
                "candidate_symbol": str(accepted_focus.get("symbol") or ""),
                "candidate_family": str(accepted_focus.get("strategy_family") or ""),
                "candidate_status": str(accepted_focus.get("status") or ""),
                "candidate_reason": str(accepted_focus.get("block_reason") or ""),
                "summary": "accepted candidate exists but no entry timing review target is active yet",
            }
        )
        snapshot["runtime_mitigation_wait_summary"] = result
        return snapshot

    if blocked_focus:
        result.update(
            {
                "status": "blocked_candidate_present",
                "next_trigger": "blocked_candidate_clears_or_actionable_target_appears",
                "candidate_symbol": str(blocked_focus.get("symbol") or ""),
                "candidate_family": str(blocked_focus.get("strategy_family") or ""),
                "candidate_status": str(blocked_focus.get("status") or ""),
                "candidate_reason": str(blocked_focus.get("block_reason") or ""),
                "summary": "blocked lineage candidate is the nearest visible setup; wait until it clears or a review target appears",
            }
        )
        snapshot["runtime_mitigation_wait_summary"] = result
        return snapshot

    if bool(watch_summary.get("fresh")) and str(watch_summary.get("tick_status") or "") == "found_eligible_candidate":
        result.update(
            {
                "status": "watcher_found_candidate_pending_review_target",
                "next_trigger": "entry_timing_review_target_materializes",
                "candidate_symbol": str(watch_summary.get("candidate_symbol") or ""),
                "candidate_family": str(watch_summary.get("candidate_family") or ""),
                "candidate_status": str(watch_summary.get("candidate_status") or "WATCH_ELIGIBLE"),
                "candidate_reason": str(watch_summary.get("summary_line") or watch_summary.get("candidate_reason") or ""),
                "summary": "paper lineage watcher found an eligible candidate but no entry timing review target is active yet",
            }
        )
        snapshot["runtime_mitigation_wait_summary"] = result
        return snapshot

    result.update(
        {
            "status": "no_lineage_candidate_visible",
            "next_trigger": "actionable_entry_timing_target_appears",
            "summary": (
                "no accepted or blocked lineage candidate is visible yet; "
                f"waiting on {str(packet.get('wait_constraint') or mitigation.get('primary_action_constraint') or 'none')}"
            ),
        }
    )
    allowed_sessions = list(session_context.get("allowed_sessions") or [])
    current_session = str(session_context.get("current_session") or "")
    if allowed_sessions and current_session not in set(allowed_sessions):
        result.update(
            {
                "status": "outside_allowed_rollout_session",
                "next_trigger": "allowed_rollout_session_opens",
                "summary": (
                    f"current session {current_session or 'inactive'} is outside the allowed rollout sessions "
                    f"{allowed_sessions}; waiting on {str(packet.get('wait_constraint') or mitigation.get('primary_action_constraint') or 'none')}"
                ),
            }
        )
    snapshot["runtime_mitigation_wait_summary"] = result
    return snapshot


def _run_stage_board(args: argparse.Namespace) -> dict[str, object]:
    stage_file = Path(args.stage_file).resolve()
    latest_board_file = Path(args.latest_board_file).resolve()
    state_file = Path(args.state_file).resolve()
    previous_timeout = ops_stage_board._REQUEST_TIMEOUT_SECONDS
    previous_attempts = ops_stage_board._REQUEST_RETRY_ATTEMPTS
    previous_delay = ops_stage_board._REQUEST_RETRY_BASE_DELAY_SECONDS
    ops_stage_board._REQUEST_TIMEOUT_SECONDS = _STAGE_BOARD_REQUEST_TIMEOUT_SECONDS
    ops_stage_board._REQUEST_RETRY_ATTEMPTS = _STAGE_BOARD_REQUEST_RETRY_ATTEMPTS
    ops_stage_board._REQUEST_RETRY_BASE_DELAY_SECONDS = _STAGE_BOARD_REQUEST_RETRY_BASE_DELAY_SECONDS
    try:
        validation = ops_stage_board._request_json(
            args.base_url,
            "POST",
            "/validation/report",
            query={"symbol": args.symbol, "refresh": False},
        )
        checklist = ops_stage_board._request_json(
            args.base_url,
            "POST",
            "/operations/checklist",
            query={
                "symbol": args.symbol,
                "universe": args.universe,
                "limit": max(1, args.limit),
                "days": max(1, args.days),
                "alert_test_lookback_hours": max(1, args.alert_test_lookback_hours),
                "write_report": False,
            },
        )
        dashboard = ops_stage_board._request_json(
            args.base_url,
            "GET",
            "/execution/operator-dashboard",
            query={
                "symbol": args.symbol,
                "universe": args.universe,
                "portfolio_limit": max(1, args.limit),
                "intent_limit": max(1, args.limit),
                "reconcile_limit": max(1, args.limit),
                "days": max(1, args.days),
            },
        )

        validation_report = validation.get("validation_report") or validation
        payload = ops_stage_board._build_stage_payload(
            validation_report,
            checklist,
            dashboard,
            symbol=args.symbol,
            universe=args.universe,
            days=args.days,
            lineage_sample_scope=args.lineage_sample_scope,
            lineage_families=args.lineage_families,
            lineage_proof_goal_closed_trades=args.lineage_proof_goal_closed_trades,
            lineage_sample_days=args.lineage_sample_days,
        )
        previous_runtime_snapshot = _load_stage_board_fallback(stage_file, latest_board_file, state_file)
        payload = ops_stage_board._reuse_recent_runtime_monitor_fields(payload, previous_runtime_snapshot)
        if dict(payload.get("runtime_signoff_summary") or {}):
            payload = _apply_runtime_signoff_projection(payload)
            payload = _apply_runtime_operator_signoff_summary(payload)
            payload = ops_stage_board._apply_runtime_stage_override(payload)
        payload.pop("stage_board_fallback_used", None)
        payload.pop("stage_board_error", None)
        ops_stage_board._write_stage_file(stage_file, payload)
        output = json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
        _write_text(latest_board_file, output)
        return payload
    except Exception as exc:
        payload = _load_stage_board_fallback(stage_file, latest_board_file, state_file)
        if not payload:
            raise
        payload["generated_at"] = datetime.now(timezone.utc).isoformat()
        payload["stage_board_fallback_used"] = True
        payload["stage_board_error"] = str(exc)
        ops_stage_board._write_stage_file(stage_file, payload)
        output = json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n"
        _write_text(latest_board_file, output)
        return payload
    finally:
        ops_stage_board._REQUEST_TIMEOUT_SECONDS = previous_timeout
        ops_stage_board._REQUEST_RETRY_ATTEMPTS = previous_attempts
        ops_stage_board._REQUEST_RETRY_BASE_DELAY_SECONDS = previous_delay


def _run_notifier(args: argparse.Namespace) -> dict[str, object]:
    stage_file = Path(args.stage_file).resolve()
    state_file = Path(args.state_file).resolve()
    current = notify_stage_change._load_stage(stage_file)
    previous = notify_stage_change._read_json(state_file)
    current = _apply_edge_sample_stall(
        previous,
        current,
        symbol=args.symbol,
        lineage_sample_scope=args.lineage_sample_scope,
        lineage_families=ops_stage_board._family_set(args.lineage_families),
        lineage_sample_days=args.lineage_sample_days,
        threshold_hours=args.edge_sample_stall_hours,
    )
    current = _apply_post_unlock_review_bundle(current, args, previous=previous)
    current = _apply_runtime_reopen_status(current)
    current = _apply_runtime_signoff_summary(current)
    current = _apply_runtime_signoff_approval_focus(
        current,
        symbol=args.symbol,
        base_url=args.base_url,
        previous=previous,
    )
    current = _apply_runtime_signoff_decision(current)
    current = _apply_runtime_signoff_projection(current)
    current = ops_stage_board._apply_runtime_stage_override(current)
    current = _apply_runtime_preflight_summary(current, args, previous=previous)
    current = _apply_runtime_operator_signoff_summary(current)
    current = _apply_runtime_mitigation_summary(current)
    current = _apply_runtime_mitigation_packet(current, args)
    current = _apply_runtime_mitigation_wait_summary(current)
    notify_stage_change._write_json(stage_file, current)
    events = notify_stage_change._collect_events(previous, current)
    result: dict[str, Any] = {
        "stage_file": str(stage_file),
        "state_file": str(state_file),
        "current": current,
        "previous": previous,
        "events": events,
        "notified": False,
        "dry_run": bool(args.dry_run),
    }
    if not events:
        notify_stage_change._write_json(state_file, current)
        return result

    message = notify_stage_change._render_message(current, events)
    result["message"] = message

    if args.dry_run:
        notify_stage_change._write_json(state_file, current)
        return result

    delivery = notify_stage_change._dispatch_stage_notification(
        current,
        message=message,
        webhook_url=args.webhook_url,
    )
    result["delivery"] = delivery
    result["notified"] = bool(delivery.get("delivered"))
    if not result["notified"]:
        result["warning"] = f"discord delivery not completed: {delivery.get('reason')}"
        return result

    result["delivery"] = delivery
    notify_stage_change._write_json(state_file, current)
    return result


def main() -> int:
    args = parse_args()
    _run_stage_board(args)
    notifier_payload = _run_notifier(args)
    print(json.dumps(notifier_payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
