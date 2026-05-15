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
from scripts.operation_report_io import atomic_write_text, parse_report_generated_at
from app.core.config import get_settings
from app.core import operator_surface_contracts as osc
from app.db.models import OrderIntent
from app.db.session import SessionLocal
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


def _resolve_root_path(raw_path: str | Path) -> Path:
    path = Path(raw_path).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


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


def _entry_model_type_allowed(*, entry_model: str, entry_type: str, allowed_entry_models: set[str]) -> bool:
    if not allowed_entry_models:
        return True
    normalized_model = str(entry_model or "").strip().upper()
    normalized_type = str(entry_type or "").strip().upper()
    if not normalized_model and not normalized_type:
        return True
    if normalized_model:
        return normalized_model in allowed_entry_models
    if normalized_type == "LIMIT":
        return "LIMIT" in allowed_entry_models
    if normalized_type == "STOP_MARKET":
        return bool(allowed_entry_models.intersection({"CONFIRM", "SWEEP_CONFIRM"}))
    return normalized_type in allowed_entry_models


def _entry_model_block_contract(*, entry_model: str, entry_type: str, allowed_entry_models: list[str]) -> tuple[str, str, str]:
    allowed_set = {item.strip().upper() for item in allowed_entry_models if item.strip()}
    reason_code = "live_limit_only_entry_required" if allowed_set == {"LIMIT"} else "live_entry_model_not_allowed"
    token = str(entry_model or entry_type or "UNKNOWN").strip().upper() or "UNKNOWN"
    if reason_code == "live_limit_only_entry_required":
        return reason_code, f"entry type {token} is outside the limit-only contract", "limit_only_candidate_appears"
    return (
        reason_code,
        f"entry model/type {token} is outside the current MICRO_LIVE entry-model contract ({','.join(sorted(allowed_set))})",
        "allowed_entry_model_candidate_appears",
    )


def _write_text(path: Path, content: str) -> None:
    atomic_write_text(path, content)


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
            recency = int(parse_report_generated_at(generated_at).timestamp())
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
    family_guard_summary = dict(payload.get("family_cluster_guard_summary") or final_result.get("family_cluster_guard_summary") or {})
    trend_proof_candidate_summary = dict(
        payload.get("trend_proof_candidate_summary") or final_result.get("trend_proof_candidate_summary") or {}
    )
    paper_exit_monitor_summary = dict(payload.get("paper_exit_monitor_summary") or {})
    active_families = [str(item) for item in list(family_guard_summary.get("active_families") or []) if str(item).strip()]
    primary_guard_family = str(active_families[0] if active_families else "").strip().lower()
    primary_guard = dict((family_guard_summary.get("families") or {}).get(primary_guard_family) or {})
    if ops_stage_board._safe_bool(primary_guard.get("loss_cooldown_active", False)):
        primary_guard_reason_code = osc.MITIGATION_GUARD_REASON_RECENT_FAMILY_LOSS
    elif ops_stage_board._safe_bool(primary_guard.get("cluster_guard_active", False)):
        primary_guard_reason_code = osc.MITIGATION_GUARD_REASON_WINDOW_CAP
    else:
        primary_guard_reason_code = ""

    settings = get_settings()
    allowed_symbols = [item.strip() for item in str(settings.auto_trading_micro_live_allowed_symbols or "").split(",") if item.strip()]

    def _iter_objects(node: Any):
        if isinstance(node, dict):
            yield node
            for value in node.values():
                yield from _iter_objects(value)
        elif isinstance(node, list):
            for value in node:
                yield from _iter_objects(value)

    allowed_symbol_families: dict[str, list[str]] = {symbol: [] for symbol in allowed_symbols}
    allowed_symbol_regimes: dict[str, list[str]] = {symbol: [] for symbol in allowed_symbols}
    for item in _iter_objects(payload):
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip()
        if not symbol or symbol not in allowed_symbol_families:
            continue
        family = str(item.get("strategy_family") or item.get("family") or "").strip()
        regime = str(item.get("regime") or "").strip().lower()
        thesis_cluster_id = str(item.get("thesis_cluster_id") or "").strip()
        if not family:
            parts = thesis_cluster_id.split(":")
            if len(parts) >= 3:
                family = parts[2].strip()
        if not regime:
            parts = thesis_cluster_id.split(":")
            if len(parts) >= 2:
                regime = parts[1].strip().lower()
        if not family:
            continue
        existing = allowed_symbol_families[symbol]
        if family not in existing:
            existing.append(family)
        if regime:
            regimes = allowed_symbol_regimes[symbol]
            if regime not in regimes:
                regimes.append(regime)

    allowed_symbol_family_visibility_line = " | ".join(
        f"{symbol}={','.join(families) if families else 'none'}"
        for symbol, families in allowed_symbol_families.items()
    )
    allowed_symbol_regime_visibility_line = " | ".join(
        f"{symbol}={','.join(regimes) if regimes else 'none'}"
        for symbol, regimes in allowed_symbol_regimes.items()
    )
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
        "family_cluster_guard_summary": family_guard_summary,
        "family_guard_active": bool(active_families),
        "family_guard_families": active_families,
        "family_guard_family": primary_guard_family,
        "family_guard_reason_code": primary_guard_reason_code,
        "family_guard_recent_loss_count": int(primary_guard.get("recent_loss_count", 0) or 0),
        "family_guard_recent_window_entry_count": int(primary_guard.get("recent_window_entry_count", 0) or 0),
        "family_guard_summary_line": str(family_guard_summary.get("summary") or ""),
        "trend_proof_candidate_summary": trend_proof_candidate_summary,
        "paper_exit_monitor_summary": paper_exit_monitor_summary,
        "allowed_symbol_family_visibility": allowed_symbol_families,
        "allowed_symbol_family_visibility_line": allowed_symbol_family_visibility_line,
        "allowed_symbol_regime_visibility": allowed_symbol_regimes,
        "allowed_symbol_regime_visibility_line": allowed_symbol_regime_visibility_line,
    }


def _runtime_mitigation_session_context(*, family: str | None) -> dict[str, Any]:
    session = OperatingLockService().current_session(now=datetime.now(timezone.utc)).to_dict()
    policy = RolloutPolicyBootstrap().get(family)
    allowed_sessions = [str(item).strip().lower() for item in list(policy.allowed_sessions or []) if str(item).strip()]
    session_active = ops_stage_board._safe_bool(session.get("active", False))
    current_session = str(session.get("name") or "inactive").lower()
    if (not session_active) or current_session == "inactive":
        current_session = "dead_session"
    return {
        "current_session": current_session,
        "session_active": session_active,
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
        and not ops_stage_board._safe_bool(snapshot.get("edge_sample_gate_ready", False))
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
    review_window_open = ops_stage_board._safe_bool(summary.get("review_window_open", False)) or _post_patch_review_window_open(
        snapshot,
        previous=previous,
    )
    bundle_command = str(summary.get("bundle_review_command") or "")
    if review_window_open and not ops_stage_board._safe_bool(summary.get("review_window_open", False)):
        summary["review_window_open"] = True
        summary["active"] = True
        if not str(summary.get("next_review_step") or "").strip():
            summary["next_review_step"] = "review_validation_and_checklist_before_runtime_reopen"
        snapshot["post_unlock_review_summary"] = summary
    if not review_window_open:
        snapshot["post_unlock_bundle_result"] = {
            "active": ops_stage_board._safe_bool(summary.get("active", False)),
            "executed": False,
            "status": osc.RUNTIME_REOPEN_STATUS_WAITING_FOR_REVIEW_WINDOW,
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
            "status": osc.MITIGATION_PACKET_STATUS_ERROR,
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
    review_window_open = ops_stage_board._safe_bool(
        review_summary.get("review_window_open", False)
    ) or _post_patch_review_window_open(snapshot)
    bundle_status = str(bundle_result.get("status") or "").upper()

    if risk_closed:
        status = osc.RUNTIME_REOPEN_STATUS_WAITING_FOR_OPERATING_LOCK
        ready = False
    elif not review_window_open:
        status = osc.RUNTIME_REOPEN_STATUS_WAITING_FOR_REVIEW_WINDOW
        ready = False
    elif bundle_status == "REVIEW_WINDOW_OPEN_PENDING_BUNDLE":
        status = osc.RUNTIME_REOPEN_STATUS_REVIEW_WINDOW_OPEN_PENDING_BUNDLE
        ready = False
    elif bundle_status == "READY_TO_REOPEN_RUNTIME":
        status = osc.RUNTIME_REOPEN_STATUS_READY_TO_REOPEN_RUNTIME
        ready = True
    elif bundle_status and bundle_status != "WAITING_FOR_REVIEW_WINDOW":
        status = osc.RUNTIME_REOPEN_STATUS_MANUAL_REVIEW_REQUIRED
        ready = False
    else:
        status = osc.RUNTIME_REOPEN_STATUS_REVIEW_WINDOW_OPEN_PENDING_BUNDLE
        ready = False

    snapshot["runtime_reopen_status"] = {
        "status": status,
        "ready": ready,
        "summary": f"runtime_reopen_status={status}",
    }
    return snapshot


def _runtime_signoff_eligible(runtime_status: str) -> bool:
    return str(runtime_status or "").strip().lower() in osc.RUNTIME_REOPEN_ELIGIBLE_STATUSES


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
    if not risk_open or not ops_stage_board._safe_bool(snapshot.get("all_readiness_gates_ready", False)):
        return False
    if ops_stage_board._safe_bool(snapshot.get("post_patch_ready_for_replay_refresh", False)):
        return True
    if ops_stage_board._safe_bool(previous_snapshot.get("post_patch_ready_for_replay_refresh", False)):
        return True
    current_focus = dict(snapshot.get("approval_template_focus") or {})
    previous_focus = dict(previous_snapshot.get("approval_template_focus") or {})
    return ops_stage_board._safe_bool(
        dict(current_focus.get("post_patch_sample_summary") or {}).get("ready_for_replay_refresh", False)
    ) or ops_stage_board._safe_bool(
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
        status = osc.RUNTIME_OPERATOR_SIGNOFF_STATUS_NOT_READY
    elif required_reviews:
        status = osc.RUNTIME_OPERATOR_SIGNOFF_STATUS_MANUAL_SIGNOFF_REQUIRED
    else:
        status = osc.RUNTIME_OPERATOR_SIGNOFF_STATUS_READY_FOR_OPERATOR_SIGNOFF

    approval_review = next(
        (item for item in required_reviews if str(item.get("code") or "") == "approval_template_review"),
        None,
    )
    if not runtime_ready:
        operator_recommendation = osc.RUNTIME_REOPEN_ACTION_WAIT_UNTIL_RUNTIME_READY
        operator_recommendation_reason = "runtime reopen status is not ready yet"
    elif approval_review is not None and str(approval_review.get("worst_scenario_status") or "").upper() == "FAIL":
        operator_recommendation = osc.RUNTIME_REOPEN_ACTION_HOLD_RUNTIME_REOPEN
        operator_recommendation_reason = (
            "replay-derived worst scenario still fails; keep runtime closed unless the operator explicitly accepts the risk"
        )
    elif required_reviews:
        operator_recommendation = osc.RUNTIME_REOPEN_ACTION_MANUAL_SIGNOFF_REQUIRED
        operator_recommendation_reason = "runtime is reopen-ready but required operator review items remain"
    else:
        operator_recommendation = osc.RUNTIME_REOPEN_ACTION_PROCEED_TO_OPERATOR_SIGNOFF
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
        if action == osc.RUNTIME_REOPEN_ACTION_CONDITIONAL_MICRO_LIVE_SIGNOFF:
            signoff["operator_recommendation_reason"] = (
                "legacy replay remains red, but the post-patch mitigation cohort cleared the red thresholds; "
                "limit any reopen to MICRO_LIVE while operator sign-off remains manual"
            )
        elif action == osc.RUNTIME_REOPEN_ACTION_CONDITIONAL_FULL_LIVE_SIGNOFF:
            signoff["operator_recommendation_reason"] = (
                "legacy replay remains red, but the post-patch mitigation cohort cleared the conditional FULL LIVE "
                "thresholds; any reopen still requires explicit operator sign-off"
            )
        elif action == osc.RUNTIME_REOPEN_ACTION_HOLD_RUNTIME_REOPEN:
            signoff["operator_recommendation_reason"] = "replay downside exceeds operating tolerance; keep runtime closed"
        elif action == osc.RUNTIME_REOPEN_ACTION_MANUAL_SIGNOFF_REQUIRED:
            signoff["operator_recommendation_reason"] = "runtime is reopen-ready but required operator review items remain"
        elif action == osc.RUNTIME_REOPEN_ACTION_PROCEED_TO_OPERATOR_SIGNOFF:
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
    required_reviews = [dict(item) for item in list(signoff.get("required_reviews") or [])]
    advisory_reviews = [dict(item) for item in list(signoff.get("advisory_reviews") or [])]
    post_patch = dict(focus.get("post_patch_sample_summary") or {})
    live_eligible_post_patch = dict(focus.get("live_eligible_post_patch_sample_summary") or {})
    gate_summary = dict(signoff.get("runtime_reopen_gate_summary") or {})

    snapshot["approval_template_focus"] = focus
    if signoff.get("approval_template_focus_error"):
        snapshot["approval_template_focus_error"] = str(signoff.get("approval_template_focus_error") or "")
    else:
        snapshot.pop("approval_template_focus_error", None)

    snapshot["runtime_decision"] = decision
    snapshot["runtime_signoff_status"] = str(signoff.get("status") or "")
    snapshot["runtime_operator_recommendation"] = str(signoff.get("operator_recommendation") or "")
    snapshot["required_reviews"] = required_reviews
    snapshot["advisory_reviews"] = advisory_reviews
    snapshot["runtime_required_review_codes"] = [
        str(item.get("code") or "").strip()
        for item in required_reviews
        if str(item.get("code") or "").strip()
    ]
    snapshot["runtime_advisory_review_codes"] = [
        str(item.get("code") or "").strip()
        for item in advisory_reviews
        if str(item.get("code") or "").strip()
    ]
    snapshot["runtime_decision_band"] = str(decision.get("band") or "")
    snapshot["runtime_effective_action"] = str(decision.get("effective_action") or "")
    snapshot["runtime_allowed_reopen_scope"] = str(decision.get("allowed_reopen_scope") or "")
    snapshot["approval_worst"] = str(focus.get("worst_scenario") or "")
    snapshot["approval_worst_status"] = str(focus.get("worst_scenario_status") or "")
    snapshot["post_patch_sample_summary"] = post_patch
    snapshot["live_eligible_post_patch_sample_summary"] = live_eligible_post_patch
    live_execution_post_patch = dict(focus.get("live_execution_post_patch_sample_summary") or {})
    snapshot["live_execution_post_patch_sample_summary"] = live_execution_post_patch
    historical_execution_contract = dict(focus.get("historical_execution_contract_proof_summary") or {})
    snapshot["historical_execution_contract_proof_summary"] = historical_execution_contract
    historical_walk_forward_execution_contract = dict(
        focus.get("historical_walk_forward_execution_contract_proof_summary") or {}
    )
    snapshot["historical_walk_forward_execution_contract_proof_summary"] = historical_walk_forward_execution_contract
    historical_walk_forward_strategy = dict(focus.get("historical_walk_forward_strategy_proof_summary") or {})
    snapshot["historical_walk_forward_strategy_proof_summary"] = historical_walk_forward_strategy
    trend_proof_post_patch = dict(focus.get("trend_proof_post_patch_sample_summary") or {})
    snapshot["trend_proof_post_patch_sample_summary"] = trend_proof_post_patch
    historical_walk_forward_trend = dict(focus.get("historical_walk_forward_trend_proof_summary") or {})
    snapshot["historical_walk_forward_trend_proof_summary"] = historical_walk_forward_trend
    snapshot["runtime_reopen_gate_summary"] = gate_summary
    snapshot["post_patch_closed_trade_count"] = int(post_patch.get("closed_trade_count", 0) or 0)
    snapshot["live_eligible_post_patch_closed_trade_count"] = int(
        live_eligible_post_patch.get("closed_trade_count", 0) or 0
    )
    snapshot["live_execution_post_patch_closed_trade_count"] = int(
        live_execution_post_patch.get("closed_trade_count", 0) or 0
    )
    snapshot["historical_execution_contract_proof_closed_trade_count"] = int(
        historical_execution_contract.get("closed_trade_count", 0) or 0
    )
    snapshot["historical_walk_forward_execution_contract_proof_closed_trade_count"] = int(
        historical_walk_forward_execution_contract.get("closed_trade_count", 0) or 0
    )
    snapshot["historical_walk_forward_strategy_proof_closed_trade_count"] = int(
        historical_walk_forward_strategy.get("closed_trade_count", 0) or 0
    )
    snapshot["trend_proof_post_patch_closed_trade_count"] = int(
        trend_proof_post_patch.get("closed_trade_count", 0) or 0
    )
    snapshot["historical_walk_forward_trend_proof_closed_trade_count"] = int(
        historical_walk_forward_trend.get("closed_trade_count", 0) or 0
    )
    snapshot["runtime_live_contract_scope"] = str(
        live_eligible_post_patch.get("contract_scope") or focus.get("live_contract_scope") or ""
    )
    snapshot["post_patch_target_closed_trades"] = int(post_patch.get("target_closed_trades", 0) or 0)
    snapshot["post_patch_remaining_to_target"] = int(post_patch.get("remaining_to_target", 0) or 0)
    snapshot["post_patch_ready_for_replay_refresh"] = ops_stage_board._safe_bool(
        post_patch.get("ready_for_replay_refresh", False)
    )
    snapshot["runtime_contract_partition_summary"] = _build_runtime_contract_partition_summary(
        post_patch=post_patch,
        live_eligible_post_patch=live_eligible_post_patch,
        live_execution_post_patch=live_execution_post_patch,
        historical_execution_contract=historical_execution_contract,
        historical_walk_forward_execution_contract=historical_walk_forward_execution_contract,
        historical_walk_forward_strategy=historical_walk_forward_strategy,
        trend_proof_post_patch=trend_proof_post_patch,
        historical_walk_forward_trend=historical_walk_forward_trend,
        active_proof_source=str(gate_summary.get("micro_live", {}).get("source_summary_key") or ""),
    )
    snapshot["runtime_live_subset_performance_summary"] = _build_runtime_live_subset_performance_summary(
        post_patch=post_patch,
        live_eligible_post_patch=live_eligible_post_patch,
        live_execution_post_patch=live_execution_post_patch,
        historical_execution_contract=historical_execution_contract,
        historical_walk_forward_execution_contract=historical_walk_forward_execution_contract,
        historical_walk_forward_strategy=historical_walk_forward_strategy,
        trend_proof_post_patch=trend_proof_post_patch,
        historical_walk_forward_trend=historical_walk_forward_trend,
    )
    return snapshot


def _build_runtime_contract_partition_summary(
    *,
    post_patch: dict[str, Any] | None,
    live_eligible_post_patch: dict[str, Any] | None,
    live_execution_post_patch: dict[str, Any] | None,
    historical_execution_contract: dict[str, Any] | None,
    historical_walk_forward_execution_contract: dict[str, Any] | None,
    historical_walk_forward_strategy: dict[str, Any] | None,
    trend_proof_post_patch: dict[str, Any] | None,
    historical_walk_forward_trend: dict[str, Any] | None,
    active_proof_source: str = "",
) -> dict[str, Any]:
    full = dict(post_patch or {})
    live = dict(live_eligible_post_patch or {})
    execution = dict(live_execution_post_patch or {})
    historical = dict(historical_execution_contract or {})
    historical_walk_forward = dict(historical_walk_forward_execution_contract or {})
    strategy_walk_forward = dict(historical_walk_forward_strategy or {})
    trend = dict(trend_proof_post_patch or {})
    walk_forward_trend = dict(historical_walk_forward_trend or {})
    settings = get_settings()
    allowed_symbols = [item.strip() for item in str(settings.auto_trading_micro_live_allowed_symbols or "").split(",") if item.strip()]
    allowed_families = [item.strip() for item in str(settings.auto_trading_micro_live_allowed_families or "").split(",") if item.strip()]
    configured_entry_models = [
        item.strip().upper()
        for item in str(getattr(settings, "auto_trading_micro_live_allowed_entry_models", "") or "").split(",")
        if item.strip()
    ]
    direction_contract: dict[str, list[str]] = {}
    for item in str(getattr(settings, "auto_trading_micro_live_direction_contract", "") or "").split(","):
        token = item.strip()
        if not token or ":" not in token:
            continue
        symbol, raw_directions = token.split(":", 1)
        directions = [direction.strip().upper() for direction in raw_directions.replace("/", "|").split("|") if direction.strip()]
        if symbol.strip() and directions:
            direction_contract[symbol.strip().upper()] = list(dict.fromkeys(directions))
    direction_contract_items = [f"{symbol}:{'|'.join(direction_contract[symbol])}" for symbol in sorted(direction_contract)]
    priority_symbols = [item.strip() for item in str(settings.auto_trading_micro_live_symbol_priority or "").split(",") if item.strip()]
    if not priority_symbols:
        priority_symbols = list(allowed_symbols)
    if allowed_symbols:
        allowed_set = set(allowed_symbols)
        priority_symbols = [item for item in priority_symbols if item in allowed_set]
    live_entry_models = [str(item or "").strip().upper() for item in list(live.get("eligible_entry_models") or []) if str(item or "").strip()]
    if not live_entry_models:
        live_entry_models = list(configured_entry_models)
    research_only_entry_models = [item for item in ["SWEEP_CONFIRM", "CONFIRM"] if item not in set(live_entry_models)]
    preferred_live_symbol = priority_symbols[0] if priority_symbols else ""
    fallback_live_symbols = priority_symbols[1:] if len(priority_symbols) > 1 else []
    summary = (
        f"live uses symbols={','.join(allowed_symbols) or 'all'} families={','.join(allowed_families) or 'none'} "
        f"priority={'>'.join(priority_symbols) or 'none'} "
        f"directions={';'.join(direction_contract_items) or 'all'} "
        f"entry_models={','.join(live_entry_models) or 'none'}; "
        f"research_only_entry_models={','.join(research_only_entry_models) or 'none'}; "
        f"historical_execution={int(historical.get('closed_trade_count', 0) or 0)}; "
        f"historical_walk_forward_execution={int(historical_walk_forward.get('closed_trade_count', 0) or 0)}; "
        f"historical_walk_forward_strategy={int(strategy_walk_forward.get('closed_trade_count', 0) or 0)}; "
        f"trend_proof={int(trend.get('closed_trade_count', 0) or 0)}; "
        f"historical_walk_forward_trend={int(walk_forward_trend.get('closed_trade_count', 0) or 0)}; "
        f"gate_proof={active_proof_source or 'live_eligible_post_patch_sample_summary'}"
    )
    return {
        "active": bool(full or live or execution or historical or historical_walk_forward or trend or walk_forward_trend),
        "live_contract_scope": str(live.get("contract_scope") or ""),
        "live_allowed_symbols": allowed_symbols,
        "live_allowed_families": allowed_families,
        "live_direction_contract": direction_contract,
        "live_allowed_entry_models": live_entry_models,
        "live_symbol_priority": priority_symbols,
        "preferred_live_symbol": preferred_live_symbol,
        "fallback_live_symbols": fallback_live_symbols,
        "research_only_entry_models": research_only_entry_models,
        "full_truth_closed_trade_count": int(full.get("closed_trade_count", 0) or 0),
        "live_eligible_closed_trade_count": int(live.get("closed_trade_count", 0) or 0),
        "live_execution_closed_trade_count": int(execution.get("closed_trade_count", 0) or 0),
        "historical_execution_contract_closed_trade_count": int(historical.get("closed_trade_count", 0) or 0),
        "historical_walk_forward_execution_contract_closed_trade_count": int(
            historical_walk_forward.get("closed_trade_count", 0) or 0
        ),
        "historical_walk_forward_strategy_closed_trade_count": int(
            strategy_walk_forward.get("closed_trade_count", 0) or 0
        ),
        "trend_proof_closed_trade_count": int(trend.get("closed_trade_count", 0) or 0),
        "historical_walk_forward_trend_closed_trade_count": int(
            walk_forward_trend.get("closed_trade_count", 0) or 0
        ),
        "active_gate_proof_source": active_proof_source or "live_eligible_post_patch_sample_summary",
        "summary": summary,
    }


def _build_runtime_live_subset_performance_summary(
    *,
    post_patch: dict[str, Any] | None,
    live_eligible_post_patch: dict[str, Any] | None,
    live_execution_post_patch: dict[str, Any] | None,
    historical_execution_contract: dict[str, Any] | None,
    historical_walk_forward_execution_contract: dict[str, Any] | None,
    historical_walk_forward_strategy: dict[str, Any] | None,
    trend_proof_post_patch: dict[str, Any] | None,
    historical_walk_forward_trend: dict[str, Any] | None,
) -> dict[str, Any]:
    full = dict(post_patch or {})
    live = dict(live_eligible_post_patch or {})
    execution = dict(live_execution_post_patch or {})
    historical = dict(historical_execution_contract or {})
    historical_walk_forward = dict(historical_walk_forward_execution_contract or {})
    strategy_walk_forward = dict(historical_walk_forward_strategy or {})
    trend = dict(trend_proof_post_patch or {})
    walk_forward_trend = dict(historical_walk_forward_trend or {})

    def _pack(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "closed_trade_count": int(item.get("closed_trade_count", 0) or 0),
            "count_basis": str(item.get("count_basis") or "distinct_plan_ids"),
            "win_rate": float(item.get("win_rate", 0.0) or 0.0),
            "ev_r": float(item.get("ev_r", 0.0) or 0.0),
            "profit_factor": item.get("profit_factor"),
            "stop_loss_share": float(item.get("stop_loss_share", 0.0) or 0.0),
            "replay_max_drawdown_r": float(item.get("replay_max_drawdown_r", 0.0) or 0.0),
            "worst_loss_streak": int(item.get("worst_loss_streak", 0) or 0),
        }

    execution_pack = _pack(execution)
    historical_pack = _pack(historical)
    historical_walk_forward_pack = _pack(historical_walk_forward)
    strategy_walk_forward_pack = _pack(strategy_walk_forward)
    live_pack = _pack(live)
    full_pack = _pack(full)
    trend_pack = _pack(trend)
    walk_forward_trend_pack = _pack(walk_forward_trend)
    execution_pf = execution_pack["profit_factor"]
    historical_pf = historical_pack["profit_factor"]
    historical_walk_forward_pf = historical_walk_forward_pack["profit_factor"]
    strategy_walk_forward_pf = strategy_walk_forward_pack["profit_factor"]
    live_pf = live_pack["profit_factor"]
    full_pf = full_pack["profit_factor"]
    trend_pf = trend_pack["profit_factor"]
    walk_forward_trend_pf = walk_forward_trend_pack["profit_factor"]
    summary = (
        f"execution_subset {execution_pack['closed_trade_count']} trades | win_rate={execution_pack['win_rate']:.0%} | "
        f"ev={execution_pack['ev_r']:+.2f}R | pf={(f'{float(execution_pf):.2f}' if execution_pf is not None else 'n/a')} | "
        f"stop_loss={execution_pack['stop_loss_share']:.0%}; "
        f"historical_execution {historical_pack['closed_trade_count']} trades | win_rate={historical_pack['win_rate']:.0%} | "
        f"ev={historical_pack['ev_r']:+.2f}R | pf={(f'{float(historical_pf):.2f}' if historical_pf is not None else 'n/a')} | "
        f"stop_loss={historical_pack['stop_loss_share']:.0%}; "
        f"historical_walk_forward_execution {historical_walk_forward_pack['closed_trade_count']} trades | "
        f"win_rate={historical_walk_forward_pack['win_rate']:.0%} | "
        f"ev={historical_walk_forward_pack['ev_r']:+.2f}R | "
        f"pf={(f'{float(historical_walk_forward_pf):.2f}' if historical_walk_forward_pf is not None else 'n/a')} | "
        f"stop_loss={historical_walk_forward_pack['stop_loss_share']:.0%}; "
        f"historical_walk_forward_strategy {strategy_walk_forward_pack['closed_trade_count']} trades | "
        f"win_rate={strategy_walk_forward_pack['win_rate']:.0%} | "
        f"ev={strategy_walk_forward_pack['ev_r']:+.2f}R | "
        f"pf={(f'{float(strategy_walk_forward_pf):.2f}' if strategy_walk_forward_pf is not None else 'n/a')} | "
        f"stop_loss={strategy_walk_forward_pack['stop_loss_share']:.0%}; "
        f"trend_proof {trend_pack['closed_trade_count']} trades | win_rate={trend_pack['win_rate']:.0%} | "
        f"ev={trend_pack['ev_r']:+.2f}R | pf={(f'{float(trend_pf):.2f}' if trend_pf is not None else 'n/a')} | "
        f"stop_loss={trend_pack['stop_loss_share']:.0%}; "
        f"historical_walk_forward_trend {walk_forward_trend_pack['closed_trade_count']} trades | "
        f"win_rate={walk_forward_trend_pack['win_rate']:.0%} | "
        f"ev={walk_forward_trend_pack['ev_r']:+.2f}R | "
        f"pf={(f'{float(walk_forward_trend_pf):.2f}' if walk_forward_trend_pf is not None else 'n/a')} | "
        f"stop_loss={walk_forward_trend_pack['stop_loss_share']:.0%}; "
        f"proxy_subset {live_pack['closed_trade_count']} trades | win_rate={live_pack['win_rate']:.0%} | "
        f"ev={live_pack['ev_r']:+.2f}R | pf={(f'{float(live_pf):.2f}' if live_pf is not None else 'n/a')} | "
        f"stop_loss={live_pack['stop_loss_share']:.0%}; "
        f"full_truth {full_pack['closed_trade_count']} trades | win_rate={full_pack['win_rate']:.0%} | "
        f"ev={full_pack['ev_r']:+.2f}R | pf={(f'{float(full_pf):.2f}' if full_pf is not None else 'n/a')} | "
        f"stop_loss={full_pack['stop_loss_share']:.0%}"
    )
    return {
        "active": bool(full or live or execution or historical or historical_walk_forward or trend or walk_forward_trend),
        "execution_subset": execution_pack,
        "historical_execution_subset": historical_pack,
        "historical_walk_forward_execution_subset": historical_walk_forward_pack,
        "historical_walk_forward_strategy_subset": strategy_walk_forward_pack,
        "trend_proof_subset": trend_pack,
        "historical_walk_forward_trend_subset": walk_forward_trend_pack,
        "live_subset": live_pack,
        "full_truth": full_pack,
        "summary": summary,
    }


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
        osc.RUNTIME_REOPEN_ACTION_CONDITIONAL_MICRO_LIVE_SIGNOFF,
        osc.RUNTIME_REOPEN_ACTION_CONDITIONAL_FULL_LIVE_SIGNOFF,
        osc.RUNTIME_REOPEN_ACTION_PROCEED_TO_OPERATOR_SIGNOFF,
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
        and str(previous_summary.get("status") or "").upper() not in {"", osc.MITIGATION_PACKET_STATUS_ERROR}
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
            "status": osc.MITIGATION_PACKET_STATUS_ERROR,
            "summary": f"micro-live preflight failed: {exc}",
            "command": command,
            "effective_action": action,
            "post_patch_closed_trade_count": current_closed,
            "fingerprint": fingerprint,
            "computed_at": computed_at,
            "failed_checks": [],
        }
    return snapshot


def _apply_runtime_operator_signoff_summary(
    current: dict[str, Any],
    args: argparse.Namespace | None = None,
) -> dict[str, Any]:
    snapshot = dict(current or {})
    base_url = str(getattr(args, "base_url", "http://127.0.0.1:8000") or "http://127.0.0.1:8000")
    symbol = str(getattr(args, "symbol", snapshot.get("symbol") or "BTCUSDC") or "BTCUSDC")
    universe = str(getattr(args, "universe", "usdc_perp_top30") or "usdc_perp_top30")
    days = int(getattr(args, "days", 30) or 30)
    snapshot["runtime_operator_signoff_summary"] = run_runtime_signoff_review._build_runtime_operator_signoff_summary(
        runtime_decision=dict(snapshot.get("runtime_decision") or {}),
        runtime_preflight_summary=dict(snapshot.get("runtime_preflight_summary") or {}),
        runtime_signoff_summary=dict(snapshot.get("runtime_signoff_summary") or {}),
        runtime_reopen_gate_summary=dict(snapshot.get("runtime_reopen_gate_summary") or {}),
        base_url=base_url,
        symbol=symbol,
        universe=universe,
        days=days,
    )
    return snapshot


def _apply_runtime_actionable_live_candidate_summary(current: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(current or {})
    signoff = dict(snapshot.get("runtime_operator_signoff_summary") or {})
    status = str(signoff.get("status") or "").strip().lower()
    scope = str(signoff.get("allowed_scope") or "").strip()
    if status in {"", "not_applicable"} or scope != osc.RUNTIME_DECISION_SCOPE_MICRO_LIVE_ONLY:
        snapshot["runtime_actionable_live_candidate_summary"] = {
            "active": False,
            "status": "not_applicable",
            "summary": "actionable live candidate review is only relevant during MICRO_LIVE_ONLY sign-off",
        }
        return snapshot

    settings = get_settings()
    allowed_symbols = [item.strip() for item in str(settings.auto_trading_micro_live_allowed_symbols or "").split(",") if item.strip()]
    allowed_families = [item.strip() for item in str(settings.auto_trading_micro_live_allowed_families or "").split(",") if item.strip()]
    allowed_sessions = [item.strip() for item in str(settings.auto_trading_micro_live_allowed_sessions or "").split(",") if item.strip()]
    configured_entry_models = [
        item.strip().upper()
        for item in str(getattr(settings, "auto_trading_micro_live_allowed_entry_models", "") or "").split(",")
        if item.strip()
    ]
    live_entry_models = list(configured_entry_models)
    direction_contract: dict[str, set[str]] = {}
    for item in str(getattr(settings, "auto_trading_micro_live_direction_contract", "") or "").split(","):
        token = item.strip()
        if not token or ":" not in token:
            continue
        symbol, raw_directions = token.split(":", 1)
        directions = {direction.strip().upper() for direction in raw_directions.replace("/", "|").split("|") if direction.strip()}
        if symbol.strip() and directions:
            direction_contract[symbol.strip().upper()] = directions
    candidates = dict(snapshot.get("representative_candidates") or {})
    accepted = dict(candidates.get("accepted") or {})
    blocked = dict(candidates.get("blocked") or {})
    recent_intent_focus = dict(snapshot.get("recent_execution_intent_focus") or {})
    recent_contract_match = dict(snapshot.get("recent_contract_matching_intent_summary") or {})
    contract_history = dict(snapshot.get("runtime_live_contract_history_summary") or {})
    watch_summary = dict(snapshot.get("paper_lineage_watch_summary") or {})
    candidate = accepted or blocked
    candidate_symbol = str(candidate.get("symbol") or "")
    candidate_family = str(candidate.get("strategy_family") or "")
    candidate_entry_model = str(candidate.get("entry_model") or "").strip().upper()
    candidate_entry_type = str(candidate.get("entry_type") or candidate_entry_model or "").strip().upper()
    candidate_direction = str(candidate.get("direction") or "").strip().upper()
    recent_contract_match_count = int(recent_contract_match.get("matching_intent_count", 0) or 0)
    recent_submit_ready_symbol = str(recent_contract_match.get("latest_submit_ready_symbol") or "")
    recent_submit_ready_family = str(recent_contract_match.get("latest_submit_ready_family") or "")
    recent_submit_ready_direction = str(recent_contract_match.get("latest_submit_ready_direction") or "").strip().upper()
    recent_submit_ready_created_at = str(recent_contract_match.get("latest_submit_ready_created_at") or "")
    prefer_recent_submit_ready = bool(recent_contract_match_count > 0 and (recent_submit_ready_symbol or recent_submit_ready_family))
    recent_intent_symbol = str((
        (
            recent_submit_ready_symbol
            if prefer_recent_submit_ready
            else recent_contract_match.get("latest_symbol")
        )
        if recent_contract_match_count > 0
        else recent_intent_focus.get("symbol") or ""
    ) or "")
    recent_intent_family = str((
        (
            recent_submit_ready_family
            if prefer_recent_submit_ready
            else recent_contract_match.get("latest_family")
        )
        if recent_contract_match_count > 0
        else recent_intent_focus.get("strategy_family") or ""
    ) or "")
    recent_intent_entry_model = str((
        (
            recent_contract_match.get("latest_submit_ready_entry_model")
            if prefer_recent_submit_ready
            else recent_contract_match.get("latest_entry_model")
        )
        if recent_contract_match_count > 0
        else recent_intent_focus.get("entry_model") or ""
    ) or "").strip().upper()
    recent_intent_entry_type = str((
        (
            recent_contract_match.get("latest_submit_ready_entry_type")
            if prefer_recent_submit_ready
            else recent_contract_match.get("latest_entry_type")
        )
        if recent_contract_match_count > 0
        else recent_intent_focus.get("entry_type") or recent_intent_entry_model or ""
    ) or "").strip().upper()
    recent_intent_direction = str(
        (
            (
                recent_contract_match.get("latest_submit_ready_direction")
                if prefer_recent_submit_ready
                else recent_contract_match.get("latest_direction")
            )
            if recent_contract_match_count > 0
            else recent_intent_focus.get("direction")
        )
        or ""
    ).strip().upper()
    recent_intent_execution_mode = str((
        (
            recent_contract_match.get("latest_submit_ready_execution_mode")
            if prefer_recent_submit_ready
            else recent_contract_match.get("latest_execution_mode")
        )
        if recent_contract_match_count > 0
        else recent_intent_focus.get("execution_mode") or ""
    ) or "")
    recent_intent_allowed_mode = str((
        (
            recent_contract_match.get("latest_submit_ready_allowed_execution_mode")
            if prefer_recent_submit_ready
            else recent_contract_match.get("latest_allowed_execution_mode")
        )
        if recent_contract_match_count > 0
        else recent_intent_focus.get("allowed_execution_mode") or recent_intent_execution_mode or ""
    ) or "")
    recent_intent_approval_state = str((
        (
            recent_contract_match.get("latest_submit_ready_approval_state")
            if prefer_recent_submit_ready
            else recent_contract_match.get("latest_approval_state")
        )
        if recent_contract_match_count > 0
        else recent_intent_focus.get("approval_state") or ""
    ) or "")
    recent_intent_reason_code = str((
        (
            recent_contract_match.get("latest_submit_ready_reason_code")
            if prefer_recent_submit_ready
            else recent_contract_match.get("latest_reason_code")
        )
        if recent_contract_match_count > 0
        else recent_intent_focus.get("decision_reason_code") or ""
    ) or "")
    historical_contract_match_count = int(contract_history.get("matching_intent_count_total", 0) or 0)
    historical_contract_match_count_30d = int(contract_history.get("matching_intent_count_30d", 0) or 0)
    historical_contract_match_line = str(contract_history.get("symbol_counts_summary") or "")
    watch_visibility = dict(watch_summary.get("allowed_symbol_family_visibility") or {})
    watch_visibility_line = str(watch_summary.get("allowed_symbol_family_visibility_line") or "")
    watch_regime_visibility = dict(watch_summary.get("allowed_symbol_regime_visibility") or {})
    watch_regime_visibility_line = str(watch_summary.get("allowed_symbol_regime_visibility_line") or "")
    reason_code = ""
    summary = ""
    next_trigger = ""
    candidate_status = str(candidate.get("status") or "")
    required_contract = str(signoff.get("contract_scope") or "")
    candidate_requirements = str(signoff.get("candidate_requirements_summary") or "")

    if accepted:
        if allowed_symbols and candidate_symbol and candidate_symbol not in allowed_symbols:
            state = osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_CANDIDATE_OUTSIDE_SYMBOL
            reason_code = "micro_live_symbol_not_allowed"
            summary = f"{candidate_symbol} is accepted but outside the MICRO_LIVE symbol allowlist"
            next_trigger = osc.ACTIONABLE_LIVE_CANDIDATE_TRIGGER_ALLOWED_SYMBOL
        elif allowed_families and candidate_family and candidate_family not in allowed_families:
            state = osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_CANDIDATE_OUTSIDE_FAMILY
            reason_code = "micro_live_family_not_allowed"
            summary = f"{candidate_family} is accepted but outside the MICRO_LIVE family allowlist"
            next_trigger = osc.ACTIONABLE_LIVE_CANDIDATE_TRIGGER_ALLOWED_FAMILY
        elif not _entry_model_type_allowed(
            entry_model=candidate_entry_model,
            entry_type=candidate_entry_type,
            allowed_entry_models=set(live_entry_models),
        ):
            state = osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_CANDIDATE_ENTRY_MODEL_OUTSIDE_CONTRACT
            reason_code, detail, next_trigger = _entry_model_block_contract(
                entry_model=candidate_entry_model,
                entry_type=candidate_entry_type,
                allowed_entry_models=live_entry_models,
            )
            summary = f"{candidate_symbol} is accepted but {detail}"
        elif candidate_symbol and candidate_direction and direction_contract.get(candidate_symbol.upper()) and candidate_direction not in direction_contract.get(candidate_symbol.upper(), set()):
            state = osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_CANDIDATE_DIRECTION_OUTSIDE_CONTRACT
            reason_code = "micro_live_direction_not_allowed"
            summary = f"{candidate_symbol} is accepted but direction {candidate_direction} is outside the current MICRO_LIVE direction contract"
            next_trigger = osc.ACTIONABLE_LIVE_CANDIDATE_TRIGGER_ALLOWED_DIRECTION
        else:
            state = osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_ACTIONABLE_VISIBLE
            summary = f"{candidate_symbol} is accepted and matches the current MICRO_LIVE contract"
            next_trigger = osc.ACTIONABLE_LIVE_CANDIDATE_TRIGGER_OPERATOR_REVIEW
    else:
        state = osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_NONE_VISIBLE
        if recent_intent_symbol or recent_intent_family:
            recent_label = "/".join(
                item for item in [recent_intent_symbol, recent_intent_family, recent_intent_allowed_mode] if item
            )
            if allowed_symbols and recent_intent_symbol and recent_intent_symbol not in allowed_symbols:
                state = osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_RECENT_INTENT_OUTSIDE_SYMBOL
                reason_code = "micro_live_symbol_not_allowed"
                summary = f"latest surfaced intent {recent_label} is outside the MICRO_LIVE symbol allowlist"
                next_trigger = osc.ACTIONABLE_LIVE_CANDIDATE_TRIGGER_ALLOWED_SYMBOL
            elif allowed_families and recent_intent_family and recent_intent_family not in allowed_families:
                state = osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_RECENT_INTENT_OUTSIDE_FAMILY
                reason_code = "micro_live_family_not_allowed"
                summary = f"latest surfaced intent {recent_label} is outside the MICRO_LIVE family allowlist"
                next_trigger = osc.ACTIONABLE_LIVE_CANDIDATE_TRIGGER_ALLOWED_FAMILY
            elif not _entry_model_type_allowed(
                entry_model=recent_intent_entry_model,
                entry_type=recent_intent_entry_type,
                allowed_entry_models=set(live_entry_models),
            ):
                state = osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_RECENT_INTENT_ENTRY_MODEL_OUTSIDE_CONTRACT
                reason_code, detail, next_trigger = _entry_model_block_contract(
                    entry_model=recent_intent_entry_model,
                    entry_type=recent_intent_entry_type,
                    allowed_entry_models=live_entry_models,
                )
                summary = f"latest surfaced intent {recent_label} uses {detail}"
            elif recent_intent_symbol and recent_intent_direction and direction_contract.get(recent_intent_symbol.upper()) and recent_intent_direction not in direction_contract.get(recent_intent_symbol.upper(), set()):
                state = osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_RECENT_INTENT_DIRECTION_OUTSIDE_CONTRACT
                reason_code = "micro_live_direction_not_allowed"
                summary = f"latest surfaced intent {recent_label} uses direction {recent_intent_direction} outside the MICRO_LIVE direction contract"
                next_trigger = osc.ACTIONABLE_LIVE_CANDIDATE_TRIGGER_ALLOWED_DIRECTION
            elif recent_intent_allowed_mode and recent_intent_allowed_mode != "MICRO_LIVE":
                if (
                    recent_intent_allowed_mode == "PAPER"
                    and str(recent_intent_approval_state or "").startswith("APPROVED")
                    and str(recent_intent_reason_code or "") == "submit_ready"
                ):
                    state = osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_RECENT_PAPER_PROMOTION_REQUIRED
                    reason_code = "paper_intent_requires_micro_live_promotion"
                    summary = (
                        f"latest surfaced intent {recent_label} is approved but was created by the PAPER drill; "
                        "operator must create a MICRO_LIVE intent if the underlying plan still matches the limit-only contract"
                    )
                    if recent_submit_ready_symbol:
                        submit_ready_label = "/".join(
                            item for item in [recent_submit_ready_symbol, recent_submit_ready_family, recent_submit_ready_direction] if item
                        )
                        summary = (
                            f"{summary}; last submit_ready limit candidate was {submit_ready_label}"
                            + (f" at {recent_submit_ready_created_at}" if recent_submit_ready_created_at else "")
                        )
                    next_trigger = osc.ACTIONABLE_LIVE_CANDIDATE_TRIGGER_OPERATOR_CREATE_INTENT
                elif recent_intent_allowed_mode == "PAPER" and str(recent_intent_approval_state or "").startswith("APPROVED"):
                    lowered_reason = str(recent_intent_reason_code or "").lower()
                    state = osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_RECENT_CONTRACT_MATCH_NOT_SUBMIT_READY
                    reason_code = recent_intent_reason_code or "micro_live_submit_not_ready"
                    next_trigger = osc.ACTIONABLE_LIVE_CANDIDATE_TRIGGER_SUBMIT_READY_LIMIT
                    if "duplicate" in lowered_reason:
                        state = osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_RECENT_CONTRACT_MATCH_DUPLICATE
                        next_trigger = osc.ACTIONABLE_LIVE_CANDIDATE_TRIGGER_DUPLICATE_CLEARS
                    elif "reentry" in lowered_reason:
                        state = osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_RECENT_CONTRACT_MATCH_REENTRY
                        next_trigger = osc.ACTIONABLE_LIVE_CANDIDATE_TRIGGER_REENTRY_CLEARS
                    summary = (
                        f"latest surfaced intent {recent_label} matches the limit-only contract but is still PAPER-only "
                        f"because decision reason is {recent_intent_reason_code or 'not_submit_ready'}"
                    )
                    if recent_submit_ready_symbol:
                        submit_ready_label = "/".join(
                            item for item in [recent_submit_ready_symbol, recent_submit_ready_family, recent_submit_ready_direction] if item
                        )
                        summary = (
                            f"{summary}; last submit_ready limit candidate was {submit_ready_label}"
                            + (f" at {recent_submit_ready_created_at}" if recent_submit_ready_created_at else "")
                        )
                else:
                    state = osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_RECENT_INTENT_NOT_MICRO_LIVE_READY
                    reason_code = recent_intent_reason_code or "micro_live_execution_mode_not_allowed"
                    summary = f"latest surfaced intent {recent_label} is capped at {recent_intent_allowed_mode} instead of MICRO_LIVE"
                    next_trigger = osc.ACTIONABLE_LIVE_CANDIDATE_TRIGGER_MICRO_LIVE_ALLOWED
            elif recent_intent_approval_state and not recent_intent_approval_state.startswith("APPROVED"):
                state = osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_RECENT_INTENT_NOT_APPROVED
                reason_code = recent_intent_reason_code or "micro_live_intent_not_approved"
                summary = f"latest surfaced intent {recent_label} is not approved for MICRO_LIVE yet"
                next_trigger = osc.ACTIONABLE_LIVE_CANDIDATE_TRIGGER_APPROVED
        if not summary and blocked:
            summary = f"no live-route candidate is visible; nearest surfaced candidate {candidate_symbol}/{candidate_family} remains blocked"
        elif not summary:
            summary = "no live-route candidate is currently visible on the operator surface"
        if blocked and state != osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_NONE_VISIBLE:
            summary = f"{summary}; nearest surfaced candidate {candidate_symbol}/{candidate_family} remains blocked"
        if state == osc.ACTIONABLE_LIVE_CANDIDATE_STATUS_NONE_VISIBLE:
            recent_bits = [item for item in [recent_intent_symbol, recent_intent_family, recent_intent_allowed_mode] if item]
            if recent_bits:
                summary = f"{summary}; latest surfaced intent is {'/'.join(recent_bits)}"
            next_trigger = osc.ACTIONABLE_LIVE_CANDIDATE_TRIGGER_CONTRACT_MATCH
        if recent_contract_match_count <= 0:
            summary = f"{summary}; no recent operator intents matched the MICRO_LIVE contract"
            if historical_contract_match_line:
                summary = f"{summary}; historical contract intent counts {historical_contract_match_line}"
            visible_allowed_families = {
                family
                for families in watch_visibility.values()
                for family in list(families or [])
                if family in set(allowed_families)
            }
            if watch_visibility_line:
                summary = f"{summary}; current watch visibility {watch_visibility_line}"
            if watch_regime_visibility_line:
                summary = f"{summary}; current watch regime {watch_regime_visibility_line}"
            if not visible_allowed_families:
                next_trigger = osc.ACTIONABLE_LIVE_CANDIDATE_TRIGGER_TREND_CONTINUATION_WATCH

    snapshot["runtime_actionable_live_candidate_summary"] = {
        "active": True,
        "status": state,
        "summary": summary,
        "next_trigger": next_trigger,
        "reason_code": reason_code,
        "candidate_symbol": candidate_symbol,
        "candidate_family": candidate_family,
        "candidate_status": candidate_status,
        "candidate_entry_type": candidate_entry_type,
        "candidate_direction": candidate_direction,
        "recent_intent_symbol": recent_intent_symbol,
        "recent_intent_family": recent_intent_family,
        "recent_intent_entry_type": recent_intent_entry_type,
        "recent_intent_direction": recent_intent_direction,
        "recent_intent_execution_mode": recent_intent_execution_mode,
        "recent_intent_allowed_execution_mode": recent_intent_allowed_mode,
        "recent_intent_approval_state": recent_intent_approval_state,
        "recent_intent_reason_code": recent_intent_reason_code,
        "recent_submit_ready_symbol": recent_submit_ready_symbol,
        "recent_submit_ready_family": recent_submit_ready_family,
        "recent_submit_ready_direction": recent_submit_ready_direction,
        "recent_submit_ready_created_at": recent_submit_ready_created_at,
        "recent_contract_match_count": recent_contract_match_count,
        "historical_contract_match_count": historical_contract_match_count,
        "historical_contract_match_count_30d": historical_contract_match_count_30d,
        "historical_contract_match_summary": historical_contract_match_line,
        "watch_allowed_symbol_family_visibility": watch_visibility,
        "watch_allowed_symbol_family_visibility_line": watch_visibility_line,
        "watch_allowed_symbol_regime_visibility": watch_regime_visibility,
        "watch_allowed_symbol_regime_visibility_line": watch_regime_visibility_line,
        "allowed_symbols": allowed_symbols,
        "allowed_families": allowed_families,
        "allowed_sessions": allowed_sessions,
        "required_contract_scope": required_contract,
        "candidate_requirements_summary": candidate_requirements,
    }
    return snapshot


def _apply_runtime_self_heal_summary(current: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(current or {})
    watch_summary = dict(snapshot.get("paper_lineage_watch_summary") or {})
    recent_contract_match = dict(snapshot.get("recent_contract_matching_intent_summary") or {})
    exit_monitor = dict(watch_summary.get("paper_exit_monitor_summary") or {})
    latest_self_heal = dict(recent_contract_match.get("latest_self_heal_summary") or {})
    latest_submit_ready_self_heal = dict(recent_contract_match.get("latest_submit_ready_self_heal_summary") or {})

    stale_cleanup_events = int(exit_monitor.get("stale_cleanup_events", 0) or 0)
    reentry_ignored = ops_stage_board._safe_bool(latest_self_heal.get("stale_paper_reentry_block_ignored", False))
    duplicate_ignored = int(latest_self_heal.get("stale_paper_duplicate_intents_ignored_count", 0) or 0)
    latest_submit_ready_applied = ops_stage_board._safe_bool(latest_submit_ready_self_heal.get("applied", False))
    active = bool(stale_cleanup_events or reentry_ignored or duplicate_ignored or latest_submit_ready_applied)

    summary = (
        f"paper_exit_monitor stale_cleanup={stale_cleanup_events}"
        f" | latest_reentry_ignored={reentry_ignored}"
        f" | latest_duplicate_ignored={duplicate_ignored}"
        f" | last_submit_ready_self_heal={latest_submit_ready_applied}"
    )
    snapshot["runtime_self_heal_summary"] = {
        "active": active,
        "paper_exit_monitor_summary": exit_monitor,
        "latest_contract_match_self_heal_summary": latest_self_heal,
        "latest_submit_ready_self_heal_summary": latest_submit_ready_self_heal,
        "stale_cleanup_events": stale_cleanup_events,
        "latest_reentry_block_ignored": reentry_ignored,
        "latest_duplicate_intents_ignored": duplicate_ignored,
        "latest_submit_ready_self_heal_applied": latest_submit_ready_applied,
        "summary": summary,
    }
    return snapshot


def _apply_runtime_live_contract_history_summary(current: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(current or {})
    signoff = dict(snapshot.get("runtime_operator_signoff_summary") or {})
    scope = str(signoff.get("allowed_scope") or "").strip()
    settings = get_settings()
    allowed_symbols = [item.strip() for item in str(settings.auto_trading_micro_live_allowed_symbols or "").split(",") if item.strip()]
    allowed_families = [item.strip() for item in str(settings.auto_trading_micro_live_allowed_families or "").split(",") if item.strip()]
    configured_entry_models = [
        item.strip().upper()
        for item in str(getattr(settings, "auto_trading_micro_live_allowed_entry_models", "") or "").split(",")
        if item.strip()
    ]
    direction_contract: dict[str, set[str]] = {}
    for item in str(getattr(settings, "auto_trading_micro_live_direction_contract", "") or "").split(","):
        token = item.strip()
        if not token or ":" not in token:
            continue
        symbol, raw_directions = token.split(":", 1)
        directions = {direction.strip().upper() for direction in raw_directions.replace("/", "|").split("|") if direction.strip()}
        if symbol.strip() and directions:
            direction_contract[symbol.strip().upper()] = directions
    summary = {
        "active": bool(allowed_symbols and allowed_families and scope == osc.RUNTIME_DECISION_SCOPE_MICRO_LIVE_ONLY),
        "matching_intent_count_total": 0,
        "matching_intent_count_30d": 0,
        "symbol_counts_total": {},
        "symbol_counts_30d": {},
        "symbol_counts_summary": "",
    }
    if not summary["active"]:
        snapshot["runtime_live_contract_history_summary"] = summary
        return snapshot

    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    db = SessionLocal()
    try:
        rows = (
            db.query(OrderIntent)
            .filter(
                OrderIntent.symbol.in_(allowed_symbols),
                OrderIntent.strategy_family.in_(allowed_families),
            )
            .order_by(OrderIntent.created_at.desc())
            .all()
        )
        symbol_counts_total = {symbol: 0 for symbol in allowed_symbols}
        symbol_counts_30d = {symbol: 0 for symbol in allowed_symbols}
        total = 0
        recent = 0
        allowed_entry_model_set = set(configured_entry_models)
        for intent in rows:
            payload = getattr(intent, "payload", {}) or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    payload = {}
            executable_plan = dict(payload.get("executable_plan") or {})
            entry_type = str(executable_plan.get("entry_type") or "").strip()
            entry_model = str(executable_plan.get("entry_model") or "").strip()
            if not _entry_model_type_allowed(
                entry_model=entry_model,
                entry_type=entry_type,
                allowed_entry_models=allowed_entry_model_set,
            ):
                continue
            symbol = str(getattr(intent, "symbol", "") or "")
            direction = str(executable_plan.get("direction") or payload.get("direction") or "").strip().upper()
            allowed_directions = direction_contract.get(symbol.upper(), set())
            if allowed_directions and direction and direction not in allowed_directions:
                continue
            created_at = getattr(intent, "created_at", None)
            total += 1
            if symbol in symbol_counts_total:
                symbol_counts_total[symbol] += 1
            if created_at:
                created_at_utc = created_at.replace(tzinfo=timezone.utc) if created_at.tzinfo is None else created_at.astimezone(timezone.utc)
                if created_at_utc >= cutoff:
                    recent += 1
                    if symbol in symbol_counts_30d:
                        symbol_counts_30d[symbol] += 1
        summary.update(
            {
                "matching_intent_count_total": total,
                "matching_intent_count_30d": recent,
                "symbol_counts_total": symbol_counts_total,
                "symbol_counts_30d": symbol_counts_30d,
                "symbol_counts_summary": " | ".join(
                    f"{symbol}={symbol_counts_total.get(symbol, 0)}/{symbol_counts_30d.get(symbol, 0)}"
                    for symbol in allowed_symbols
                ),
            }
        )
    finally:
        db.close()
    snapshot["runtime_live_contract_history_summary"] = summary
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
        refreshed_focus = run_runtime_signoff_review._refresh_focus_from_local_artifact(
            previous_focus,
            stage=snapshot,
            symbol=symbol,
            universe=str(snapshot.get("universe") or "usdc_perp_top30"),
            days=int(snapshot.get("days") or 30),
        )
        refreshed_focus["computed_at"] = datetime.now(timezone.utc).isoformat()
        signoff["approval_template_focus"] = refreshed_focus
        signoff["approval_template_focus_cached_at"] = str(
            refreshed_focus.get("computed_at")
            or previous_signoff.get("approval_template_focus_cached_at")
            or previous_focus.get("computed_at")
            or ""
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
            refreshed_focus = run_runtime_signoff_review._refresh_focus_from_local_artifact(
                previous_focus,
                stage=snapshot,
                symbol=symbol,
                universe=str(snapshot.get("universe") or "usdc_perp_top30"),
                days=int(snapshot.get("days") or 30),
            )
            refreshed_focus["computed_at"] = datetime.now(timezone.utc).isoformat()
            signoff["approval_template_focus"] = refreshed_focus
            signoff["approval_template_focus_cached_at"] = str(
                refreshed_focus.get("computed_at")
                or previous_signoff.get("approval_template_focus_cached_at")
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
        if str(item.get("generated_status") or item.get("status") or "") != osc.MITIGATION_PACKET_STATUS_READY:
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
        "available": ops_stage_board._safe_bool(summary.get("available", False)),
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
    if not ops_stage_board._safe_bool(summary.get("available", False)):
        snapshot["runtime_mitigation_packet_result"] = result
        return snapshot
    watch_summary = _load_latest_lineage_watch_summary()
    if (
        status == osc.MITIGATION_ACTION_STATUS_CANDIDATE_REVIEW_PENDING
        and action == "run_entry_timing_split_review"
        and not str(target.get("symbol") or "").strip()
            and ops_stage_board._safe_bool(watch_summary.get("fresh"))
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
        status = osc.MITIGATION_ACTION_STATUS_ACTIONABLE_NOW

    if status != osc.MITIGATION_ACTION_STATUS_ACTIONABLE_NOW or not action or not command:
        result["status"] = osc.MITIGATION_PACKET_STATUS_WAITING
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
                "status": osc.MITIGATION_PACKET_STATUS_FRESH_READY_EXISTS,
                "packet_id": str(fresh_packet.get("packet_id") or ""),
                "target_symbol": str(dict(fresh_packet.get("target_contract") or {}).get("symbol") or target.get("symbol") or ""),
                "target_variant": str(dict(fresh_packet.get("target_contract") or {}).get("preferred_variant") or preferred_variant),
                "summary": "a fresh READY runtime mitigation packet already exists",
            }
        )
        snapshot["runtime_mitigation_packet_result"] = result
        return snapshot

    if bool(getattr(args, "dry_run", False)):
        result["status"] = osc.MITIGATION_PACKET_STATUS_DRY_RUN
        result["summary"] = "runtime mitigation is actionable but packet generation is skipped in dry-run mode"
        snapshot["runtime_mitigation_packet_result"] = result
        return snapshot

    try:
        payload = _run_runtime_mitigation_packet_command(command)
    except Exception as exc:
        result.update(
            {
                "status": osc.MITIGATION_PACKET_STATUS_ERROR,
                "executed": True,
                "summary": f"runtime mitigation packet failed: {exc}",
            }
        )
        snapshot["runtime_mitigation_packet_result"] = result
        return snapshot
    result.update(
        {
            "status": str(payload.get("status") or osc.MITIGATION_PACKET_STATUS_UNKNOWN),
            "executed": True,
            "packet_id": str(payload.get("packet_id") or ""),
            "target_symbol": str(dict(payload.get("target_contract") or {}).get("symbol") or target.get("symbol") or ""),
            "target_variant": str(dict(payload.get("target_contract") or {}).get("preferred_variant") or preferred_variant),
            "summary": f"runtime mitigation packet generated with status={str(payload.get('status') or osc.MITIGATION_PACKET_STATUS_UNKNOWN)}",
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
    snapshot["paper_lineage_watch_summary"] = {
        "available": ops_stage_board._safe_bool(watch_summary.get("available", False)),
        "fresh": ops_stage_board._safe_bool(watch_summary.get("fresh", False)),
        "generated_at": str(watch_summary.get("generated_at") or ""),
        "tick_status": str(watch_summary.get("tick_status") or ""),
        "summary_line": str(watch_summary.get("summary_line") or ""),
        "candidate_symbol": str(watch_summary.get("candidate_symbol") or ""),
        "candidate_family": str(watch_summary.get("candidate_family") or ""),
        "candidate_status": str(watch_summary.get("candidate_status") or ""),
        "family_guard_active": ops_stage_board._safe_bool(watch_summary.get("family_guard_active", False)),
        "family_guard_families": list(watch_summary.get("family_guard_families") or []),
        "family_guard_family": str(watch_summary.get("family_guard_family") or ""),
        "family_guard_reason_code": str(watch_summary.get("family_guard_reason_code") or ""),
        "family_guard_recent_loss_count": int(watch_summary.get("family_guard_recent_loss_count", 0) or 0),
        "family_guard_recent_window_entry_count": int(watch_summary.get("family_guard_recent_window_entry_count", 0) or 0),
        "family_guard_summary_line": str(watch_summary.get("family_guard_summary_line") or ""),
        "trend_proof_candidate_summary": dict(watch_summary.get("trend_proof_candidate_summary") or {}),
        "paper_exit_monitor_summary": dict(watch_summary.get("paper_exit_monitor_summary") or {}),
        "allowed_symbol_family_visibility": dict(watch_summary.get("allowed_symbol_family_visibility") or {}),
        "allowed_symbol_family_visibility_line": str(watch_summary.get("allowed_symbol_family_visibility_line") or ""),
        "allowed_symbol_regime_visibility": dict(watch_summary.get("allowed_symbol_regime_visibility") or {}),
        "allowed_symbol_regime_visibility_line": str(watch_summary.get("allowed_symbol_regime_visibility_line") or ""),
    }

    result: dict[str, Any] = {
        "available": ops_stage_board._safe_bool(mitigation.get("available", False)),
        "status": osc.MITIGATION_WAIT_STATUS_INACTIVE,
        "focus_label": str(mitigation.get("primary_focus_label") or mitigation.get("primary_action_code") or ""),
        "wait_constraint": str(mitigation.get("primary_action_constraint") or ""),
        "next_trigger": "",
        "current_session": str(session_context.get("current_session") or ""),
        "session_active": ops_stage_board._safe_bool(session_context.get("session_active", False)),
        "allowed_sessions": list(session_context.get("allowed_sessions") or []),
        "candidate_symbol": "",
        "candidate_family": "",
        "candidate_status": "",
        "candidate_reason": "",
        "watch_tick_status": str(watch_summary.get("tick_status") or ""),
        "watch_generated_at": str(watch_summary.get("generated_at") or ""),
        "watch_guard_active": ops_stage_board._safe_bool(watch_summary.get("family_guard_active", False)),
        "watch_guard_family": str(watch_summary.get("family_guard_family") or ""),
        "watch_guard_families": list(watch_summary.get("family_guard_families") or []),
        "watch_guard_reason_code": str(watch_summary.get("family_guard_reason_code") or ""),
        "summary": "runtime mitigation wait is inactive",
    }
    if not ops_stage_board._safe_bool(mitigation.get("available", False)):
        snapshot["runtime_mitigation_wait_summary"] = result
        return snapshot

    packet_status = str(packet.get("status") or "")
    if packet_status in {
        osc.MITIGATION_PACKET_STATUS_READY,
        osc.MITIGATION_PACKET_STATUS_FRESH_READY_EXISTS,
        osc.MITIGATION_PACKET_STATUS_DRY_RUN,
    }:
        result.update(
            {
                "status": osc.MITIGATION_WAIT_STATUS_PACKET_READY,
                "next_trigger": osc.MITIGATION_NEXT_TRIGGER_REVIEW_READY_PACKET,
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
    if primary_status == osc.MITIGATION_ACTION_STATUS_ACTIONABLE_NOW and entry_target:
        result.update(
            {
                "status": osc.MITIGATION_WAIT_STATUS_ACTIONABLE_TARGET,
                "next_trigger": osc.MITIGATION_NEXT_TRIGGER_GENERATE_PACKET,
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
                "status": osc.MITIGATION_WAIT_STATUS_REVIEW_TARGET_NOT_ACTIONABLE,
                "next_trigger": osc.MITIGATION_NEXT_TRIGGER_ENTRY_TARGET_ACTIONABLE,
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
                "status": osc.MITIGATION_WAIT_STATUS_ACCEPTED_WITHOUT_REVIEW_TARGET,
                "next_trigger": osc.MITIGATION_NEXT_TRIGGER_ENTRY_TARGET_MATERIALIZES,
                "candidate_symbol": str(accepted_focus.get("symbol") or ""),
                "candidate_family": str(accepted_focus.get("strategy_family") or ""),
                "candidate_status": str(accepted_focus.get("status") or ""),
                "candidate_reason": str(accepted_focus.get("block_reason") or ""),
                "summary": "portfolio accepted context candidate exists, but no entry timing review target is active yet",
            }
        )
        snapshot["runtime_mitigation_wait_summary"] = result
        return snapshot

    if blocked_focus:
        result.update(
            {
                "status": osc.MITIGATION_WAIT_STATUS_BLOCKED_CANDIDATE,
                "next_trigger": osc.MITIGATION_NEXT_TRIGGER_BLOCKED_CLEARS,
                "candidate_symbol": str(blocked_focus.get("symbol") or ""),
                "candidate_family": str(blocked_focus.get("strategy_family") or ""),
                "candidate_status": str(blocked_focus.get("status") or ""),
                "candidate_reason": str(blocked_focus.get("block_reason") or ""),
                "summary": "blocked lineage candidate is the nearest visible setup; wait until it clears or a review target appears",
            }
        )
        snapshot["runtime_mitigation_wait_summary"] = result
        return snapshot

    if ops_stage_board._safe_bool(watch_summary.get("fresh")) and ops_stage_board._safe_bool(
        watch_summary.get("family_guard_active")
    ):
        guard_reason = str(watch_summary.get("family_guard_reason_code") or "")
        next_trigger = osc.MITIGATION_NEXT_TRIGGER_GUARD_CLEARS
        if guard_reason == osc.MITIGATION_GUARD_REASON_RECENT_FAMILY_LOSS:
            next_trigger = osc.MITIGATION_NEXT_TRIGGER_LOSS_COOLDOWN_CLEARS
        elif guard_reason == osc.MITIGATION_GUARD_REASON_WINDOW_CAP:
            next_trigger = osc.MITIGATION_NEXT_TRIGGER_CLUSTER_WINDOW_CLEARS
        result.update(
            {
                "status": osc.MITIGATION_WAIT_STATUS_PAPER_FAMILY_GUARD,
                "next_trigger": next_trigger,
                "candidate_family": str(watch_summary.get("family_guard_family") or ""),
                "candidate_status": guard_reason or "FAMILY_GUARD_ACTIVE",
                "candidate_reason": str(watch_summary.get("family_guard_summary_line") or watch_summary.get("summary_line") or ""),
                "summary": "paper lineage watcher is holding new family samples until the active guard clears",
            }
        )
        snapshot["runtime_mitigation_wait_summary"] = result
        return snapshot

    if (
        ops_stage_board._safe_bool(watch_summary.get("fresh"))
        and str(watch_summary.get("tick_status") or "") == "found_eligible_candidate"
    ):
        result.update(
            {
                "status": osc.MITIGATION_WAIT_STATUS_WATCHER_PENDING_TARGET,
                "next_trigger": osc.MITIGATION_NEXT_TRIGGER_ENTRY_TARGET_MATERIALIZES,
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
            "status": osc.MITIGATION_WAIT_STATUS_NO_LINEAGE,
            "next_trigger": osc.MITIGATION_NEXT_TRIGGER_ACTIONABLE_ENTRY_TARGET,
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
                "status": osc.MITIGATION_WAIT_STATUS_OUTSIDE_SESSION,
                "next_trigger": osc.MITIGATION_NEXT_TRIGGER_ALLOWED_SESSION,
                "summary": (
                    f"current session {current_session or 'inactive'} is outside the allowed rollout sessions "
                    f"{allowed_sessions}; waiting on {str(packet.get('wait_constraint') or mitigation.get('primary_action_constraint') or 'none')}"
                ),
            }
        )
    snapshot["runtime_mitigation_wait_summary"] = result
    return snapshot


def _run_stage_board(args: argparse.Namespace) -> dict[str, object]:
    stage_file = _resolve_root_path(args.stage_file).resolve()
    latest_board_file = _resolve_root_path(args.latest_board_file).resolve()
    state_file = _resolve_root_path(args.state_file).resolve()
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
            payload = _apply_runtime_operator_signoff_summary(payload, args)
            payload = _apply_runtime_live_contract_history_summary(payload)
            payload = _apply_runtime_actionable_live_candidate_summary(payload)
            payload = _apply_runtime_self_heal_summary(payload)
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
    stage_file = _resolve_root_path(args.stage_file).resolve()
    state_file = _resolve_root_path(args.state_file).resolve()
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
    current = _apply_runtime_operator_signoff_summary(current, args)
    current = _apply_runtime_live_contract_history_summary(current)
    current = _apply_runtime_mitigation_summary(current)
    current = _apply_runtime_mitigation_packet(current, args)
    current = _apply_runtime_mitigation_wait_summary(current)
    current = _apply_runtime_actionable_live_candidate_summary(current)
    current = _apply_runtime_self_heal_summary(current)
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
    result["notified"] = notify_stage_change._safe_bool(delivery.get("delivered"))
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
