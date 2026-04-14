#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from datetime import UTC, datetime
import os
from pathlib import Path
import socket
import time
from typing import Any
from urllib import error, parse, request


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STAGE_FILE = ROOT_DIR / "reports/operations/stage_monitor/current_stage.json"
_POST_PATCH_BASELINE_TEXT = os.environ.get("RUNTIME_MITIGATION_BASELINE_TS", "2026-04-10T00:00:00+09:00")
_POST_PATCH_SAMPLE_GOAL = max(int(os.environ.get("RUNTIME_MITIGATION_BASELINE_GOAL", "20")), 1)
_POST_PATCH_MICRO_LIVE_MIN_CLOSED_TRADES = max(
    int(os.environ.get("RUNTIME_MICRO_LIVE_POST_PATCH_MIN_CLOSED_TRADES", "50")),
    1,
)
_POST_PATCH_MICRO_LIVE_MAX_DRAWDOWN_R = float(
    os.environ.get("RUNTIME_MICRO_LIVE_POST_PATCH_MAX_DRAWDOWN_R", "5.0")
)
_POST_PATCH_MICRO_LIVE_MIN_P5_R = float(
    os.environ.get("RUNTIME_MICRO_LIVE_POST_PATCH_MIN_P5_R", "-1.05")
)
_POST_PATCH_MICRO_LIVE_MAX_STOP_LOSS_SHARE = float(
    os.environ.get("RUNTIME_MICRO_LIVE_POST_PATCH_MAX_STOP_LOSS_SHARE", "0.35")
)
_POST_PATCH_MICRO_LIVE_MAX_LOSS_STREAK = int(
    os.environ.get("RUNTIME_MICRO_LIVE_POST_PATCH_MAX_LOSS_STREAK", "5")
)
_POST_PATCH_FULL_LIVE_MIN_CLOSED_TRADES = max(
    int(os.environ.get("RUNTIME_FULL_LIVE_POST_PATCH_MIN_CLOSED_TRADES", "80")),
    1,
)
_POST_PATCH_FULL_LIVE_MAX_DRAWDOWN_R = float(
    os.environ.get("RUNTIME_FULL_LIVE_POST_PATCH_MAX_DRAWDOWN_R", "5.0")
)
_POST_PATCH_FULL_LIVE_MIN_P5_R = float(
    os.environ.get("RUNTIME_FULL_LIVE_POST_PATCH_MIN_P5_R", "-1.0")
)
_POST_PATCH_FULL_LIVE_MAX_STOP_LOSS_SHARE = float(
    os.environ.get("RUNTIME_FULL_LIVE_POST_PATCH_MAX_STOP_LOSS_SHARE", "0.35")
)
_POST_PATCH_FULL_LIVE_MAX_LOSS_STREAK = int(
    os.environ.get("RUNTIME_FULL_LIVE_POST_PATCH_MAX_LOSS_STREAK", "5")
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize the remaining runtime operator sign-off decision."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--stage-file", default=str(DEFAULT_STAGE_FILE))
    parser.add_argument("--report-dir", default="reports/operations/runtime_signoff_reviews")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_ts(value: Any) -> datetime | None:
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


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(item) for item in values)
    if len(ordered) == 1:
        return float(ordered[0])
    clamped = min(max(float(q), 0.0), 1.0)
    index = int(round(clamped * (len(ordered) - 1)))
    return float(ordered[index])


def _max_drawdown(values: list[float]) -> float:
    peak = 0.0
    equity = 0.0
    worst_drawdown = 0.0
    for item in values:
        equity += float(item)
        peak = max(peak, equity)
        worst_drawdown = max(worst_drawdown, peak - equity)
    return float(worst_drawdown)


def _build_post_patch_threshold_breaches(
    post_patch: dict[str, Any] | None,
    *,
    min_closed_trades: int,
    max_drawdown_r: float,
    min_p5_r: float,
    max_stop_loss_share: float,
    max_loss_streak: int,
    code_prefix: str = "post_patch",
) -> list[dict[str, Any]]:
    summary = dict(post_patch or {})
    breached_thresholds: list[dict[str, Any]] = []
    closed_trade_count = int(summary.get("closed_trade_count", 0) or 0)
    replay_max_drawdown_r = float(summary.get("replay_max_drawdown_r", 0.0) or 0.0)
    replay_p5_r = float(summary.get("replay_p5_r", 0.0) or 0.0)
    stop_loss_share = float(summary.get("stop_loss_share", 0.0) or 0.0)
    worst_loss_streak = int(summary.get("worst_loss_streak", 0) or 0)
    if closed_trade_count < min_closed_trades:
        breached_thresholds.append(
            {
                "code": f"{code_prefix}_sample_count_min",
                "value": closed_trade_count,
                "threshold": min_closed_trades,
            }
        )
    if replay_max_drawdown_r >= max_drawdown_r:
        breached_thresholds.append(
            {
                "code": f"{code_prefix}_max_drawdown_red",
                "value": round(replay_max_drawdown_r, 4),
                "threshold": max_drawdown_r,
            }
        )
    if replay_p5_r < min_p5_r:
        breached_thresholds.append(
            {
                "code": f"{code_prefix}_p5_red",
                "value": round(replay_p5_r, 4),
                "threshold": min_p5_r,
            }
        )
    if stop_loss_share >= max_stop_loss_share:
        breached_thresholds.append(
            {
                "code": f"{code_prefix}_stop_loss_share_red",
                "value": round(stop_loss_share, 4),
                "threshold": max_stop_loss_share,
            }
        )
    if worst_loss_streak >= max_loss_streak:
        breached_thresholds.append(
            {
                "code": f"{code_prefix}_loss_streak_red",
                "value": worst_loss_streak,
                "threshold": max_loss_streak,
            }
        )
    return breached_thresholds


def _build_runtime_reopen_gate_summary(
    approval_template_focus: dict[str, Any] | None,
    runtime_decision: dict[str, Any] | None,
) -> dict[str, Any]:
    focus = dict(approval_template_focus or {})
    decision = dict(runtime_decision or {})
    post_patch = dict(focus.get("post_patch_sample_summary") or {})

    def _build_gate(
        *,
        label: str,
        min_closed_trades: int,
        max_drawdown_r: float,
        min_p5_r: float,
        max_stop_loss_share: float,
        max_loss_streak: int,
        code_prefix: str,
    ) -> dict[str, Any]:
        breaches = _build_post_patch_threshold_breaches(
            post_patch,
            min_closed_trades=min_closed_trades,
            max_drawdown_r=max_drawdown_r,
            min_p5_r=min_p5_r,
            max_stop_loss_share=max_stop_loss_share,
            max_loss_streak=max_loss_streak,
            code_prefix=code_prefix,
        )
        closed_trade_count = int(post_patch.get("closed_trade_count", 0) or 0)
        ready = bool(post_patch.get("ready_for_replay_refresh", False)) and not breaches
        remaining_to_min = max(int(min_closed_trades) - closed_trade_count, 0)
        summary = (
            f"{label} ready"
            if ready
            else f"{label} waiting on {', '.join(str(item.get('code') or 'unknown') for item in breaches) or 'post_patch_refresh'}"
        )
        return {
            "label": label,
            "status": "ready" if ready else "not_ready",
            "closed_trade_count": closed_trade_count,
            "min_closed_trades": int(min_closed_trades),
            "remaining_to_min": remaining_to_min,
            "replay_max_drawdown_r": float(post_patch.get("replay_max_drawdown_r", 0.0) or 0.0),
            "replay_p5_r": float(post_patch.get("replay_p5_r", 0.0) or 0.0),
            "stop_loss_share": float(post_patch.get("stop_loss_share", 0.0) or 0.0),
            "worst_loss_streak": int(post_patch.get("worst_loss_streak", 0) or 0),
            "breached_thresholds": breaches,
            "summary": summary,
        }

    return {
        "active_scope": str(decision.get("allowed_reopen_scope") or ""),
        "effective_action": str(decision.get("effective_action") or ""),
        "micro_live": _build_gate(
            label="MICRO_LIVE",
            min_closed_trades=_POST_PATCH_MICRO_LIVE_MIN_CLOSED_TRADES,
            max_drawdown_r=_POST_PATCH_MICRO_LIVE_MAX_DRAWDOWN_R,
            min_p5_r=_POST_PATCH_MICRO_LIVE_MIN_P5_R,
            max_stop_loss_share=_POST_PATCH_MICRO_LIVE_MAX_STOP_LOSS_SHARE,
            max_loss_streak=_POST_PATCH_MICRO_LIVE_MAX_LOSS_STREAK,
            code_prefix="post_patch",
        ),
        "full_live": _build_gate(
            label="FULL_LIVE",
            min_closed_trades=_POST_PATCH_FULL_LIVE_MIN_CLOSED_TRADES,
            max_drawdown_r=_POST_PATCH_FULL_LIVE_MAX_DRAWDOWN_R,
            min_p5_r=_POST_PATCH_FULL_LIVE_MIN_P5_R,
            max_stop_loss_share=_POST_PATCH_FULL_LIVE_MAX_STOP_LOSS_SHARE,
            max_loss_streak=_POST_PATCH_FULL_LIVE_MAX_LOSS_STREAK,
            code_prefix="post_patch_full_live",
        ),
    }


def _build_runtime_operator_signoff_summary(
    *,
    runtime_decision: dict[str, Any] | None,
    runtime_preflight_summary: dict[str, Any] | None,
    runtime_signoff_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    decision = dict(runtime_decision or {})
    preflight = dict(runtime_preflight_summary or {})
    signoff = dict(runtime_signoff_summary or {})
    action = str(decision.get("effective_action") or signoff.get("operator_recommendation") or "")
    scope = str(decision.get("allowed_reopen_scope") or "none")
    preflight_status = str(preflight.get("status") or "not_available")
    required_reviews = [dict(item) for item in list(signoff.get("required_reviews") or [])]
    required_review_codes = [str(item.get("code") or "") for item in required_reviews if str(item.get("code") or "")]

    applicable_actions = {
        "conditional_micro_live_signoff",
        "conditional_full_live_signoff",
        "proceed_to_operator_signoff",
    }
    if action not in applicable_actions:
        return {
            "active": False,
            "status": "not_applicable",
            "effective_action": action,
            "allowed_scope": scope,
            "preflight_status": preflight_status,
            "required_review_codes": required_review_codes,
            "summary": "operator sign-off summary is only applicable once runtime enters a sign-off path",
            "next_step": "wait_for_signoff_path",
        }

    if preflight_status != "READY_FOR_MICRO_LIVE":
        return {
            "active": True,
            "status": "waiting_for_preflight",
            "effective_action": action,
            "allowed_scope": scope,
            "preflight_status": preflight_status,
            "required_review_codes": required_review_codes,
            "summary": "runtime sign-off is waiting for MICRO_LIVE preflight to clear",
            "next_step": "clear_preflight_failures_before_manual_signoff",
        }

    if action == "conditional_micro_live_signoff":
        return {
            "active": True,
            "status": "ready_for_manual_micro_live_signoff",
            "effective_action": action,
            "allowed_scope": scope,
            "preflight_status": preflight_status,
            "required_review_codes": required_review_codes,
            "first_required_review_code": str(required_reviews[0].get("code") or "") if required_reviews else "",
            "summary": "MICRO_LIVE preflight is green; operator may sign off MICRO_LIVE only",
            "next_step": "review_required_warning_and_record_micro_live_signoff",
        }

    if action == "conditional_full_live_signoff":
        return {
            "active": True,
            "status": "ready_for_manual_full_live_signoff",
            "effective_action": action,
            "allowed_scope": scope,
            "preflight_status": preflight_status,
            "required_review_codes": required_review_codes,
            "first_required_review_code": str(required_reviews[0].get("code") or "") if required_reviews else "",
            "summary": "FULL_LIVE preflight is green; operator may sign off FULL_LIVE scope",
            "next_step": "review_required_warning_and_record_full_live_signoff",
        }

    return {
        "active": True,
        "status": "ready_for_operator_signoff",
        "effective_action": action,
        "allowed_scope": scope,
        "preflight_status": preflight_status,
        "required_review_codes": required_review_codes,
        "first_required_review_code": str(required_reviews[0].get("code") or "") if required_reviews else "",
        "summary": "preflight is green and runtime may proceed to final operator sign-off",
        "next_step": "record_operator_signoff",
    }


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _read_stage(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"stage file does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"stage file is invalid: {path}")
    return payload


def _runtime_signoff_command(*, symbol: str, universe: str, days: int) -> str:
    return (
        f"./.venv/bin/python scripts/run_runtime_signoff_review.py "
        f"--symbol {symbol.upper()} --universe {universe} --days {max(int(days), 1)}"
    )


def _request_json(base_url: str, path: str, *, query: dict[str, Any]) -> dict[str, Any]:
    params = parse.urlencode({key: value for key, value in query.items() if value is not None})
    url = f"{base_url.rstrip('/')}{path}"
    if params:
        url = f"{url}?{params}"
    try:
        with request.urlopen(url, timeout=30) as response:
            payload = json.load(response)
    except (error.URLError, TimeoutError, socket.timeout) as exc:
        raise RuntimeError(f"request failed for {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"non-object payload returned for {url}")
    return payload


def _is_retryable_request_error(message: str) -> bool:
    lowered = str(message or "").lower()
    return any(
        token in lowered
        for token in (
            "http error 500",
            "internal server error",
            "database is locked",
            "sqlite busy",
            "timed out",
            "timeout",
            "remote end closed connection without response",
            "remotedisconnected",
        )
    )


def _request_json_with_retry(
    base_url: str,
    path: str,
    *,
    query: dict[str, Any],
    request_json_fn=_request_json,
    attempts: int = 3,
    sleep_seconds: float = 0.25,
) -> dict[str, Any]:
    last_error: RuntimeError | None = None
    for attempt in range(max(int(attempts), 1)):
        try:
            return request_json_fn(base_url, path, query=query)
        except Exception as exc:
            runtime_exc = exc if isinstance(exc, RuntimeError) else RuntimeError(
                f"request failed for {path}: {exc}"
            )
            last_error = runtime_exc
            if not _is_retryable_request_error(str(exc)) or attempt + 1 >= max(int(attempts), 1):
                raise runtime_exc
            time.sleep(sleep_seconds * float(attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"request failed for {path}: exhausted retries without a response")


def _fallback_operator_recommendation(
    *,
    runtime_ready: bool,
    required_reviews: list[dict[str, Any]],
) -> tuple[str, str]:
    if not runtime_ready:
        return "wait_until_runtime_ready", "runtime reopen status is not ready yet"
    approval_review = next(
        (item for item in required_reviews if str(item.get("code") or "") == "approval_template_review"),
        None,
    )
    if approval_review is not None and str(approval_review.get("worst_scenario_status") or "").upper() == "FAIL":
        return (
            "hold_runtime_reopen",
            "replay-derived worst scenario still fails; keep runtime closed unless the operator explicitly accepts the risk",
        )
    if required_reviews:
        return "manual_signoff_required", "runtime is reopen-ready but required operator review items remain"
    return "proceed_to_operator_signoff", "runtime is reopen-ready and no required operator review items remain"


def _runtime_signoff_eligible_status(value: Any) -> bool:
    return str(value or "").strip().lower() in {
        "ready_to_reopen_runtime",
        "manual_review_required",
        "review_window_open_pending_bundle",
    }


def _build_runtime_decision(
    *,
    runtime_ready: bool,
    required_reviews: list[dict[str, Any]],
    approval_template_focus: dict[str, Any] | None,
) -> dict[str, Any]:
    if not runtime_ready:
        return {
            "band": "GREY_WAIT",
            "effective_action": "wait_until_runtime_ready",
            "allowed_reopen_scope": "none",
            "summary": "runtime is not ready yet; do not reopen",
            "breached_thresholds": [],
        }

    approval_review = next(
        (item for item in required_reviews if str(item.get("code") or "") == "approval_template_review"),
        None,
    )
    focus = dict(approval_template_focus or {})
    post_patch = dict(focus.get("post_patch_sample_summary") or {})
    downside = dict(focus.get("downside_profile") or {})
    breached_thresholds: list[dict[str, Any]] = []

    if approval_review is not None and str(approval_review.get("worst_scenario_status") or "").upper() == "FAIL":
        replay_max_drawdown_r = float(focus.get("replay_max_drawdown_r", 0.0) or 0.0)
        replay_p5_r = float(focus.get("replay_p5_r", 0.0) or 0.0)
        stop_loss_share = float(downside.get("stop_loss_share", 0.0) or 0.0)
        worst_loss_streak = int(downside.get("worst_loss_streak", 0) or 0)
        if replay_max_drawdown_r >= 8.0:
            breached_thresholds.append(
                {"code": "max_drawdown_red", "value": round(replay_max_drawdown_r, 4), "threshold": 8.0}
            )
        if replay_p5_r <= -1.0:
            breached_thresholds.append(
                {"code": "p5_red", "value": round(replay_p5_r, 4), "threshold": -1.0}
            )
        if stop_loss_share >= 0.5:
            breached_thresholds.append(
                {"code": "stop_loss_share_red", "value": round(stop_loss_share, 4), "threshold": 0.5}
            )
        if worst_loss_streak >= 7:
            breached_thresholds.append(
                {"code": "loss_streak_red", "value": worst_loss_streak, "threshold": 7}
            )

        if breached_thresholds:
            micro_live_post_patch_breaches = _build_post_patch_threshold_breaches(
                post_patch,
                min_closed_trades=_POST_PATCH_MICRO_LIVE_MIN_CLOSED_TRADES,
                max_drawdown_r=_POST_PATCH_MICRO_LIVE_MAX_DRAWDOWN_R,
                min_p5_r=_POST_PATCH_MICRO_LIVE_MIN_P5_R,
                max_stop_loss_share=_POST_PATCH_MICRO_LIVE_MAX_STOP_LOSS_SHARE,
                max_loss_streak=_POST_PATCH_MICRO_LIVE_MAX_LOSS_STREAK,
                code_prefix="post_patch",
            )
            full_live_post_patch_breaches = _build_post_patch_threshold_breaches(
                post_patch,
                min_closed_trades=_POST_PATCH_FULL_LIVE_MIN_CLOSED_TRADES,
                max_drawdown_r=_POST_PATCH_FULL_LIVE_MAX_DRAWDOWN_R,
                min_p5_r=_POST_PATCH_FULL_LIVE_MIN_P5_R,
                max_stop_loss_share=_POST_PATCH_FULL_LIVE_MAX_STOP_LOSS_SHARE,
                max_loss_streak=_POST_PATCH_FULL_LIVE_MAX_LOSS_STREAK,
                code_prefix="post_patch_full_live",
            )
            if bool(post_patch.get("ready_for_replay_refresh", False)) and not full_live_post_patch_breaches:
                return {
                    "band": "AMBER_CONDITIONAL",
                    "effective_action": "conditional_full_live_signoff",
                    "allowed_reopen_scope": "MICRO_LIVE_OR_LIVE",
                    "summary": (
                        "legacy replay downside remains red, but the post-patch mitigation cohort met the "
                        "conditional FULL LIVE thresholds"
                    ),
                    "breached_thresholds": breached_thresholds,
                    "post_patch_breached_thresholds": [],
                    "post_patch_override_active": True,
                }
            if bool(post_patch.get("ready_for_replay_refresh", False)) and not micro_live_post_patch_breaches:
                return {
                    "band": "AMBER_CONDITIONAL",
                    "effective_action": "conditional_micro_live_signoff",
                    "allowed_reopen_scope": "MICRO_LIVE_ONLY",
                    "summary": (
                        "legacy replay downside remains red, but the post-patch mitigation cohort met the "
                        "conditional MICRO_LIVE thresholds"
                    ),
                    "breached_thresholds": breached_thresholds,
                    "post_patch_breached_thresholds": [],
                    "post_patch_override_active": True,
                }
            return {
                "band": "RED_HOLD",
                "effective_action": "hold_runtime_reopen",
                "allowed_reopen_scope": "none",
                "summary": "replay downside exceeds operating tolerance; keep runtime closed",
                "breached_thresholds": breached_thresholds,
                "post_patch_breached_thresholds": micro_live_post_patch_breaches if bool(post_patch) else [],
                "post_patch_override_active": False,
            }
        return {
            "band": "AMBER_CONDITIONAL",
            "effective_action": "conditional_micro_live_signoff",
            "allowed_reopen_scope": "MICRO_LIVE_ONLY",
            "summary": "approval-template warning remains, but replay downside is below the red operating thresholds",
            "breached_thresholds": [],
            "post_patch_breached_thresholds": [],
            "post_patch_override_active": False,
        }

    if required_reviews:
        return {
            "band": "AMBER_CONDITIONAL",
            "effective_action": "manual_signoff_required",
            "allowed_reopen_scope": "MICRO_LIVE_ONLY",
            "summary": "runtime is reopen-ready but required operator review items remain",
            "breached_thresholds": [],
            "post_patch_breached_thresholds": [],
            "post_patch_override_active": False,
        }

    return {
        "band": "GREEN_PROCEED",
        "effective_action": "proceed_to_operator_signoff",
        "allowed_reopen_scope": "MICRO_LIVE_OR_LIVE",
        "summary": "runtime is reopen-ready and no required operator review items remain",
        "breached_thresholds": [],
        "post_patch_breached_thresholds": [],
        "post_patch_override_active": False,
    }


def _apply_runtime_decision(payload: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(payload or {})
    runtime_reopen = dict(enriched.get("runtime_reopen_status") or {})
    required_reviews = [dict(item) for item in list(enriched.get("required_reviews") or [])]
    approval_template_focus = dict(enriched.get("approval_template_focus") or {})
    decision = _build_runtime_decision(
        runtime_ready=_runtime_signoff_eligible_status(runtime_reopen.get("status"))
        or bool(runtime_reopen.get("ready", False)),
        required_reviews=required_reviews,
        approval_template_focus=approval_template_focus,
    )
    enriched["runtime_decision"] = decision
    action = str(decision.get("effective_action") or "")
    if action:
        enriched["operator_recommendation"] = action
        if action == "conditional_micro_live_signoff":
            enriched["operator_recommendation_reason"] = (
                "legacy replay remains red, but the post-patch mitigation cohort cleared the red thresholds; "
                "limit any reopen to MICRO_LIVE while operator sign-off remains manual"
            )
        elif action == "conditional_full_live_signoff":
            enriched["operator_recommendation_reason"] = (
                "legacy replay remains red, but the post-patch mitigation cohort cleared the conditional FULL LIVE "
                "thresholds; any reopen still requires explicit operator sign-off"
            )
        elif action == "hold_runtime_reopen":
            enriched["operator_recommendation_reason"] = "replay downside exceeds operating tolerance; keep runtime closed"
        elif action == "manual_signoff_required":
            enriched["operator_recommendation_reason"] = "runtime is reopen-ready but required operator review items remain"
        elif action == "proceed_to_operator_signoff":
            enriched["operator_recommendation_reason"] = "runtime is reopen-ready and no required operator review items remain"
    enriched["runtime_reopen_gate_summary"] = _build_runtime_reopen_gate_summary(
        enriched.get("approval_template_focus"),
        enriched.get("runtime_decision"),
    )
    return enriched


def _approval_template_focus_symbol(stage: dict[str, Any], *, symbol: str) -> str:
    selected_trial_run_id = str(stage.get("selected_trial_run_id") or "")
    lineage_sample = dict(stage.get("lineage_sample_summary") or {})
    scope = str(lineage_sample.get("scope") or "")
    if selected_trial_run_id.startswith("LINEAGE_GLOBAL") or scope == "family_global":
        return "LINEAGE_GLOBAL"
    return symbol.upper()


def _load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _build_approval_template_downside_profile(*, artifact_path: str) -> dict[str, Any] | None:
    artifact_rel = str(artifact_path or "").strip()
    if not artifact_rel:
        return None
    artifact = _load_json_file(ROOT_DIR / artifact_rel)
    if not artifact:
        return None

    trade_rows = list(artifact.get("trade_rows") or [])
    if not trade_rows:
        return None

    plan_to_meta: dict[str, dict[str, Any]] = {}
    for path_str in list(artifact.get("input_artifact_paths") or []):
        batch = _load_json_file(ROOT_DIR / str(path_str))
        if not batch:
            continue
        for row in list(batch.get("trade_rows") or []):
            plan_to_meta[str(row.get("plan_id") or "")] = dict(row)

    total_trades = len(trade_rows)
    stop_loss_count = 0
    regime_counts: Counter[str] = Counter()
    loss_timestamp_counts: Counter[str] = Counter()
    long_hold_trade_count = 0
    long_hold_loss_count = 0
    current_loss_streak = 0
    worst_loss_streak = 0
    current_loss_block_sum = 0.0
    worst_loss_block_sum = 0.0
    worst_loss_block_len = 0
    negative_r_by_symbol: dict[str, float] = defaultdict(float)
    negative_trade_count_by_symbol: Counter[str] = Counter()
    entry_anchor_source_counts: Counter[str] = Counter()
    confirm_named_loss_count = 0
    loss_held_bars: list[int] = []

    for row in trade_rows:
        replayed_r = float(row.get("replayed_realized_r", 0.0) or 0.0)
        exit_reason = str(row.get("final_exit_reason") or "unknown")
        meta = dict(plan_to_meta.get(str(row.get("plan_id") or ""), {}) or {})
        symbol = str(meta.get("symbol") or "UNKNOWN")
        regime = str(meta.get("regime") or "unknown")
        held_bars = int(meta.get("final_exit_held_bars", 0) or 0)
        regime_counts[regime] += 1
        if held_bars > 240:
            long_hold_trade_count += 1
        if exit_reason == "stop_loss":
            stop_loss_count += 1
        if replayed_r < 0:
            current_loss_streak += 1
            current_loss_block_sum += replayed_r
            worst_loss_streak = max(worst_loss_streak, current_loss_streak)
            if current_loss_block_sum < worst_loss_block_sum:
                worst_loss_block_sum = current_loss_block_sum
                worst_loss_block_len = current_loss_streak
            negative_r_by_symbol[symbol] += replayed_r
            negative_trade_count_by_symbol[symbol] += 1
            loss_timestamp_counts[str(row.get("closed_ts") or "")] += 1
            entry_anchor_source_counts[str(meta.get("entry_anchor_source") or "unknown")] += 1
            if "confirm" in str(row.get("plan_id") or ""):
                confirm_named_loss_count += 1
            loss_held_bars.append(held_bars)
            if held_bars > 240:
                long_hold_loss_count += 1
        else:
            current_loss_streak = 0
            current_loss_block_sum = 0.0

    top_loss_symbols = [
        {
            "symbol": symbol,
            "negative_r": round(total_negative_r, 4),
            "loss_trade_count": int(negative_trade_count_by_symbol.get(symbol, 0) or 0),
        }
        for symbol, total_negative_r in sorted(negative_r_by_symbol.items(), key=lambda item: item[1])[:3]
    ]

    top_loss_waves = [
        {
            "closed_ts": closed_ts,
            "loss_trade_count": int(count or 0),
        }
        for closed_ts, count in loss_timestamp_counts.most_common(3)
    ]
    dominant_regime = regime_counts.most_common(1)[0][0] if regime_counts else "unknown"
    loss_trade_count = int(sum(negative_trade_count_by_symbol.values()) or 0)
    confirm_named_loss_share = round(float(confirm_named_loss_count) / float(loss_trade_count), 4) if loss_trade_count else 0.0
    top_loss_wave = dict(top_loss_waves[0] or {}) if top_loss_waves else {}
    top_loss_wave_count = int(top_loss_wave.get("loss_trade_count", 0) or 0)
    top_loss_wave_share_of_losses = round(
        float(top_loss_wave_count) / float(loss_trade_count),
        4,
    ) if loss_trade_count else 0.0
    long_hold_loss_share = round(float(long_hold_loss_count) / float(loss_trade_count), 4) if loss_trade_count else 0.0
    dominant_entry_anchor_source = entry_anchor_source_counts.most_common(1)[0][0] if entry_anchor_source_counts else "unknown"
    median_loss_held_bars = 0.0
    p75_loss_held_bars = 0
    max_loss_held_bars = 0
    if loss_held_bars:
        ordered_loss_held_bars = sorted(loss_held_bars)
        median_loss_held_bars = round(float(ordered_loss_held_bars[len(ordered_loss_held_bars) // 2]), 4)
        p75_loss_held_bars = int(ordered_loss_held_bars[int(0.75 * (len(ordered_loss_held_bars) - 1))] or 0)
        max_loss_held_bars = int(max(ordered_loss_held_bars) or 0)

    mitigation_focus: list[dict[str, Any]] = []
    if dominant_regime == "range" and stop_loss_count >= max(3, int(total_trades * 0.4)):
        mitigation_focus.append(
            {
                "code": "range_entry_timing_review",
                "summary": "range regime dominates the replay losses; review sweep_reversal entry timing before reopening runtime",
            }
        )
    if long_hold_loss_share >= 0.75:
        mitigation_focus.append(
            {
                "code": "shadow_fail_fast_review",
                "summary": "most replay losses are long-held stop-outs; prioritize fail_fast_no_reaction_within_3_bars as a shadow review",
            }
        )
    if top_loss_wave_share_of_losses >= 0.5:
        mitigation_focus.append(
            {
                "code": "loss_wave_cluster_review",
                "summary": "losses cluster in the same close wave; review cluster throttling and same-window exposure before reopening runtime",
            }
        )

    primary_failure_mode = "general_replay_drawdown"
    primary_failure_summary = "replay losses remain elevated and should be reviewed before reopening runtime"
    if (
        dominant_regime == "range"
        and long_hold_loss_share >= 0.75
        and top_loss_wave_share_of_losses >= 0.5
        and confirm_named_loss_share >= 0.7
    ):
        primary_failure_mode = "range_confirm_entry_loss_wave"
        primary_failure_summary = (
            "range regime losses are dominated by confirm-entry stop-outs that stay open too long and cluster in the same close wave"
        )
    elif dominant_regime == "range" and long_hold_loss_share >= 0.75 and top_loss_wave_share_of_losses >= 0.5:
        primary_failure_mode = "range_late_entry_loss_wave"
        primary_failure_summary = (
            "range regime losses are dominated by long-held stop-outs that cluster in the same close wave"
        )
    elif dominant_regime == "range" and long_hold_loss_share >= 0.75:
        primary_failure_mode = "range_long_hold_stopouts"
        primary_failure_summary = "range regime losses are dominated by long-held stop-outs"
    elif top_loss_wave_share_of_losses >= 0.5 and stop_loss_count >= max(2, int(total_trades * 0.4)):
        primary_failure_mode = "clustered_stop_loss_wave"
        primary_failure_summary = "losses cluster in the same wave and produce a long stop-loss streak"
    elif stop_loss_count >= max(3, int(total_trades * 0.5)):
        primary_failure_mode = "stop_loss_heavy_distribution"
        primary_failure_summary = "too many replay trades finish at stop-loss under the worst-case replay scenario"

    return {
        "trade_count": total_trades,
        "dominant_regime": dominant_regime,
        "stop_loss_count": stop_loss_count,
        "stop_loss_share": round(float(stop_loss_count) / float(total_trades), 4) if total_trades else 0.0,
        "loss_trade_count": loss_trade_count,
        "confirm_named_loss_count": confirm_named_loss_count,
        "confirm_named_loss_share": confirm_named_loss_share,
        "long_hold_trade_count": long_hold_trade_count,
        "long_hold_loss_count": long_hold_loss_count,
        "long_hold_loss_share": long_hold_loss_share,
        "median_loss_held_bars": median_loss_held_bars,
        "p75_loss_held_bars": p75_loss_held_bars,
        "max_loss_held_bars": max_loss_held_bars,
        "dominant_entry_anchor_source": dominant_entry_anchor_source,
        "worst_loss_streak": worst_loss_streak,
        "worst_loss_block_sum_r": round(worst_loss_block_sum, 4),
        "worst_loss_block_len": worst_loss_block_len,
        "top_loss_symbols": top_loss_symbols,
        "top_loss_waves": top_loss_waves,
        "top_loss_wave_share_of_losses": top_loss_wave_share_of_losses,
        "primary_failure_mode": primary_failure_mode,
        "primary_failure_summary": primary_failure_summary,
        "mitigation_focus": mitigation_focus,
    }


def _split_review_command(*, symbol: str, universe: str, days: int, action: str) -> str:
    return (
        f"./.venv/bin/python scripts/run_split_review_followup.py "
        f"--symbol {symbol.upper()} --universe {universe} --days {max(int(days), 1)} --action {action}"
    )


def _build_mitigation_review_summary(
    *,
    downside_profile: dict[str, Any] | None,
    stage: dict[str, Any],
    symbol: str,
    universe: str,
    days: int,
) -> dict[str, Any] | None:
    downside = dict(downside_profile or {})
    focus_items = list(downside.get("mitigation_focus") or [])
    if not focus_items:
        return None

    entry_target = dict(stage.get("entry_timing_review_target") or {})
    items: list[dict[str, Any]] = []
    for focus in focus_items:
        code = str(focus.get("code") or "").strip()
        summary = str(focus.get("summary") or "").strip()
        item: dict[str, Any] = {
            "code": code,
            "summary": summary,
            "review_mode": "research_only",
            "status": "research_only",
            "current_constraint": "",
            "command": "",
        }
        if code == "range_entry_timing_review":
            command = str(entry_target.get("followup_command") or "").strip() or _split_review_command(
                symbol=symbol,
                universe=universe,
                days=days,
                action="run_entry_timing_split_review",
            )
            has_target = bool(entry_target.get("symbol"))
            item.update(
                {
                    "review_mode": "live_split_review",
                    "status": "actionable_now" if has_target else "candidate_review_pending",
                    "current_constraint": "" if has_target else "waiting_for_actionable_entry_timing_target",
                    "command": command,
                }
            )
        elif code == "shadow_fail_fast_review":
            item.update(
                {
                    "review_mode": "shadow_only",
                    "status": "deferred_by_experiment_sequence",
                    "current_constraint": "exit_optimization_live_change_not_allowed",
                    "shadow_hypothesis": "fail_fast_no_reaction_within_3_bars",
                }
            )
        elif code == "loss_wave_cluster_review":
            item.update(
                {
                    "review_mode": "research_only",
                    "status": "manual_operator_review",
                    "current_constraint": "operator_review_before_cluster_policy_change",
                    "command": _runtime_signoff_command(symbol=symbol, universe=universe, days=days),
                }
            )
        items.append(item)

    primary = next(
        (
            item
            for item in items
            if str(item.get("status") or "") in {"actionable_now", "candidate_review_pending"}
        ),
        items[0],
    )
    return {
        "primary_action_code": str(primary.get("code") or ""),
        "primary_action_status": str(primary.get("status") or ""),
        "primary_action_command": str(primary.get("command") or ""),
        "actionable_now_count": sum(1 for item in items if str(item.get("status") or "") == "actionable_now"),
        "candidate_pending_count": sum(
            1 for item in items if str(item.get("status") or "") == "candidate_review_pending"
        ),
        "deferred_count": sum(
            1 for item in items if str(item.get("status") or "") == "deferred_by_experiment_sequence"
        ),
        "research_only_count": sum(
            1 for item in items if str(item.get("status") or "") in {"research_only", "manual_operator_review"}
        ),
        "items": items,
    }


def _build_mitigation_execution_plan(
    *,
    priority_summary: dict[str, Any] | None,
    mitigation_review_summary: dict[str, Any] | None,
) -> dict[str, Any] | None:
    priority = dict(priority_summary or {})
    review_summary = dict(mitigation_review_summary or {})
    items = list(review_summary.get("items") or [])
    if not priority or not items:
        return None

    item_by_code = {str(item.get("code") or ""): dict(item) for item in items}
    review_code_map = {
        "confirm_entry_tighten": "range_entry_timing_review",
        "non_confirm_fail_fast": "shadow_fail_fast_review",
        "confirm_fail_fast": "shadow_fail_fast_review",
        "loss_wave_cluster": "loss_wave_cluster_review",
    }
    label_map = {
        "confirm_entry_tighten": "confirm 진입 타이밍 축소",
        "non_confirm_fail_fast": "non-confirm fail-fast",
        "confirm_fail_fast": "confirm fail-fast",
        "loss_wave_cluster": "loss wave cluster 검토",
    }

    ordered_steps: list[dict[str, Any]] = []
    for step_code in list(priority.get("ordered_focus") or []):
        mapped_code = str(review_code_map.get(str(step_code), "") or "")
        item = dict(item_by_code.get(mapped_code) or {})
        if not item:
            continue
        ordered_steps.append(
            {
                "focus_code": str(step_code),
                "focus_label": str(label_map.get(str(step_code), step_code)),
                "review_code": mapped_code,
                "review_mode": str(item.get("review_mode") or ""),
                "status": str(item.get("status") or ""),
                "command": str(item.get("command") or ""),
                "constraint": str(item.get("current_constraint") or ""),
            }
        )

    if not ordered_steps:
        return None

    primary_step = dict(ordered_steps[0])
    secondary_step = dict(ordered_steps[1]) if len(ordered_steps) > 1 else {}
    return {
        "primary_focus_code": str(primary_step.get("focus_code") or ""),
        "primary_focus_label": str(primary_step.get("focus_label") or ""),
        "primary_status": str(primary_step.get("status") or ""),
        "primary_command": str(primary_step.get("command") or ""),
        "secondary_focus_code": str(secondary_step.get("focus_code") or ""),
        "secondary_focus_label": str(secondary_step.get("focus_label") or ""),
        "secondary_status": str(secondary_step.get("status") or ""),
        "secondary_command": str(secondary_step.get("command") or ""),
        "ordered_steps": ordered_steps,
    }


def _build_confirm_loss_cluster_summary(
    *,
    artifact_path: str,
) -> dict[str, Any] | None:
    artifact_rel = str(artifact_path or "").strip()
    if not artifact_rel:
        return None
    artifact = _load_json_file(ROOT_DIR / artifact_rel)
    if not artifact:
        return None

    plan_to_meta: dict[str, dict[str, Any]] = {}
    for path_str in list(artifact.get("input_artifact_paths") or []):
        batch = _load_json_file(ROOT_DIR / str(path_str))
        if not batch:
            continue
        for row in list(batch.get("trade_rows") or []):
            plan_to_meta[str(row.get("plan_id") or "")] = dict(row)

    confirm_losses: list[dict[str, Any]] = []
    for row in list(artifact.get("trade_rows") or []):
        replayed_r = float(row.get("replayed_realized_r", 0.0) or 0.0)
        plan_id = str(row.get("plan_id") or "")
        if replayed_r >= 0 or "confirm" not in plan_id:
            continue
        meta = dict(plan_to_meta.get(plan_id, {}) or {})
        confirm_losses.append({**meta, **dict(row)})

    if not confirm_losses:
        return None

    symbol_counts: Counter[str] = Counter()
    symbol_negative_r: defaultdict[str, float] = defaultdict(float)
    closed_ts_counts: Counter[str] = Counter()
    wave_negative_r: defaultdict[str, float] = defaultdict(float)
    held_bars_values: list[int] = []
    symbol_held_bars: defaultdict[str, list[int]] = defaultdict(list)
    wave_symbols: defaultdict[str, Counter[str]] = defaultdict(Counter)
    held_bar_bands = {
        "over_240": 0,
        "over_1000": 0,
        "over_2000": 0,
    }
    for row in confirm_losses:
        symbol = str(row.get("symbol") or "UNKNOWN")
        replayed_r = float(row.get("replayed_realized_r", 0.0) or 0.0)
        closed_ts = str(row.get("closed_ts") or "")
        held_bars = int(row.get("final_exit_held_bars", 0) or 0)
        symbol_counts[symbol] += 1
        symbol_negative_r[symbol] += replayed_r
        closed_ts_counts[closed_ts] += 1
        wave_negative_r[closed_ts] += replayed_r
        held_bars_values.append(held_bars)
        symbol_held_bars[symbol].append(held_bars)
        wave_symbols[closed_ts][symbol] += 1
        if held_bars > 240:
            held_bar_bands["over_240"] += 1
        if held_bars > 1000:
            held_bar_bands["over_1000"] += 1
        if held_bars > 2000:
            held_bar_bands["over_2000"] += 1

    def _median(values: list[int]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        return round(float(ordered[len(ordered) // 2]), 4)

    def _p75(values: list[int]) -> int:
        if not values:
            return 0
        ordered = sorted(values)
        return int(ordered[int(0.75 * (len(ordered) - 1))] or 0)

    top_symbols = [
        {
            "symbol": symbol,
            "loss_trade_count": int(symbol_counts.get(symbol, 0) or 0),
            "negative_r": round(symbol_negative_r.get(symbol, 0.0), 4),
            "median_held_bars": _median(symbol_held_bars.get(symbol, [])),
            "p75_held_bars": _p75(symbol_held_bars.get(symbol, [])),
        }
        for symbol, _ in symbol_counts.most_common(5)
    ]
    top_waves = [
        {
            "closed_ts": closed_ts,
            "loss_trade_count": int(count or 0),
            "negative_r": round(wave_negative_r.get(closed_ts, 0.0), 4),
            "top_symbols": [
                {"symbol": symbol, "loss_trade_count": int(symbol_count or 0)}
                for symbol, symbol_count in wave_symbols.get(closed_ts, Counter()).most_common(3)
            ],
        }
        for closed_ts, count in closed_ts_counts.most_common(3)
    ]
    held_sorted = sorted(held_bars_values)
    median_held_bars = _median(held_sorted)
    p75_held_bars = _p75(held_sorted)
    review_priority = [
        {
            "symbol": item["symbol"],
            "negative_r": item["negative_r"],
            "loss_trade_count": item["loss_trade_count"],
            "median_held_bars": item["median_held_bars"],
        }
        for item in top_symbols[:3]
    ]

    return {
        "loss_trade_count": len(confirm_losses),
        "median_held_bars": median_held_bars,
        "p75_held_bars": p75_held_bars,
        "held_bar_bands": held_bar_bands,
        "top_symbols": top_symbols,
        "top_waves": top_waves,
        "review_priority": review_priority,
    }


def _build_entry_timing_loss_profile(
    *,
    artifact_path: str,
) -> dict[str, Any] | None:
    artifact_rel = str(artifact_path or "").strip()
    if not artifact_rel:
        return None
    artifact = _load_json_file(ROOT_DIR / artifact_rel)
    if not artifact:
        return None

    plan_to_meta: dict[str, dict[str, Any]] = {}
    for path_str in list(artifact.get("input_artifact_paths") or []):
        batch = _load_json_file(ROOT_DIR / str(path_str))
        if not batch:
            continue
        for row in list(batch.get("trade_rows") or []):
            plan_to_meta[str(row.get("plan_id") or "")] = dict(row)

    losses = [
        {**dict(plan_to_meta.get(str(row.get("plan_id") or ""), {}) or {}), **dict(row)}
        for row in list(artifact.get("trade_rows") or [])
        if float(row.get("replayed_realized_r", 0.0) or 0.0) < 0
    ]
    if not losses:
        return None

    def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        held = sorted(int(row.get("final_exit_held_bars", 0) or 0) for row in rows)
        loss_by_symbol: defaultdict[str, float] = defaultdict(float)
        count_by_symbol: Counter[str] = Counter()
        total_negative_r = 0.0
        for row in rows:
            symbol = str(row.get("symbol") or "UNKNOWN")
            replayed_r = float(row.get("replayed_realized_r", 0.0) or 0.0)
            total_negative_r += replayed_r
            loss_by_symbol[symbol] += replayed_r
            count_by_symbol[symbol] += 1
        return {
            "loss_trade_count": len(rows),
            "negative_r": round(total_negative_r, 4),
            "median_held_bars": round(float(held[len(held) // 2]), 4) if held else 0.0,
            "p75_held_bars": int(held[int(0.75 * (len(held) - 1))] or 0) if held else 0,
            "top_symbols": [
                {
                    "symbol": symbol,
                    "loss_trade_count": int(count_by_symbol.get(symbol, 0) or 0),
                    "negative_r": round(loss_by_symbol.get(symbol, 0.0), 4),
                }
                for symbol, _ in sorted(loss_by_symbol.items(), key=lambda item: item[1])[:3]
            ],
        }

    confirm_losses = [row for row in losses if "confirm" in str(row.get("plan_id") or "")]
    non_confirm_losses = [row for row in losses if "confirm" not in str(row.get("plan_id") or "")]
    confirm_summary = _summarize(confirm_losses) if confirm_losses else {}
    non_confirm_summary = _summarize(non_confirm_losses) if non_confirm_losses else {}
    total_negative_r = abs(sum(float(row.get("replayed_realized_r", 0.0) or 0.0) for row in losses))
    confirm_negative_r = abs(float(confirm_summary.get("negative_r", 0.0) or 0.0))
    confirm_share = round(float(len(confirm_losses)) / float(len(losses)), 4) if losses else 0.0
    confirm_negative_share = round(confirm_negative_r / total_negative_r, 4) if total_negative_r else 0.0
    confirm_median = float(confirm_summary.get("median_held_bars", 0.0) or 0.0)
    non_confirm_median = float(non_confirm_summary.get("median_held_bars", 0.0) or 0.0)
    held_bar_gap = round(confirm_median - non_confirm_median, 4)
    dominant_loss_cohort = "confirm" if confirm_share >= 0.5 else "non_confirm"

    if dominant_loss_cohort == "confirm" and held_bar_gap >= 0:
        summary = "confirm losses dominate and hold longer"
    elif dominant_loss_cohort == "confirm":
        summary = "confirm losses dominate, but non-confirm losses hold longer"
    elif held_bar_gap >= 0:
        summary = "non-confirm losses dominate, but confirm losses hold longer"
    else:
        summary = "non-confirm losses dominate and hold longer"

    return {
        "loss_trade_count": len(losses),
        "dominant_loss_cohort": dominant_loss_cohort,
        "confirm_loss_share": confirm_share,
        "confirm_negative_r_share": confirm_negative_share,
        "held_bar_gap_confirm_minus_non_confirm": held_bar_gap,
        "confirm": confirm_summary,
        "non_confirm": non_confirm_summary,
        "summary": summary,
    }


def _build_entry_timing_priority_summary(
    profile: dict[str, Any] | None,
) -> dict[str, Any] | None:
    source = dict(profile or {})
    if not source:
        return None

    confirm_share = float(source.get("confirm_loss_share", 0.0) or 0.0)
    confirm_negative_share = float(source.get("confirm_negative_r_share", 0.0) or 0.0)
    held_gap = float(source.get("held_bar_gap_confirm_minus_non_confirm", 0.0) or 0.0)
    confirm = dict(source.get("confirm") or {})
    non_confirm = dict(source.get("non_confirm") or {})

    if confirm_share >= 0.7 or confirm_negative_share >= 0.7:
        primary_focus_code = "confirm_entry_tighten"
        primary_summary = "confirm 손실 비중이 높아 range confirm-entry를 먼저 줄여야 함"
    else:
        primary_focus_code = "non_confirm_fail_fast"
        primary_summary = "non-confirm 손실 비중이 커서 fail-fast 쪽을 먼저 봐야 함"

    if held_gap <= -240 and int(non_confirm.get("loss_trade_count", 0) or 0) > 0:
        secondary_focus_code = "non_confirm_fail_fast"
        secondary_summary = "non-confirm 손실은 수는 적지만 더 오래 끌려서 fail-fast shadow 검토가 필요함"
    elif held_gap >= 240 and int(confirm.get("loss_trade_count", 0) or 0) > 0:
        secondary_focus_code = "confirm_fail_fast"
        secondary_summary = "confirm 손실도 오래 끌리는 편이라 confirm fail-fast shadow 검토가 필요함"
    else:
        secondary_focus_code = "loss_wave_cluster"
        secondary_summary = "보유시간 차이보다 손실 파동 동시성이 더 크므로 cluster 검토를 우선 유지"

    ordered_focus = [primary_focus_code]
    if secondary_focus_code != primary_focus_code:
        ordered_focus.append(secondary_focus_code)

    return {
        "primary_focus_code": primary_focus_code,
        "primary_summary": primary_summary,
        "secondary_focus_code": secondary_focus_code,
        "secondary_summary": secondary_summary,
        "ordered_focus": ordered_focus,
    }


def _build_post_patch_sample_summary(
    *,
    artifact_path: str,
    baseline_ts: datetime | None = None,
    target_closed_trades: int = _POST_PATCH_SAMPLE_GOAL,
) -> dict[str, Any] | None:
    artifact_rel = str(artifact_path or "").strip()
    if not artifact_rel:
        return None
    artifact = _load_json_file(ROOT_DIR / artifact_rel)
    if not artifact:
        return None

    cutoff = baseline_ts or _parse_ts(_POST_PATCH_BASELINE_TEXT)
    if cutoff is None:
        return None

    plan_to_meta: dict[str, dict[str, Any]] = {}
    for path_str in list(artifact.get("input_artifact_paths") or []):
        batch = _load_json_file(ROOT_DIR / str(path_str))
        if not batch:
            continue
        for row in list(batch.get("trade_rows") or []):
            plan_to_meta[str(row.get("plan_id") or "")] = dict(row)

    cohort_rows: list[dict[str, Any]] = []
    for row in list(artifact.get("trade_rows") or []):
        closed_ts = _parse_ts(row.get("closed_ts"))
        if closed_ts is None or closed_ts < cutoff:
            continue
        plan_id = str(row.get("plan_id") or "")
        meta = dict(plan_to_meta.get(plan_id, {}) or {})
        cohort_rows.append({**meta, **dict(row)})

    if not cohort_rows:
        return {
            "baseline_ts": cutoff.isoformat(),
            "target_closed_trades": int(target_closed_trades),
            "closed_trade_count": 0,
            "remaining_to_target": int(target_closed_trades),
            "ready_for_replay_refresh": False,
            "confirm_named_loss_share": 0.0,
            "stop_loss_share": 0.0,
            "median_held_bars": 0.0,
            "top_symbols": [],
            "summary": f"post-patch sample 0/{int(target_closed_trades)}; waiting for new closes",
        }

    total = len(cohort_rows)
    stop_loss_count = 0
    confirm_loss_count = 0
    loss_held_bars: list[int] = []
    symbol_counts: Counter[str] = Counter()
    replay_rs: list[float] = []
    current_loss_streak = 0
    worst_loss_streak = 0
    for row in cohort_rows:
        plan_id = str(row.get("plan_id") or "")
        exit_reason = str(row.get("final_exit_reason") or "")
        replayed_r = float(row.get("replayed_realized_r", 0.0) or 0.0)
        held_bars = int(row.get("final_exit_held_bars", 0) or 0)
        symbol_counts[str(row.get("symbol") or "UNKNOWN")] += 1
        replay_rs.append(replayed_r)
        if exit_reason == "stop_loss":
            stop_loss_count += 1
        if replayed_r < 0 and "confirm" in plan_id:
            confirm_loss_count += 1
        if replayed_r < 0:
            loss_held_bars.append(held_bars)
            current_loss_streak += 1
            worst_loss_streak = max(worst_loss_streak, current_loss_streak)
        else:
            current_loss_streak = 0

    remaining = max(int(target_closed_trades) - total, 0)
    median_held_bars = 0.0
    if loss_held_bars:
        ordered = sorted(loss_held_bars)
        median_held_bars = round(float(ordered[len(ordered) // 2]), 4)
    top_symbols = [
        {"symbol": symbol, "trade_count": int(count or 0)}
        for symbol, count in symbol_counts.most_common(3)
    ]
    confirm_share = round(float(confirm_loss_count) / float(max(len(loss_held_bars), 1)), 4) if loss_held_bars else 0.0
    stop_loss_share = round(float(stop_loss_count) / float(total), 4) if total else 0.0
    replay_max_drawdown_r = round(_max_drawdown(replay_rs), 4) if replay_rs else 0.0
    replay_p5_r = round(_percentile(replay_rs, 0.05), 4) if replay_rs else 0.0
    return {
        "baseline_ts": cutoff.isoformat(),
        "target_closed_trades": int(target_closed_trades),
        "closed_trade_count": int(total),
        "remaining_to_target": int(remaining),
        "ready_for_replay_refresh": remaining == 0,
        "confirm_named_loss_share": confirm_share,
        "stop_loss_share": stop_loss_share,
        "median_held_bars": median_held_bars,
        "replay_max_drawdown_r": replay_max_drawdown_r,
        "replay_p5_r": replay_p5_r,
        "worst_loss_streak": int(worst_loss_streak),
        "top_symbols": top_symbols,
        "summary": (
            f"post-patch sample {total}/{int(target_closed_trades)}"
            f" | stop_loss={stop_loss_share:.0%}"
            f" | confirm_loss={confirm_share:.0%}"
        ),
    }


def _build_approval_template_focus(
    *,
    focus_symbol: str,
    worst_scenario: str,
    assessment_payload: dict[str, Any] | None,
    output_artifacts_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    assessment = dict(assessment_payload or {})
    output_artifacts = dict(output_artifacts_payload or {})
    scenario_statuses = dict((assessment.get("scenario_evidence") or {}).get("scenario_statuses") or {})
    scenario_outputs = dict(output_artifacts.get("scenario_outputs") or {})
    scenario_status = dict(scenario_statuses.get(worst_scenario) or {})
    scenario_output = dict(scenario_outputs.get(worst_scenario) or {})
    replay_summary = dict(scenario_output.get("summary") or {})
    approximation_gap = dict(scenario_output.get("approximation_gap") or scenario_status.get("approximation_delta") or {})

    if not scenario_status and not scenario_output:
        return None

    focus = {
        "focus_symbol": focus_symbol,
        "worst_scenario": worst_scenario,
        "worst_scenario_status": str(scenario_status.get("status") or "NOT_AVAILABLE"),
        "worst_scenario_reason": str(scenario_status.get("reason") or "not_available"),
        "worst_scenario_source": str(scenario_status.get("source") or "not_available"),
        "divergence_status": str(scenario_status.get("divergence_status") or "NOT_AVAILABLE"),
        "divergence_reason": str(scenario_status.get("divergence_reason") or "not_available"),
        "replay_trade_rows": int((output_artifacts.get("summary_counts") or {}).get("replay_trade_rows", 0) or 0),
        "replay_scenarios_compared": int((output_artifacts.get("summary_counts") or {}).get("scenarios_compared", 0) or 0),
        "replay_ev_r": float(replay_summary.get("ev", 0.0) or 0.0),
        "replay_p5_r": float(replay_summary.get("p5_ev", 0.0) or 0.0),
        "replay_max_drawdown_r": float(replay_summary.get("max_drawdown", 0.0) or 0.0),
        "approximation_gap_ev_r": float(approximation_gap.get("ev", 0.0) or 0.0),
        "approximation_gap_max_drawdown_r": float(approximation_gap.get("max_drawdown", 0.0) or 0.0),
        "artifact_path": str(scenario_output.get("artifact_path") or ""),
    }
    downside_profile = _build_approval_template_downside_profile(artifact_path=str(focus.get("artifact_path") or ""))
    if downside_profile:
        focus["downside_profile"] = downside_profile
    return focus


def _attach_approval_template_focus(
    payload: dict[str, Any],
    *,
    stage: dict[str, Any],
    symbol: str,
    base_url: str,
    request_json_fn=_request_json,
) -> dict[str, Any]:
    enriched = dict(payload or {})
    primary_required = dict(enriched.get("primary_required_review") or {})
    if str(primary_required.get("code") or "") != "approval_template_review":
        return enriched

    worst_scenario = str(primary_required.get("worst_scenario") or "").strip()
    if not worst_scenario:
        return enriched

    focus_symbol = _approval_template_focus_symbol(stage, symbol=symbol)
    try:
        assessment_payload = _request_json_with_retry(
            base_url,
            "/validation/stress-replay-assessment",
            query={"symbol": focus_symbol, "write_report": False},
            request_json_fn=request_json_fn,
        )
        output_artifacts_payload = _request_json_with_retry(
            base_url,
            "/validation/stress-replay-output-artifacts",
            query={"symbol": focus_symbol, "write_report": False},
            request_json_fn=request_json_fn,
        )
    except RuntimeError as exc:
        enriched["approval_template_focus_error"] = str(exc)
        return enriched

    focus = _build_approval_template_focus(
        focus_symbol=focus_symbol,
        worst_scenario=worst_scenario,
        assessment_payload=assessment_payload,
        output_artifacts_payload=output_artifacts_payload,
    )
    if focus is not None:
        downside = dict(focus.get("downside_profile") or {})
        confirm_loss_cluster_summary = _build_confirm_loss_cluster_summary(
            artifact_path=str(focus.get("artifact_path") or "")
        )
        if confirm_loss_cluster_summary:
            focus["confirm_loss_cluster_summary"] = confirm_loss_cluster_summary
        entry_timing_loss_profile = _build_entry_timing_loss_profile(
            artifact_path=str(focus.get("artifact_path") or "")
        )
        entry_timing_priority_summary = None
        if entry_timing_loss_profile:
            focus["entry_timing_loss_profile"] = entry_timing_loss_profile
            entry_timing_priority_summary = _build_entry_timing_priority_summary(entry_timing_loss_profile)
            if entry_timing_priority_summary:
                focus["entry_timing_priority_summary"] = entry_timing_priority_summary
        mitigation_review_summary = _build_mitigation_review_summary(
            downside_profile=downside,
            stage=stage,
            symbol=symbol,
            universe=str(payload.get("universe") or stage.get("universe") or "usdc_perp_top30"),
            days=int(payload.get("days") or stage.get("days") or 30),
        )
        if mitigation_review_summary:
            focus["mitigation_review_summary"] = mitigation_review_summary
            mitigation_execution_plan = _build_mitigation_execution_plan(
                priority_summary=entry_timing_priority_summary,
                mitigation_review_summary=mitigation_review_summary,
            )
            if mitigation_execution_plan:
                focus["mitigation_execution_plan"] = mitigation_execution_plan
        post_patch_sample_summary = _build_post_patch_sample_summary(
            artifact_path=str(focus.get("artifact_path") or "")
        )
        if post_patch_sample_summary:
            focus["post_patch_sample_summary"] = post_patch_sample_summary
        enriched["approval_template_focus"] = focus
    return enriched


def _build_payload(stage: dict[str, Any], *, symbol: str, universe: str, days: int) -> dict[str, Any]:
    runtime_reopen = dict(stage.get("runtime_reopen_status") or {})
    signoff = dict(stage.get("runtime_signoff_summary") or {})
    lineage = dict(stage.get("lineage_sample_summary") or {})
    risk = dict(stage.get("risk_gate_summary") or {})
    validation = dict(stage.get("validation_approval_strip") or {})

    required_reviews = [dict(item) for item in list(signoff.get("required_reviews") or [])]
    advisory_reviews = [dict(item) for item in list(signoff.get("advisory_reviews") or [])]
    primary_required = dict(required_reviews[0] or {}) if required_reviews else {}

    runtime_ready = _runtime_signoff_eligible_status(runtime_reopen.get("status")) or bool(runtime_reopen.get("ready", False))
    if not runtime_ready:
        status = "NOT_READY_FOR_SIGNOFF"
        summary_line = "Runtime reopen is not ready yet; operator sign-off should not proceed."
    elif required_reviews:
        status = "MANUAL_SIGNOFF_REQUIRED"
        summary_line = "Runtime can reopen only after operator explicitly reviews the remaining required warning."
    else:
        status = "READY_FOR_OPERATOR_SIGNOFF"
        summary_line = "Runtime reopen is ready and no required sign-off warnings remain."

    operator_recommendation, operator_recommendation_reason = _fallback_operator_recommendation(
        runtime_ready=runtime_ready,
        required_reviews=required_reviews,
    )

    next_steps: list[str] = []
    if status == "NOT_READY_FOR_SIGNOFF":
        next_steps.append("Wait until runtime_reopen_status becomes ready_to_reopen_runtime.")
    elif required_reviews:
        if str(primary_required.get("code") or "") == "approval_template_review":
            next_steps.append(
                "Review whether the replay-derived worst scenario failure should still block runtime reopen."
            )
            next_steps.append(
                "If the warning is acceptable, record explicit operator sign-off before reopening runtime."
            )
            next_steps.append(
                "If the warning is not acceptable, keep runtime closed and continue candidate review only."
            )
        else:
            next_steps.append("Review the remaining required warning and decide whether runtime reopen is acceptable.")
    else:
        next_steps.append("Proceed to final operator sign-off and runtime reopen decision.")

    payload = {
        "generated_at": _now().isoformat(),
        "symbol": symbol.upper(),
        "universe": universe,
        "days": int(days),
        "status": status,
        "summary_line": summary_line,
        "runtime_signoff_review_command": _runtime_signoff_command(symbol=symbol, universe=universe, days=days),
        "runtime_reopen_status": {
            "status": str(runtime_reopen.get("status") or "not_available"),
            "ready": bool(runtime_reopen.get("ready", False)),
        },
        "risk_gate": {
            "status": str(risk.get("status") or "NOT_AVAILABLE"),
            "state": str(risk.get("risk_state") or "UNKNOWN"),
        },
        "validation": {
            "approve_value": str(validation.get("approve_value") or "n/a"),
            "align_value": str(validation.get("align_value") or "n/a"),
            "act_value": str(validation.get("act_value") or "n/a"),
        },
        "operator_recommendation": operator_recommendation,
        "operator_recommendation_reason": operator_recommendation_reason,
        "lineage_sample": {
            "closed_trade_count": int(lineage.get("closed_trade_count") or 0),
            "proof_goal_closed_trades": int(lineage.get("proof_goal_closed_trades") or 0),
        },
        "required_reviews": required_reviews,
        "advisory_reviews": advisory_reviews,
        "primary_required_review": primary_required or None,
        "next_steps": next_steps,
    }
    return payload


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    primary = dict(payload.get("primary_required_review") or {})
    focus = dict(payload.get("approval_template_focus") or {})
    decision = dict(payload.get("runtime_decision") or {})
    gate = dict(payload.get("runtime_reopen_gate_summary") or {})
    lines: list[str] = []
    lines.append("# Runtime Sign-off Review")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- symbol: {payload['symbol']}")
    lines.append(f"- status: {payload['status']}")
    lines.append(f"- summary: {payload['summary_line']}")
    lines.append("")
    lines.append("## Current State")
    lines.append("")
    lines.append(
        f"- runtime_reopen_status: {payload['runtime_reopen_status']['status']} / ready={payload['runtime_reopen_status']['ready']}"
    )
    lines.append(f"- operator_recommendation: {payload.get('operator_recommendation') or 'n/a'}")
    lines.append(f"- operator_recommendation_reason: {payload.get('operator_recommendation_reason') or 'n/a'}")
    if decision:
        lines.append(
            f"- runtime_decision: {decision.get('band') or 'n/a'} / "
            f"{decision.get('effective_action') or 'n/a'} / "
            f"scope={decision.get('allowed_reopen_scope') or 'n/a'}"
        )
        lines.append(f"- runtime_decision_summary: {decision.get('summary') or 'n/a'}")
    if gate:
        micro = dict(gate.get("micro_live") or {})
        full = dict(gate.get("full_live") or {})
        lines.append(
            "- runtime_reopen_gate: "
            f"MICRO={micro.get('status') or 'n/a'} "
            f"({int(micro.get('closed_trade_count') or 0)}/{int(micro.get('min_closed_trades') or 0)})"
            f" | FULL={full.get('status') or 'n/a'} "
            f"({int(full.get('closed_trade_count') or 0)}/{int(full.get('min_closed_trades') or 0)})"
        )
    lines.append(f"- risk_gate: {payload['risk_gate']['status']} / {payload['risk_gate']['state']}")
    lines.append(
        f"- lineage_sample: {payload['lineage_sample']['closed_trade_count']}/{payload['lineage_sample']['proof_goal_closed_trades']}"
    )
    lines.append("")
    lines.append("## Required Review")
    lines.append("")
    if primary:
        lines.append(f"- code: {primary.get('code', 'n/a')}")
        lines.append(f"- summary: {primary.get('summary', 'n/a')}")
        lines.append(f"- current_value: {primary.get('current_value', 'n/a')}")
        if primary.get("worst_scenario"):
            lines.append(
                f"- worst_scenario: {primary.get('worst_scenario')}/{primary.get('worst_scenario_status', 'NOT_AVAILABLE')}"
            )
        if primary.get("worst_scenario_reason"):
            lines.append(f"- worst_scenario_reason: {primary.get('worst_scenario_reason')}")
        lines.append(f"- clear_when: {primary.get('clear_when', 'n/a')}")
    else:
        lines.append("- none")
    if focus:
        lines.append("")
        lines.append("## Approval Template Focus")
        lines.append("")
        lines.append(f"- focus_symbol: {focus.get('focus_symbol', 'n/a')}")
        lines.append(
            f"- worst_scenario: {focus.get('worst_scenario', 'n/a')}/{focus.get('worst_scenario_status', 'NOT_AVAILABLE')}"
        )
        lines.append(f"- worst_scenario_reason: {focus.get('worst_scenario_reason', 'n/a')}")
        lines.append(f"- source: {focus.get('worst_scenario_source', 'n/a')}")
        lines.append(
            f"- replay_ev_r: {float(focus.get('replay_ev_r', 0.0) or 0.0):.4f} | "
            f"replay_p5_r: {float(focus.get('replay_p5_r', 0.0) or 0.0):.4f} | "
            f"replay_max_drawdown_r: {float(focus.get('replay_max_drawdown_r', 0.0) or 0.0):.4f}"
        )
        lines.append(
            f"- approximation_gap_ev_r: {float(focus.get('approximation_gap_ev_r', 0.0) or 0.0):+.4f} | "
            f"approximation_gap_max_drawdown_r: {float(focus.get('approximation_gap_max_drawdown_r', 0.0) or 0.0):+.4f}"
        )
        lines.append(
            f"- divergence: {focus.get('divergence_status', 'NOT_AVAILABLE')} / "
            f"{focus.get('divergence_reason', 'n/a')}"
        )
        lines.append(
            f"- replay_trade_rows: {int(focus.get('replay_trade_rows', 0) or 0)} | "
            f"scenarios_compared: {int(focus.get('replay_scenarios_compared', 0) or 0)}"
        )
        downside = dict(focus.get("downside_profile") or {})
        if downside:
            lines.append(
                f"- downside_profile: regime={str(downside.get('dominant_regime') or 'unknown')}, "
                f"stop_loss={int(downside.get('stop_loss_count', 0) or 0)}/"
                f"{int(downside.get('trade_count', 0) or 0)} "
                f"({float(downside.get('stop_loss_share', 0.0) or 0.0):.2%}), "
                f"confirm_losses={int(downside.get('confirm_named_loss_count', 0) or 0)}/"
                f"{int(downside.get('loss_trade_count', 0) or 0)} "
                f"({float(downside.get('confirm_named_loss_share', 0.0) or 0.0):.2%}), "
                f"long_hold_losses={int(downside.get('long_hold_loss_count', 0) or 0)}/"
                f"{int(downside.get('loss_trade_count', 0) or 0)} "
                f"({float(downside.get('long_hold_loss_share', 0.0) or 0.0):.2%}), "
                f"held_bars_median={float(downside.get('median_loss_held_bars', 0.0) or 0.0):.0f}, "
                f"held_bars_p75={int(downside.get('p75_loss_held_bars', 0) or 0)}, "
                f"worst_loss_streak={int(downside.get('worst_loss_streak', 0) or 0)}, "
                f"worst_loss_block={float(downside.get('worst_loss_block_sum_r', 0.0) or 0.0):.4f}R/"
                f"{int(downside.get('worst_loss_block_len', 0) or 0)} trades"
            )
            lines.append(
                f"- primary_failure_mode: {str(downside.get('primary_failure_mode') or 'unknown')} / "
                f"{str(downside.get('primary_failure_summary') or 'n/a')}"
            )
            top_loss_symbols = list(downside.get("top_loss_symbols") or [])
            if top_loss_symbols:
                top_line = ", ".join(
                    f"{str(item.get('symbol') or 'UNKNOWN')} "
                    f"({float(item.get('negative_r', 0.0) or 0.0):.4f}R/"
                    f"{int(item.get('loss_trade_count', 0) or 0)})"
                    for item in top_loss_symbols[:3]
                )
                lines.append(f"- top_loss_symbols: {top_line}")
            top_loss_waves = list(downside.get("top_loss_waves") or [])
            if top_loss_waves:
                wave = dict(top_loss_waves[0] or {})
                lines.append(
                    f"- top_loss_wave: {str(wave.get('closed_ts') or 'n/a')} / "
                    f"{int(wave.get('loss_trade_count', 0) or 0)} losses / "
                    f"{float(downside.get('top_loss_wave_share_of_losses', 0.0) or 0.0):.2%} of replay losses"
                )
            mitigation_focus = list(downside.get("mitigation_focus") or [])
            if mitigation_focus:
                lines.append("- mitigation_focus:")
                for item in mitigation_focus[:3]:
                    lines.append(
                        f"  - {str(item.get('code') or 'unknown')}: {str(item.get('summary') or 'n/a')}"
                    )
        mitigation_review_summary = dict(focus.get("mitigation_review_summary") or {})
        if mitigation_review_summary:
            lines.append(
                "- mitigation_review_summary: "
                f"primary={str(mitigation_review_summary.get('primary_action_code') or 'unknown')}/"
                f"{str(mitigation_review_summary.get('primary_action_status') or 'unknown')}"
            )
            for item in list(mitigation_review_summary.get("items") or [])[:3]:
                lines.append(
                    "  - "
                    f"{str(item.get('code') or 'unknown')}: "
                    f"status={str(item.get('status') or 'unknown')} | "
                    f"mode={str(item.get('review_mode') or 'unknown')} | "
                    f"constraint={str(item.get('current_constraint') or 'none')} | "
                    f"command={str(item.get('command') or 'n/a')}"
                )
        confirm_cluster = dict(focus.get("confirm_loss_cluster_summary") or {})
        if confirm_cluster:
            top_symbols = ", ".join(
                f"{str(item.get('symbol') or 'UNKNOWN')} "
                f"({int(item.get('loss_trade_count', 0) or 0)} / {float(item.get('negative_r', 0.0) or 0.0):.4f}R)"
                for item in list(confirm_cluster.get("top_symbols") or [])[:3]
            )
            top_wave = dict((confirm_cluster.get("top_waves") or [None])[0] or {})
            lines.append(
                f"- confirm_loss_cluster: losses={int(confirm_cluster.get('loss_trade_count', 0) or 0)}, "
                f"median_held_bars={float(confirm_cluster.get('median_held_bars', 0.0) or 0.0):.0f}, "
                f"p75_held_bars={int(confirm_cluster.get('p75_held_bars', 0) or 0)}, "
                f"top_wave={str(top_wave.get('closed_ts') or 'n/a')}/{int(top_wave.get('loss_trade_count', 0) or 0)}, "
                f"top_symbols={top_symbols or 'n/a'}"
            )
        entry_timing_profile = dict(focus.get("entry_timing_loss_profile") or {})
        if entry_timing_profile:
            confirm_profile = dict(entry_timing_profile.get("confirm") or {})
            non_confirm_profile = dict(entry_timing_profile.get("non_confirm") or {})
            lines.append(
                f"- entry_timing_loss_profile: dominant={str(entry_timing_profile.get('dominant_loss_cohort') or 'unknown')}, "
                f"confirm_share={float(entry_timing_profile.get('confirm_loss_share', 0.0) or 0.0):.2%}, "
                f"confirm_negative_r_share={float(entry_timing_profile.get('confirm_negative_r_share', 0.0) or 0.0):.2%}, "
                f"held_gap={float(entry_timing_profile.get('held_bar_gap_confirm_minus_non_confirm', 0.0) or 0.0):+.0f} bars, "
                f"confirm={int(confirm_profile.get('loss_trade_count', 0) or 0)}/"
                f"{float(confirm_profile.get('negative_r', 0.0) or 0.0):.4f}R, "
                f"non_confirm={int(non_confirm_profile.get('loss_trade_count', 0) or 0)}/"
                f"{float(non_confirm_profile.get('negative_r', 0.0) or 0.0):.4f}R"
            )
        priority_summary = dict(focus.get("entry_timing_priority_summary") or {})
        if priority_summary:
            lines.append(
                f"- entry_timing_priority: primary={str(priority_summary.get('primary_focus_code') or 'unknown')} / "
                f"{str(priority_summary.get('primary_summary') or 'n/a')} | "
                f"secondary={str(priority_summary.get('secondary_focus_code') or 'unknown')} / "
                f"{str(priority_summary.get('secondary_summary') or 'n/a')}"
            )
        execution_plan = dict(focus.get("mitigation_execution_plan") or {})
        if execution_plan:
            lines.append(
                f"- mitigation_execution_plan: primary={str(execution_plan.get('primary_focus_label') or 'unknown')}/"
                f"{str(execution_plan.get('primary_status') or 'unknown')} | "
                f"secondary={str(execution_plan.get('secondary_focus_label') or 'none')}/"
                f"{str(execution_plan.get('secondary_status') or 'none')}"
            )
        post_patch = dict(focus.get("post_patch_sample_summary") or {})
        if post_patch:
            top_symbols = ", ".join(
                f"{str(item.get('symbol') or 'UNKNOWN')} ({int(item.get('trade_count', 0) or 0)})"
                for item in list(post_patch.get("top_symbols") or [])[:3]
            )
            lines.append(
                f"- post_patch_sample: {int(post_patch.get('closed_trade_count', 0) or 0)}/"
                f"{int(post_patch.get('target_closed_trades', 0) or 0)} | "
                f"ready={bool(post_patch.get('ready_for_replay_refresh', False))} | "
                f"stop_loss={float(post_patch.get('stop_loss_share', 0.0) or 0.0):.0%} | "
                f"confirm_loss={float(post_patch.get('confirm_named_loss_share', 0.0) or 0.0):.0%} | "
                f"median_held_bars={float(post_patch.get('median_held_bars', 0.0) or 0.0):.0f}"
                + (f" | top_symbols={top_symbols}" if top_symbols else "")
            )
    if decision.get("breached_thresholds"):
        lines.append("")
        lines.append("## Runtime Decision Thresholds")
        lines.append("")
        for item in list(decision.get("breached_thresholds") or []):
            lines.append(
                f"- {str(item.get('code') or 'unknown')}: "
                f"value={item.get('value')} threshold={item.get('threshold')}"
            )
    lines.append("")
    lines.append("## Next Steps")
    lines.append("")
    for item in payload.get("next_steps") or []:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Raw Payload")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    lines.append("```")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_confirm_loss_cluster_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    focus = dict(payload.get("approval_template_focus") or {})
    downside = dict(focus.get("downside_profile") or {})
    cluster = dict(focus.get("confirm_loss_cluster_summary") or {})
    lines: list[str] = []
    lines.append("# Confirm Loss Cluster Review")
    lines.append("")
    lines.append(f"- generated_at: {payload.get('generated_at') or 'n/a'}")
    lines.append(f"- symbol: {payload.get('symbol') or 'n/a'}")
    lines.append(f"- focus_symbol: {focus.get('focus_symbol') or 'n/a'}")
    lines.append(f"- worst_scenario: {focus.get('worst_scenario') or 'n/a'}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        f"- primary_failure_mode: {downside.get('primary_failure_mode') or 'unknown'} / "
        f"{downside.get('primary_failure_summary') or 'n/a'}"
    )
    lines.append(
        f"- confirm_losses: {int(cluster.get('loss_trade_count', 0) or 0)} / "
        f"{int(downside.get('loss_trade_count', 0) or 0)} "
        f"({float(downside.get('confirm_named_loss_share', 0.0) or 0.0):.2%})"
    )
    lines.append(
        f"- held_bars: median={float(cluster.get('median_held_bars', 0.0) or 0.0):.0f} / "
        f"p75={int(cluster.get('p75_held_bars', 0) or 0)}"
    )
    lines.append(
        f"- worst_wave_share: {float(downside.get('top_loss_wave_share_of_losses', 0.0) or 0.0):.2%}"
    )
    held_bar_bands = dict(cluster.get("held_bar_bands") or {})
    if held_bar_bands:
        lines.append(
            f"- held_bar_bands: >240={int(held_bar_bands.get('over_240', 0) or 0)}, "
            f">1000={int(held_bar_bands.get('over_1000', 0) or 0)}, "
            f">2000={int(held_bar_bands.get('over_2000', 0) or 0)}"
        )
    lines.append("")
    lines.append("## Top Symbols")
    lines.append("")
    top_symbols = list(cluster.get("top_symbols") or [])
    if top_symbols:
        for item in top_symbols:
            lines.append(
                f"- {str(item.get('symbol') or 'UNKNOWN')}: "
                f"{int(item.get('loss_trade_count', 0) or 0)} losses / "
                f"{float(item.get('negative_r', 0.0) or 0.0):.4f}R / "
                f"median={float(item.get('median_held_bars', 0.0) or 0.0):.0f} bars / "
                f"p75={int(item.get('p75_held_bars', 0) or 0)} bars"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Loss Waves")
    lines.append("")
    top_waves = list(cluster.get("top_waves") or [])
    if top_waves:
        for item in top_waves:
            top_symbols_line = ", ".join(
                f"{str(symbol_item.get('symbol') or 'UNKNOWN')}({int(symbol_item.get('loss_trade_count', 0) or 0)})"
                for symbol_item in list(item.get("top_symbols") or [])[:3]
            )
            lines.append(
                f"- {str(item.get('closed_ts') or 'n/a')}: "
                f"{int(item.get('loss_trade_count', 0) or 0)} confirm losses / "
                f"{float(item.get('negative_r', 0.0) or 0.0):.4f}R / "
                f"top={top_symbols_line or 'n/a'}"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Review Priority")
    lines.append("")
    review_priority = list(cluster.get("review_priority") or [])
    if review_priority:
        for item in review_priority:
            lines.append(
                f"- {str(item.get('symbol') or 'UNKNOWN')}: "
                f"{float(item.get('negative_r', 0.0) or 0.0):.4f}R / "
                f"{int(item.get('loss_trade_count', 0) or 0)} losses / "
                f"median={float(item.get('median_held_bars', 0.0) or 0.0):.0f} bars"
            )
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Next Step")
    lines.append("")
    lines.append(
        "- Prioritize `range_entry_timing_review` before any reopen decision; "
        "treat `shadow_fail_fast_review` as the next shadow-only mitigation."
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_entry_timing_loss_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    focus = dict(payload.get("approval_template_focus") or {})
    profile = dict(focus.get("entry_timing_loss_profile") or {})
    priority = dict(focus.get("entry_timing_priority_summary") or {})
    confirm = dict(profile.get("confirm") or {})
    non_confirm = dict(profile.get("non_confirm") or {})
    lines: list[str] = []
    lines.append("# Entry Timing Loss Review")
    lines.append("")
    lines.append(f"- generated_at: {payload.get('generated_at') or 'n/a'}")
    lines.append(f"- symbol: {payload.get('symbol') or 'n/a'}")
    lines.append(f"- focus_symbol: {focus.get('focus_symbol') or 'n/a'}")
    lines.append(f"- worst_scenario: {focus.get('worst_scenario') or 'n/a'}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- dominant_loss_cohort: {profile.get('dominant_loss_cohort') or 'unknown'}")
    lines.append(f"- summary: {profile.get('summary') or 'n/a'}")
    lines.append(
        f"- confirm_loss_share: {float(profile.get('confirm_loss_share', 0.0) or 0.0):.2%} / "
        f"confirm_negative_r_share: {float(profile.get('confirm_negative_r_share', 0.0) or 0.0):.2%}"
    )
    lines.append(
        f"- held_bar_gap_confirm_minus_non_confirm: {float(profile.get('held_bar_gap_confirm_minus_non_confirm', 0.0) or 0.0):+.0f} bars"
    )
    if priority:
        lines.append(
            f"- priority: primary={str(priority.get('primary_focus_code') or 'unknown')} / "
            f"{str(priority.get('primary_summary') or 'n/a')}"
        )
        lines.append(
            f"- secondary: {str(priority.get('secondary_focus_code') or 'unknown')} / "
            f"{str(priority.get('secondary_summary') or 'n/a')}"
        )
    execution_plan = dict(focus.get("mitigation_execution_plan") or {})
    if execution_plan:
        lines.append(
            f"- execution_plan: primary={str(execution_plan.get('primary_focus_label') or 'unknown')} / "
            f"{str(execution_plan.get('primary_status') or 'unknown')} / "
            f"cmd={str(execution_plan.get('primary_command') or 'n/a')}"
        )
        if str(execution_plan.get("secondary_focus_label") or "").strip():
            lines.append(
                f"- execution_plan_secondary: {str(execution_plan.get('secondary_focus_label') or 'unknown')} / "
                f"{str(execution_plan.get('secondary_status') or 'unknown')} / "
                f"cmd={str(execution_plan.get('secondary_command') or 'n/a')}"
            )
    lines.append("")
    lines.append("## Confirm Cohort")
    lines.append("")
    lines.append(
        f"- losses: {int(confirm.get('loss_trade_count', 0) or 0)} / "
        f"{float(confirm.get('negative_r', 0.0) or 0.0):.4f}R / "
        f"median={float(confirm.get('median_held_bars', 0.0) or 0.0):.0f} bars / "
        f"p75={int(confirm.get('p75_held_bars', 0) or 0)} bars"
    )
    for item in list(confirm.get("top_symbols") or [])[:3]:
        lines.append(
            f"- {str(item.get('symbol') or 'UNKNOWN')}: "
            f"{int(item.get('loss_trade_count', 0) or 0)} losses / "
            f"{float(item.get('negative_r', 0.0) or 0.0):.4f}R"
        )
    lines.append("")
    lines.append("## Non-Confirm Cohort")
    lines.append("")
    lines.append(
        f"- losses: {int(non_confirm.get('loss_trade_count', 0) or 0)} / "
        f"{float(non_confirm.get('negative_r', 0.0) or 0.0):.4f}R / "
        f"median={float(non_confirm.get('median_held_bars', 0.0) or 0.0):.0f} bars / "
        f"p75={int(non_confirm.get('p75_held_bars', 0) or 0)} bars"
    )
    for item in list(non_confirm.get("top_symbols") or [])[:3]:
        lines.append(
            f"- {str(item.get('symbol') or 'UNKNOWN')}: "
            f"{int(item.get('loss_trade_count', 0) or 0)} losses / "
            f"{float(item.get('negative_r', 0.0) or 0.0):.4f}R"
        )
    lines.append("")
    lines.append("## Next Step")
    lines.append("")
    lines.append("- Prioritize `range_entry_timing_review`; confirm cohort dominates the replay downside.")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_runtime_mitigation_plan_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    focus = dict(payload.get("approval_template_focus") or {})
    execution_plan = dict(focus.get("mitigation_execution_plan") or {})
    review_summary = dict(focus.get("mitigation_review_summary") or {})
    lines: list[str] = []
    lines.append("# Runtime Mitigation Plan")
    lines.append("")
    lines.append(f"- generated_at: {payload.get('generated_at') or 'n/a'}")
    lines.append(f"- symbol: {payload.get('symbol') or 'n/a'}")
    lines.append(f"- runtime_status: {payload.get('status') or 'n/a'}")
    lines.append("")
    lines.append("## Plan")
    lines.append("")
    if execution_plan:
        lines.append(
            f"- 1st: {execution_plan.get('primary_focus_label') or 'n/a'} / "
            f"{execution_plan.get('primary_status') or 'n/a'}"
        )
        lines.append(f"  command: {execution_plan.get('primary_command') or 'n/a'}")
        if str(execution_plan.get("secondary_focus_label") or "").strip():
            lines.append(
                f"- 2nd: {execution_plan.get('secondary_focus_label') or 'n/a'} / "
                f"{execution_plan.get('secondary_status') or 'n/a'}"
            )
            lines.append(f"  command: {execution_plan.get('secondary_command') or 'n/a'}")
    else:
        lines.append("- no mitigation execution plan available")
    lines.append("")
    lines.append("## Review Items")
    lines.append("")
    for item in list(review_summary.get("items") or []):
        lines.append(
            f"- {str(item.get('code') or 'unknown')}: "
            f"status={str(item.get('status') or 'unknown')} / "
            f"mode={str(item.get('review_mode') or 'unknown')} / "
            f"constraint={str(item.get('current_constraint') or 'none')} / "
            f"command={str(item.get('command') or 'n/a')}"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _report_path_value(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def main() -> int:
    args = parse_args()
    stage = _read_stage(Path(args.stage_file))
    payload = _build_payload(
        stage,
        symbol=args.symbol,
        universe=args.universe,
        days=args.days,
    )
    payload = _attach_approval_template_focus(
        payload,
        stage=stage,
        symbol=args.symbol,
        base_url=args.base_url,
    )
    payload = _apply_runtime_decision(payload)
    if not args.no_write_report:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        report_path = ROOT_DIR / args.report_dir / f"runtime_signoff_review_{args.symbol.upper()}_{ts}.md"
        _write_report(report_path, payload)
        payload["report_path"] = _report_path_value(report_path)
        confirm_cluster = dict(dict(payload.get("approval_template_focus") or {}).get("confirm_loss_cluster_summary") or {})
        if confirm_cluster:
            confirm_report_path = (
                ROOT_DIR
                / args.report_dir
                / f"confirm_loss_cluster_review_{args.symbol.upper()}_{ts}.md"
            )
            _write_confirm_loss_cluster_report(confirm_report_path, payload)
            payload["confirm_loss_cluster_report_path"] = _report_path_value(confirm_report_path)
        entry_timing_profile = dict(dict(payload.get("approval_template_focus") or {}).get("entry_timing_loss_profile") or {})
        if entry_timing_profile:
            entry_timing_report_path = (
                ROOT_DIR
                / args.report_dir
                / f"entry_timing_loss_review_{args.symbol.upper()}_{ts}.md"
            )
            _write_entry_timing_loss_report(entry_timing_report_path, payload)
            payload["entry_timing_loss_report_path"] = _report_path_value(entry_timing_report_path)
        mitigation_execution_plan = dict(dict(payload.get("approval_template_focus") or {}).get("mitigation_execution_plan") or {})
        if mitigation_execution_plan:
            mitigation_plan_report_path = (
                ROOT_DIR
                / args.report_dir
                / f"runtime_mitigation_plan_{args.symbol.upper()}_{ts}.md"
            )
            _write_runtime_mitigation_plan_report(mitigation_plan_report_path, payload)
            payload["runtime_mitigation_plan_report_path"] = _report_path_value(mitigation_plan_report_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
