#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from scripts import run_runtime_signoff_review

DEFAULT_STAGE_FILE = ROOT_DIR / "reports/operations/stage_monitor/current_stage.json"
_REQUEST_RETRY_ATTEMPTS = 5
_REQUEST_RETRY_BASE_DELAY_SECONDS = 1.0
_RUNTIME_MONITOR_REUSE_SECONDS = 900
_REQUEST_TIMEOUT_SECONDS = 90


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show the current operating stage from validation, checklist, and operator dashboard surfaces."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument(
        "--lineage-sample-scope",
        choices=["symbol_edge_proof", "family_global"],
        default="family_global",
        help="Sample scope for readiness/stall tracking.",
    )
    parser.add_argument(
        "--lineage-families",
        default="sweep_reversal,trend_continuation",
        help="Comma-separated lineage families to count when using family_global scope.",
    )
    parser.add_argument(
        "--lineage-proof-goal-closed-trades",
        type=int,
        default=100,
        help="Closed-trade goal for lineage sample readiness.",
    )
    parser.add_argument(
        "--lineage-sample-days",
        type=int,
        default=180,
        help="Lookback window for lineage family sample counting.",
    )
    parser.add_argument("--alert-test-lookback-hours", type=int, default=24)
    parser.add_argument("--json", action="store_true", help="Print full JSON only.")
    parser.add_argument(
        "--stage-file",
        default=str(DEFAULT_STAGE_FILE),
        help="Write the latest stage snapshot to this path.",
    )
    parser.add_argument(
        "--no-write-stage",
        action="store_true",
        help="Do not persist the latest stage snapshot.",
    )
    return parser.parse_args()


def _request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url += f"?{urlencode(query, doseq=True)}"
    request = Request(url=url, headers={"Accept": "application/json"}, method=method.upper())
    last_error: RuntimeError | None = None
    retry_with_refresh = (
        path == "/validation/report"
        and str((query or {}).get("refresh", "")).lower() in {"false", "0"}
    )
    for attempt in range(1, _REQUEST_RETRY_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            if retry_with_refresh and exc.code == 404 and "cached validation payload is not available yet" in payload.lower():
                refreshed_query = dict(query or {})
                refreshed_query["refresh"] = True
                return _request_json(base_url, method, path, query=refreshed_query)
            retryable = exc.code >= 500 or "database is locked" in payload.lower()
            last_error = RuntimeError(f"{method.upper()} {path} failed with HTTP {exc.code}: {payload}")
            if retryable and attempt < _REQUEST_RETRY_ATTEMPTS:
                time.sleep(_REQUEST_RETRY_BASE_DELAY_SECONDS * attempt)
                continue
            raise last_error from exc
        except URLError as exc:
            last_error = RuntimeError(f"{method.upper()} {path} failed: {exc.reason}")
            if attempt < _REQUEST_RETRY_ATTEMPTS:
                time.sleep(_REQUEST_RETRY_BASE_DELAY_SECONDS * attempt)
                continue
            raise last_error from exc
        except TimeoutError as exc:
            last_error = RuntimeError(f"{method.upper()} {path} timed out after {_REQUEST_TIMEOUT_SECONDS}s")
            if attempt < _REQUEST_RETRY_ATTEMPTS:
                time.sleep(_REQUEST_RETRY_BASE_DELAY_SECONDS * attempt)
                continue
            raise last_error from exc
    assert last_error is not None
    raise last_error


def _write_stage_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


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


def _read_stage_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return dict(payload) if isinstance(payload, dict) else None


def _active_close_only(dashboard: dict[str, Any]) -> bool:
    locks = dashboard.get("active_locks")
    if not isinstance(locks, list):
        return False
    return any(str(item.get("reason_code") or "") == "close_only_active" for item in locks if isinstance(item, dict))


def _surface_strip_summary(payload: dict[str, Any] | None, *, surface_type: str = "generic") -> dict[str, str]:
    surface = dict(payload or {})
    if surface_type == "validation":
        summary = dict(surface.get("approval_strip_summary") or {})
        deployment_summary = dict(surface.get("deployment_approval_summary") or {})
    else:
        summary = dict(surface.get("approval_strip_summary") or {})
        deployment_summary = {}
    if summary:
        return {
            "approve_value": str(summary.get("approve_value") or "n/a"),
            "approve_reason": str(summary.get("approve_reason") or ""),
            "align_value": str(summary.get("align_value") or "n/a"),
            "align_reason": str(summary.get("align_reason") or ""),
            "act_value": str(summary.get("act_value") or "continue_runtime_monitoring"),
            "act_reason": str(summary.get("act_reason") or ""),
            "act_priority_level": str(summary.get("act_priority_level") or "monitor"),
            "primary_reason": str(summary.get("primary_reason") or ""),
        }
    return {
        "approve_value": str(
            surface.get("deployment_go_no_go")
            or deployment_summary.get("deployment_go_no_go")
            or surface.get("approval_topline_status")
            or "n/a"
        ),
        "approve_reason": str(
            surface.get("deployment_message")
            or deployment_summary.get("deployment_message")
            or surface.get("approval_topline_summary_line")
            or ""
        ),
        "align_value": str(
            surface.get("playbook_go_no_go")
            or deployment_summary.get("playbook_go_no_go")
            or surface.get("approval_topline_status")
            or "n/a"
        ),
        "align_reason": str(
            surface.get("playbook_message")
            or deployment_summary.get("playbook_message")
            or surface.get("approval_topline_summary_line")
            or ""
        ),
        "act_value": str(
            surface.get("playbook_action")
            or deployment_summary.get("playbook_action")
            or "continue_runtime_monitoring"
        ),
        "act_reason": str(
            surface.get("playbook_message")
            or deployment_summary.get("playbook_message")
            or surface.get("deployment_message")
            or deployment_summary.get("deployment_message")
            or ""
        ),
        "act_priority_level": "monitor",
        "primary_reason": str(
            surface.get("deployment_message")
            or deployment_summary.get("deployment_message")
            or surface.get("playbook_message")
            or deployment_summary.get("playbook_message")
            or ""
        ),
    }


def _surface_summary_line(label: str, summary: dict[str, str]) -> str:
    return (
        f"{label}: approve={summary.get('approve_value', 'n/a')} | "
        f"align={summary.get('align_value', 'n/a')} | "
        f"act={summary.get('act_value', 'continue_runtime_monitoring')}"
    )


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _family_set(raw: str | None) -> list[str]:
    values = {item.strip().lower() for item in str(raw or "").split(",") if item.strip()}
    return sorted(values)


def _lineage_sample_summary(
    *,
    scope: str,
    symbol: str,
    edge_experiment_review: dict[str, Any] | None,
    families: list[str],
    proof_goal_closed_trades: int,
    sample_days: int,
) -> dict[str, Any]:
    normalized_scope = str(scope or "symbol_edge_proof").strip().lower() or "symbol_edge_proof"
    goal = max(int(proof_goal_closed_trades or 0), 0)
    if normalized_scope != "family_global":
        detail = _edge_experiment_detail_parts(edge_experiment_review or {})
        closed_count = int(detail.get("closed_trade_count", 0) or 0)
        summary = {
            "scope": "symbol_edge_proof",
            "symbol_filter": str(symbol or "").upper() or None,
            "families": list(families),
            "proof_goal_closed_trades": goal,
            "closed_trade_count": closed_count,
            "remaining_closed_trades_to_goal": max(goal - closed_count, 0),
            "goal_ready": goal > 0 and closed_count >= goal,
            "latest_closed_trade_at": None,
        }
        summary["summary"] = (
            f"scope=symbol_edge_proof | symbol={summary['symbol_filter'] or 'n/a'} | "
            f"closes={summary['closed_trade_count']}/{goal} | "
            f"remaining={summary['remaining_closed_trades_to_goal']}"
        )
        return summary

    closed_count, latest_closed_trade_dt = _family_closed_fill_metrics(families=families, sample_days=sample_days)
    latest_closed_trade_at = latest_closed_trade_dt.isoformat() if latest_closed_trade_dt is not None else None

    summary = {
        "scope": "family_global",
        "symbol_filter": None,
        "families": list(families),
        "proof_goal_closed_trades": goal,
        "closed_trade_count": closed_count,
        "remaining_closed_trades_to_goal": max(goal - closed_count, 0),
        "goal_ready": goal > 0 and closed_count >= goal,
        "latest_closed_trade_at": latest_closed_trade_at,
        "sample_days": int(max(1, sample_days)),
    }
    summary["summary"] = (
        f"scope=family_global | families={','.join(summary['families']) or 'none'} | "
        f"closes={summary['closed_trade_count']}/{goal} | "
        f"remaining={summary['remaining_closed_trades_to_goal']} | "
        f"lookback_days={summary['sample_days']}"
    )
    return summary


def _family_closed_fill_metrics(*, families: list[str], sample_days: int) -> tuple[int, datetime | None]:
    from datetime import timedelta

    from app.core.config import get_settings
    from app.core.enums import ExecutionFillStage
    from app.db.models import ExecutionFill
    from app.db.session import SessionLocal

    normalized_families = {str(item).strip().lower() for item in families if str(item).strip()}
    if not normalized_families:
        return 0, None

    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(sample_days)))
    db = SessionLocal()
    try:
        rows = (
            db.query(ExecutionFill.plan_id, ExecutionFill.fill_ts, ExecutionFill.payload)
            .filter(
                ExecutionFill.stage == ExecutionFillStage.CLOSED.value,
                ExecutionFill.strategy_version == settings.strategy_version,
                ExecutionFill.fill_ts >= cutoff,
            )
            .all()
        )
        latest_by_plan: dict[str, datetime] = {}
        latest_closed_trade_at: datetime | None = None
        for plan_id, fill_ts, payload in rows:
            family = str((payload or {}).get("strategy_family") or "").strip().lower()
            if family not in normalized_families:
                continue
            candidate = fill_ts if isinstance(fill_ts, datetime) else None
            if candidate is None:
                continue
            if candidate.tzinfo is None:
                candidate = candidate.replace(tzinfo=timezone.utc)
            else:
                candidate = candidate.astimezone(timezone.utc)
            current = latest_by_plan.get(str(plan_id))
            if current is None or candidate > current:
                latest_by_plan[str(plan_id)] = candidate
            if latest_closed_trade_at is None or candidate > latest_closed_trade_at:
                latest_closed_trade_at = candidate
        return len(latest_by_plan), latest_closed_trade_at
    finally:
        db.close()


def _edge_experiment_summary(
    validation_report: dict[str, Any],
    dashboard: dict[str, Any],
) -> dict[str, Any] | None:
    dashboard_source = dict((((dashboard or {}).get("signal_funnel") or {}).get("edge_experiment_review") or {}))
    validation_source = dict((validation_report or {}).get("edge_experiment_review_summary") or {})
    source = dashboard_source or validation_source
    if not source:
        return None

    source_summary = dict(source.get("source_summary") or {})
    edge_proof_posture = dict(source.get("edge_proof_posture") or {})
    daily_edge_kpis = dict(source.get("daily_edge_kpis") or {})
    return {
        "available": bool(source.get("available", True)),
        "advisory_only": bool(source.get("advisory_only", True)),
        "edge_state": str(source.get("edge_state") or "insufficient_edge_measurement"),
        "summary": str(source.get("summary") or ""),
        "true_edge_ratio": round(_float(source.get("true_edge_ratio")), 4),
        "edge_decay_rate": round(_float(source.get("edge_decay_rate")), 4),
        "entry_timing_preferred_variant": str(
            source.get("entry_timing_preferred_variant") or source_summary.get("entry_timing_preferred_variant") or "none"
        ),
        "execution_style_preferred_variant": str(
            source.get("execution_style_preferred_variant")
            or source_summary.get("execution_style_preferred_variant")
            or "none"
        ),
        "edge_proof_goal_closed_trades": int(
            source.get("edge_proof_goal_closed_trades") or edge_proof_posture.get("edge_proof_goal_closed_trades") or 0
        ),
        "remaining_closed_trades_to_edge_proof_goal": int(
            source.get("remaining_closed_trades_to_edge_proof_goal")
            or edge_proof_posture.get("remaining_closed_trades_to_edge_proof_goal")
            or 0
        ),
        "edge_proof_posture": {
            "state": str(edge_proof_posture.get("state") or "unknown"),
            "claim_state": str(edge_proof_posture.get("claim_state") or "unknown"),
            "focus": str(edge_proof_posture.get("focus") or ""),
            "summary": str(edge_proof_posture.get("summary") or ""),
        },
        "daily_edge_kpis": {
            "closed_trade_count": int(daily_edge_kpis.get("closed_trade_count", source.get("closed_trade_count", 0)) or 0),
            "sample_maturity_state": str(
                daily_edge_kpis.get("sample_maturity_state") or source.get("sample_maturity_state") or "unknown"
            ),
            "true_edge_ratio": round(_float(daily_edge_kpis.get("true_edge_ratio", source.get("true_edge_ratio"))), 4),
            "edge_decay_rate": round(_float(daily_edge_kpis.get("edge_decay_rate", source.get("edge_decay_rate"))), 4),
            "regime_dependency_state": str(
                daily_edge_kpis.get("regime_dependency_state") or source.get("regime_dependency_state") or "not_available"
            ),
        },
    }


def _edge_evolution_summary(
    validation_report: dict[str, Any],
    dashboard: dict[str, Any],
) -> dict[str, Any] | None:
    dashboard_source = dict((((dashboard or {}).get("signal_funnel") or {}).get("edge_evolution_rule") or {}))
    validation_source = dict((validation_report or {}).get("edge_evolution_rule_summary") or {})
    source = dashboard_source or validation_source
    if not source:
        return None
    return {
        "available": bool(source.get("available", True)),
        "advisory_only": bool(source.get("advisory_only", True)),
        "evolution_state": str(source.get("evolution_state") or "insufficient_sample"),
        "recommended_action": str(source.get("recommended_action") or "keep_current_baseline"),
        "allocation_bias": str(source.get("allocation_bias") or "hold_current_baseline"),
        "promotion_candidate_axis": str(source.get("promotion_candidate_axis") or "none"),
        "promotion_candidate_variant": str(source.get("promotion_candidate_variant") or "none"),
    }


def _review_followup_summary(
    validation_report: dict[str, Any],
    dashboard: dict[str, Any],
) -> dict[str, Any] | None:
    dashboard_source = dict((((dashboard or {}).get("signal_funnel") or {}).get("review_followup_ledger") or {}))
    validation_source = dict((validation_report or {}).get("review_followup_ledger_summary") or {})
    source = dashboard_source or validation_source
    if not source:
        return None
    return {
        "available": bool(source.get("available", False)),
        "last_status": str(source.get("last_status") or "none"),
        "last_action": str(source.get("last_action") or "none"),
        "recent_entry_count": int(source.get("recent_entry_count", 0) or 0),
        "last_followup_command": str(source.get("last_followup_command") or ""),
    }


def _edge_experiment_detail_parts(summary: dict[str, Any]) -> dict[str, Any]:
    posture = dict(summary.get("edge_proof_posture") or {})
    kpis = dict(summary.get("daily_edge_kpis") or {})
    return {
        "proof_state": str(posture.get("state") or "unknown"),
        "claim_state": str(posture.get("claim_state") or "unknown"),
        "proof_goal_closed_trades": int(summary.get("edge_proof_goal_closed_trades", 0) or 0),
        "remaining_closed_trades_to_edge_proof_goal": int(
            summary.get("remaining_closed_trades_to_edge_proof_goal", 0) or 0
        ),
        "closed_trade_count": int(kpis.get("closed_trade_count", 0) or 0),
        "true_edge_ratio": round(_float(kpis.get("true_edge_ratio", summary.get("true_edge_ratio"))), 4),
        "edge_decay_rate": round(_float(kpis.get("edge_decay_rate", summary.get("edge_decay_rate"))), 4),
        "regime_dependency_state": str(kpis.get("regime_dependency_state") or "not_available"),
    }


def _edge_experiment_summary_line(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "edge_experiment: unavailable"
    detail = _edge_experiment_detail_parts(summary)
    return (
        f"edge_experiment: state={summary.get('edge_state', 'insufficient_edge_measurement')} | "
        f"entry_timing={summary.get('entry_timing_preferred_variant', 'none')} | "
        f"execution_style={summary.get('execution_style_preferred_variant', 'none')} | "
        f"proof={detail['proof_state']}/{detail['claim_state']} | "
        f"closes={detail['closed_trade_count']}/{detail['proof_goal_closed_trades']} | "
        f"remaining={detail['remaining_closed_trades_to_edge_proof_goal']} | "
        f"regime={detail['regime_dependency_state']} | "
        f"true_edge={detail['true_edge_ratio']:.4f} | "
        f"decay={detail['edge_decay_rate']:.4f}"
    )


def _edge_evolution_summary_line(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "edge_evolution: unavailable"
    return (
        f"edge_evolution: state={summary.get('evolution_state', 'insufficient_sample')} | "
        f"action={summary.get('recommended_action', 'keep_current_baseline')} | "
        f"bias={summary.get('allocation_bias', 'hold_current_baseline')} | "
        f"promotion={summary.get('promotion_candidate_axis', 'none')}/{summary.get('promotion_candidate_variant', 'none')}"
    )


def _review_followup_summary_line(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "review_followup_ledger: unavailable"
    return (
        f"review_followup_ledger: status={summary.get('last_status', 'none')} | "
        f"action={summary.get('last_action', 'none')} | "
        f"entries={int(summary.get('recent_entry_count', 0) or 0)} | "
        f"cmd={summary.get('last_followup_command', '') or 'none'}"
    )


def _lineage_sample_summary_line(summary: dict[str, Any] | None) -> str:
    item = dict(summary or {})
    if not item:
        return "lineage_sample: unavailable"
    families = ",".join(str(name) for name in (item.get("families") or []) if str(name).strip()) or "none"
    return (
        f"lineage_sample: scope={item.get('scope', 'unknown')} | "
        f"families={families} | "
        f"closes={int(item.get('closed_trade_count', 0) or 0)}/{int(item.get('proof_goal_closed_trades', 0) or 0)} | "
        f"remaining={int(item.get('remaining_closed_trades_to_goal', 0) or 0)}"
    )


def _lineage_closed_fill_health(lineage_sample_summary: dict[str, Any] | None) -> dict[str, Any]:
    summary = dict(lineage_sample_summary or {})
    closed_trade_count = int(summary.get("closed_trade_count", 0) or 0)
    latest_closed_trade_at = str(summary.get("latest_closed_trade_at") or "")
    if closed_trade_count <= 0:
        return {
            "status": "no_closed_fills_present",
            "healthy": False,
            "closed_trade_count": 0,
            "latest_closed_trade_at": latest_closed_trade_at,
            "summary": "no lineage CLOSED fills observed yet",
        }
    return {
        "status": "closed_fills_present",
        "healthy": True,
        "closed_trade_count": closed_trade_count,
        "latest_closed_trade_at": latest_closed_trade_at,
        "summary": (
            f"lineage CLOSED fills observed: {closed_trade_count}"
            + (f" | latest={latest_closed_trade_at}" if latest_closed_trade_at else "")
        ),
    }


def _lineage_closed_fill_health_line(summary: dict[str, Any] | None) -> str:
    item = dict(summary or {})
    if not item:
        return "lineage_closed_fill_health: unavailable"
    return (
        f"lineage_closed_fill_health: status={item.get('status', 'unknown')} | "
        f"healthy={bool(item.get('healthy', False))} | "
        f"closes={int(item.get('closed_trade_count', 0) or 0)}"
    )


_LINEAGE_TARGET_FAMILIES = {"sweep_reversal", "trend_continuation"}
_ACTIVE_LINEAGE_SAMPLE_STALL_HOURS = 6


def _representative_candidates(dashboard: dict[str, Any]) -> dict[str, Any]:
    portfolio = dict((dashboard or {}).get("portfolio_summary") or {})

    def _candidate(row: dict[str, Any] | None, *, status: str) -> dict[str, Any] | None:
        item = dict(row or {})
        if not item:
            return None
        focus = dict(item.get("edge_experiment_focus") or {})
        return {
            "symbol": str(item.get("symbol") or ""),
            "status": status,
            "strategy_family": str(item.get("strategy_family") or ""),
            "block_reason": str(item.get("block_reason") or ""),
            "edge_state": str(focus.get("edge_state") or "insufficient_edge_measurement"),
            "entry_timing_preferred_variant": str(focus.get("entry_timing_preferred_variant") or "none"),
            "execution_style_preferred_variant": str(focus.get("execution_style_preferred_variant") or "none"),
        }

    accepted_rows = list(portfolio.get("accepted_candidates") or [])
    blocked_rows = list(portfolio.get("blocked_candidates") or [])
    return {
        "accepted": _candidate(accepted_rows[0] if accepted_rows else None, status="ACTIONABLE_ENTRY"),
        "blocked": _candidate(blocked_rows[0] if blocked_rows else None, status="BLOCKED_SETUP"),
    }


def _open_lineage_samples(families: list[str], *, limit: int = 3) -> dict[str, Any]:
    from app.core.enums import OrderLifecycleState
    from app.db.models import ExecutionFill, OrderIntent, OrderSubmission
    from app.db.session import SessionLocal

    normalized_families = {str(item).strip().lower() for item in families if str(item).strip()}
    if not normalized_families:
        return {
            "open_sample_count": 0,
            "sample_limit": int(max(1, limit)),
            "samples": [],
            "symbols": [],
            "summary": "open lineage samples: 0",
        }

    db = SessionLocal()
    try:
        closed_plan_ids = {
            str(plan_id)
            for (plan_id,) in db.query(ExecutionFill.plan_id)
            .filter(ExecutionFill.stage == "CLOSED")
            .distinct()
            .all()
        }
        rows = (
            db.query(OrderSubmission, OrderIntent)
            .join(OrderIntent, OrderIntent.intent_id == OrderSubmission.intent_id)
            .filter(
                OrderSubmission.adapter == "paper",
                OrderSubmission.execution_mode == "PAPER",
                OrderSubmission.state.in_(
                    [
                        OrderLifecycleState.ACKNOWLEDGED.value,
                        OrderLifecycleState.PARTIALLY_FILLED.value,
                        OrderLifecycleState.FILLED.value,
                    ]
                ),
            )
            .order_by(OrderSubmission.submitted_at.desc(), OrderSubmission.created_at.desc())
            .limit(50)
            .all()
        )
        samples: list[dict[str, Any]] = []
        seen_plan_ids: set[str] = set()
        for submission, intent in rows:
            family = str(getattr(intent, "strategy_family", "") or "").strip().lower()
            if family not in normalized_families:
                continue
            plan_id = str(getattr(submission, "plan_id", "") or "")
            if not plan_id or plan_id in closed_plan_ids or plan_id in seen_plan_ids:
                continue
            seen_plan_ids.add(plan_id)
            latest_fill = (
                db.query(ExecutionFill)
                .filter(ExecutionFill.plan_id == plan_id)
                .order_by(ExecutionFill.fill_ts.desc())
                .first()
            )
            if latest_fill is None:
                continue
            submitted_at = getattr(submission, "submitted_at", None) or getattr(submission, "created_at", None)
            if isinstance(submitted_at, datetime) and submitted_at.tzinfo is None:
                submitted_at = submitted_at.replace(tzinfo=timezone.utc)
            elif isinstance(submitted_at, datetime):
                submitted_at = submitted_at.astimezone(timezone.utc)
            last_fill_at = getattr(latest_fill, "fill_ts", None)
            if isinstance(last_fill_at, datetime) and last_fill_at.tzinfo is None:
                last_fill_at = last_fill_at.replace(tzinfo=timezone.utc)
            elif isinstance(last_fill_at, datetime):
                last_fill_at = last_fill_at.astimezone(timezone.utc)
            hours_open = 0.0
            if isinstance(submitted_at, datetime):
                hours_open = max((datetime.now(timezone.utc) - submitted_at).total_seconds() / 3600.0, 0.0)
            samples.append(
                {
                    "symbol": str(getattr(submission, "symbol", "") or ""),
                    "status": "OPEN_PAPER_SAMPLE",
                    "strategy_family": family,
                    "plan_id": plan_id,
                    "submission_id": str(getattr(submission, "submission_id", "") or ""),
                    "submitted_at": submitted_at.isoformat() if isinstance(submitted_at, datetime) else "",
                    "hours_open": round(hours_open, 2),
                    "last_fill_stage": str(getattr(latest_fill, "stage", "") or "none"),
                    "last_fill_at": last_fill_at.isoformat() if isinstance(last_fill_at, datetime) else "",
                }
            )
    finally:
        db.close()

    limited = samples[: max(1, int(limit))]
    symbols = [str(item.get("symbol") or "") for item in limited if str(item.get("symbol") or "").strip()]
    preview = ", ".join(
        f"{item.get('symbol') or 'unknown'}:{item.get('last_fill_stage') or 'none'}" for item in limited
    )
    return {
        "open_sample_count": len(samples),
        "sample_limit": int(max(1, limit)),
        "samples": limited,
        "symbols": symbols,
        "summary": (
            f"open lineage samples={len(samples)}"
            + (f" | top={preview}" if preview else "")
        ),
    }


def _active_lineage_sample_focus(families: list[str]) -> dict[str, Any] | None:
    summary = _open_lineage_samples(families, limit=1)
    samples = list(summary.get("samples") or [])
    if not samples:
        return None
    return dict(samples[0])


def _open_lineage_sample_summary_line(summary: dict[str, Any] | None) -> str:
    item = dict(summary or {})
    if not item:
        return "open_lineage_samples: unavailable"
    samples = list(item.get("samples") or [])
    preview = ", ".join(
        f"{sample.get('symbol') or 'unknown'}:{sample.get('last_fill_stage') or 'none'}"
        for sample in samples
    )
    line = (
        f"open_lineage_samples: count={int(item.get('open_sample_count', 0) or 0)} | "
        f"limit={int(item.get('sample_limit', 0) or 0)}"
    )
    if preview:
        line = f"{line} | top={preview}"
    return line


def _active_lineage_sample_health(
    sample: dict[str, Any] | None,
    *,
    threshold_hours: int = _ACTIVE_LINEAGE_SAMPLE_STALL_HOURS,
) -> dict[str, Any]:
    item = dict(sample or {})
    if not item:
        return {
            "active": False,
            "status": "none",
            "threshold_hours": int(max(1, threshold_hours)),
            "hours_open": 0.0,
            "symbol": "",
            "strategy_family": "",
            "plan_id": "",
            "last_fill_stage": "none",
            "last_fill_at": "",
            "summary": "no active lineage paper sample",
        }
    hours_open = round(float(item.get("hours_open", 0.0) or 0.0), 2)
    active = hours_open >= float(max(1, threshold_hours))
    return {
        "active": active,
        "status": "stalled" if active else "tracking",
        "threshold_hours": int(max(1, threshold_hours)),
        "hours_open": hours_open,
        "symbol": str(item.get("symbol") or ""),
        "strategy_family": str(item.get("strategy_family") or ""),
        "plan_id": str(item.get("plan_id") or ""),
        "last_fill_stage": str(item.get("last_fill_stage") or "none"),
        "last_fill_at": str(item.get("last_fill_at") or ""),
        "summary": (
            f"open lineage sample {str(item.get('symbol') or 'unknown')} "
            f"has remained open for {hours_open:.1f}h "
            f"(threshold={max(1, threshold_hours)}h)"
        ),
    }


def _representative_candidate_summary_line(label: str, candidate: dict[str, Any] | None) -> str:
    item = dict(candidate or {})
    if not item:
        return f"{label}: none"
    line = (
        f"{label}: {item.get('symbol') or 'unknown'} | "
        f"family={item.get('strategy_family') or 'unknown'} | "
        f"edge={item.get('edge_state') or 'insufficient_edge_measurement'} | "
        f"split={(item.get('entry_timing_preferred_variant') or 'none')}/{(item.get('execution_style_preferred_variant') or 'none')}"
    )
    if item.get("status"):
        line = f"{line} | status={item.get('status')}"
    if item.get("block_reason"):
        line = f"{line} | reason={item.get('block_reason')}"
    return line


def _split_review_followup_command(*, symbol: str, universe: str, days: int, action: str) -> str:
    return (
        f"./.venv/bin/python scripts/run_split_review_followup.py "
        f"--symbol {symbol.upper()} --universe {universe} --days {max(1, int(days))} --action {action}"
    )


def _experiment_review_target(
    operator_action_priority: dict[str, Any] | None,
    *,
    target_key: str,
    preferred_key: str,
    action: str,
    universe: str,
    days: int,
) -> dict[str, Any] | None:
    priority = dict(operator_action_priority or {})
    context = dict(priority.get("experiment_context") or {})
    target = dict(context.get(target_key) or {})
    if not target:
        return None
    symbol = str(target.get("symbol") or "")
    return {
        "action": action,
        "preferred_variant": str(context.get(preferred_key) or "none"),
        "symbol": symbol,
        "status": str(target.get("status") or ""),
        "strategy_family": str(target.get("strategy_family") or ""),
        "block_reason": str(target.get("block_reason") or ""),
        "focus_source": str(target.get("focus_source") or ""),
        "followup_command": (
            _split_review_followup_command(
                symbol=symbol,
                universe=universe,
                days=days,
                action=action,
            )
            if symbol
            else ""
        ),
    }


def _resolved_selected_trial(validation_report: dict[str, Any] | None) -> dict[str, Any]:
    report = dict(validation_report or {})
    deployment = dict(report.get("deployment_approval_summary") or {})
    trial_writer_summary = dict(report.get("strategy_v2_pbo_dsr_trial_writer_summary") or {})
    threshold_runner_summary = dict(report.get("strategy_v2_pbo_dsr_threshold_runner_summary") or {})

    writer_selected_trial_run_id = trial_writer_summary.get("selected_trial_run_id")
    if writer_selected_trial_run_id:
        return {
            "selected_trial_run_id": writer_selected_trial_run_id,
            "resolution_source": "trial_writer_summary",
            "raw_trial_writer_selected_trial_run_id": writer_selected_trial_run_id,
            "threshold_lineage_winner_run_id": deployment.get("threshold_lineage_winner_run_id"),
            "threshold_lineage_winner_source": deployment.get("threshold_lineage_winner_source"),
            "threshold_lineage_winner_type": deployment.get("threshold_lineage_winner_type"),
            "threshold_lineage_audit_status": deployment.get("threshold_lineage_audit_status"),
        }

    threshold_runner_selected_trial_run_id = threshold_runner_summary.get("selected_trial_run_id")
    if threshold_runner_selected_trial_run_id:
        return {
            "selected_trial_run_id": threshold_runner_selected_trial_run_id,
            "resolution_source": "threshold_runner_summary",
            "raw_trial_writer_selected_trial_run_id": writer_selected_trial_run_id,
            "threshold_lineage_winner_run_id": deployment.get("threshold_lineage_winner_run_id"),
            "threshold_lineage_winner_source": deployment.get("threshold_lineage_winner_source"),
            "threshold_lineage_winner_type": deployment.get("threshold_lineage_winner_type"),
            "threshold_lineage_audit_status": deployment.get("threshold_lineage_audit_status"),
        }

    threshold_lineage_winner_run_id = deployment.get("threshold_lineage_winner_run_id")
    threshold_lineage_winner_type = str(deployment.get("threshold_lineage_winner_type") or "").strip().lower()
    threshold_lineage_audit_status = str(deployment.get("threshold_lineage_audit_status") or "").strip().upper()
    if (
        threshold_lineage_winner_run_id
        and threshold_lineage_winner_type in {"true_threshold", "runtime_proxy"}
        and threshold_lineage_audit_status == "PASS"
    ):
        return {
            "selected_trial_run_id": threshold_lineage_winner_run_id,
            "resolution_source": "deployment_threshold_lineage_winner",
            "raw_trial_writer_selected_trial_run_id": writer_selected_trial_run_id,
            "threshold_lineage_winner_run_id": threshold_lineage_winner_run_id,
            "threshold_lineage_winner_source": deployment.get("threshold_lineage_winner_source"),
            "threshold_lineage_winner_type": deployment.get("threshold_lineage_winner_type"),
            "threshold_lineage_audit_status": deployment.get("threshold_lineage_audit_status"),
        }

    return {
        "selected_trial_run_id": None,
        "resolution_source": "unresolved",
        "raw_trial_writer_selected_trial_run_id": writer_selected_trial_run_id,
        "threshold_lineage_winner_run_id": deployment.get("threshold_lineage_winner_run_id"),
        "threshold_lineage_winner_source": deployment.get("threshold_lineage_winner_source"),
        "threshold_lineage_winner_type": deployment.get("threshold_lineage_winner_type"),
        "threshold_lineage_audit_status": deployment.get("threshold_lineage_audit_status"),
    }


def _lineage_gate_ready(selected_trial_run_id: Any, trial_runs_written: Any) -> bool:
    return bool(selected_trial_run_id) or int(trial_runs_written or 0) > 0


def _candidate_gate_ready(
    representative_candidates: dict[str, Any] | None,
    entry_timing_review_target: dict[str, Any] | None,
    execution_style_review_target: dict[str, Any] | None,
    active_lineage_sample_focus: dict[str, Any] | None,
) -> bool:
    accepted = dict((representative_candidates or {}).get("accepted") or {})
    accepted_family = str(accepted.get("strategy_family") or "").strip().lower()
    if accepted and accepted_family in _LINEAGE_TARGET_FAMILIES:
        return True

    active_sample = dict(active_lineage_sample_focus or {})
    active_sample_family = str(active_sample.get("strategy_family") or "").strip().lower()
    if active_sample and active_sample_family in _LINEAGE_TARGET_FAMILIES:
        return True

    for target in (entry_timing_review_target, execution_style_review_target):
        item = dict(target or {})
        family = str(item.get("strategy_family") or "").strip().lower()
        status = str(item.get("status") or "").strip().upper()
        if item and family in _LINEAGE_TARGET_FAMILIES and status.startswith("ACTIONABLE"):
            return True
    return False


def _edge_sample_gate_ready(
    edge_experiment_review: dict[str, Any] | None,
    lineage_sample_summary: dict[str, Any] | None = None,
) -> bool:
    lineage_summary = dict(lineage_sample_summary or {})
    if lineage_summary:
        proof_goal = int(lineage_summary.get("proof_goal_closed_trades", 0) or 0)
        closed_count = int(lineage_summary.get("closed_trade_count", 0) or 0)
        return proof_goal > 0 and closed_count >= proof_goal
    summary = dict(edge_experiment_review or {})
    if not summary:
        return False
    detail = _edge_experiment_detail_parts(summary)
    proof_goal = int(detail.get("proof_goal_closed_trades", 0) or 0)
    closed_count = int(detail.get("closed_trade_count", 0) or 0)
    return proof_goal > 0 and closed_count >= proof_goal


def _readiness_gates(
    *,
    selected_trial_run_id: Any,
    trial_runs_written: Any,
    representative_candidates: dict[str, Any] | None,
    entry_timing_review_target: dict[str, Any] | None,
    execution_style_review_target: dict[str, Any] | None,
    active_lineage_sample_focus: dict[str, Any] | None,
    edge_experiment_review: dict[str, Any] | None,
    lineage_sample_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    lineage_ready = _lineage_gate_ready(selected_trial_run_id, trial_runs_written)
    candidate_ready = _candidate_gate_ready(
        representative_candidates,
        entry_timing_review_target,
        execution_style_review_target,
        active_lineage_sample_focus,
    )
    edge_sample_ready = _edge_sample_gate_ready(edge_experiment_review, lineage_sample_summary)
    all_ready = lineage_ready and candidate_ready and edge_sample_ready
    return {
        "lineage_gate_ready": lineage_ready,
        "candidate_gate_ready": candidate_ready,
        "edge_sample_gate_ready": edge_sample_ready,
        "all_ready": all_ready,
        "summary": (
            f"lineage={lineage_ready} | candidate={candidate_ready} | "
            f"edge_sample={edge_sample_ready} | all_ready={all_ready}"
        ),
    }


def _experiment_review_target_line(label: str, target: dict[str, Any] | None) -> str:
    item = dict(target or {})
    if not item:
        return f"{label}: none"
    line = (
        f"{label}: action={item.get('action') or 'unknown'} | "
        f"target={item.get('symbol') or 'unknown'} | "
        f"variant={item.get('preferred_variant') or 'none'} | "
        f"status={item.get('status') or 'unknown'} | "
        f"family={item.get('strategy_family') or 'unknown'}"
    )
    if item.get("block_reason"):
        line = f"{line} | reason={item.get('block_reason')}"
    if item.get("focus_source"):
        line = f"{line} | focus={item.get('focus_source')}"
    if item.get("followup_command"):
        line = f"{line} | cmd={item.get('followup_command')}"
    return line


def _active_lineage_sample_focus_line(sample: dict[str, Any] | None) -> str:
    item = dict(sample or {})
    if not item:
        return "active_lineage_sample_focus: none"
    line = (
        f"active_lineage_sample_focus: {item.get('symbol') or 'unknown'} | "
        f"family={item.get('strategy_family') or 'unknown'} | "
        f"status={item.get('status') or 'unknown'} | "
        f"plan_id={item.get('plan_id') or 'unknown'}"
    )
    if item.get("hours_open") is not None:
        line = f"{line} | hours_open={float(item.get('hours_open') or 0.0):.2f}"
    if item.get("last_fill_stage"):
        line = f"{line} | last_fill={item.get('last_fill_stage')}"
    return line


def _active_lineage_sample_health_line(item: dict[str, Any] | None) -> str:
    sample = dict(item or {})
    return (
        f"active_lineage_sample_health: active={bool(sample.get('active', False))} | "
        f"hours_open={float(sample.get('hours_open', 0.0) or 0.0):.2f} | "
        f"threshold_hours={int(sample.get('threshold_hours', 0) or 0)} | "
        f"status={sample.get('status') or 'none'}"
    )


def _risk_gate_summary(checklist: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(checklist or {})
    checks = list(payload.get("checks") or [])
    for item in checks:
        row = dict(item or {})
        if str(row.get("item_id") or "") != "risk_gate_open":
            continue
        evidence = dict(row.get("evidence") or {})
        operating_lock = dict(evidence.get("operating_lock") or {})
        daily_stats = dict(operating_lock.get("daily_stats") or {})
        last_trade = dict(daily_stats.get("last_trade") or {})
        return {
            "status": str(row.get("status") or "NOT_AVAILABLE"),
            "blocking": bool(row.get("blocking", False)),
            "summary": str(row.get("summary") or ""),
            "risk_state": str(evidence.get("risk_state") or "UNKNOWN"),
            "risk_reason": str(evidence.get("risk_reason") or "unknown"),
            "unlock_at": operating_lock.get("unlock_at"),
            "scope": str(operating_lock.get("scope") or ""),
            "strategy_mode": str(operating_lock.get("strategy_mode") or ""),
            "daily_realized_r": float(daily_stats.get("realized_r", 0.0) or 0.0),
            "daily_trades": int(daily_stats.get("trades", 0) or 0),
            "daily_loss_streak": int(daily_stats.get("loss_streak", 0) or 0),
            "daily_loss_limit_r": float(daily_stats.get("loss_limit_r", 0.0) or 0.0),
            "last_trade_symbol": str(last_trade.get("symbol") or ""),
            "last_trade_closed_ts": last_trade.get("closed_ts"),
            "last_trade_realized_r": float(last_trade.get("realized_r", 0.0) or 0.0),
            "last_trade_exit_reason": str(last_trade.get("exit_reason") or ""),
        }
    return {
        "status": "NOT_AVAILABLE",
        "blocking": False,
        "summary": "risk gate evidence unavailable",
    }


def _risk_gate_summary_line(item: dict[str, Any] | None) -> str:
    summary = dict(item or {})
    return (
        f"risk_gate: status={summary.get('status') or 'NOT_AVAILABLE'} | "
        f"state={summary.get('risk_state') or 'UNKNOWN'} | "
        f"reason={summary.get('risk_reason') or 'unknown'} | "
        f"unlock_at={summary.get('unlock_at') or 'n/a'} | "
        f"daily_r={float(summary.get('daily_realized_r', 0.0) or 0.0):.4f}/"
        f"{float(summary.get('daily_loss_limit_r', 0.0) or 0.0):.4f} | "
        f"loss_streak={int(summary.get('daily_loss_streak', 0) or 0)}"
    )


def _risk_gate_unlock_summary(item: dict[str, Any] | None) -> dict[str, Any]:
    summary = dict(item or {})
    unlock_at = summary.get("unlock_at")
    risk_state = str(summary.get("risk_state") or "").upper()
    status = str(summary.get("status") or "").upper()
    if unlock_at and risk_state == "CLOSED" and status == "FAIL":
        return {
            "active": True,
            "status": "scheduled_unlock",
            "unlock_at": unlock_at,
            "summary": f"operating lock is expected to auto-clear at {unlock_at}",
        }
    return {
        "active": False,
        "status": "not_locked",
        "unlock_at": unlock_at,
        "summary": "no scheduled operating-lock unlock is pending",
    }


def _risk_gate_unlock_summary_line(item: dict[str, Any] | None) -> str:
    summary = dict(item or {})
    line = (
        f"risk_gate_unlock: active={bool(summary.get('active', False))} | "
        f"status={summary.get('status') or 'not_available'} | "
        f"unlock_at={summary.get('unlock_at') or 'n/a'}"
    )
    if summary.get("expected_stage_after_unlock"):
        line = f"{line} | expected_stage={summary.get('expected_stage_after_unlock')}"
    if summary.get("expected_checklist_status_after_unlock"):
        line = f"{line} | expected_checklist={summary.get('expected_checklist_status_after_unlock')}"
    return line


def _post_unlock_review_summary(
    *,
    risk_gate_summary: dict[str, Any] | None,
    risk_gate_unlock_summary: dict[str, Any] | None,
    validation_report: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
    stage: str,
    lineage_gate_ready: bool,
    edge_sample_gate_ready: bool,
    symbol: str,
    universe: str,
    days: int,
) -> dict[str, Any]:
    risk_summary = dict(risk_gate_summary or {})
    unlock_summary = dict(risk_gate_unlock_summary or {})
    deployment = dict((validation_report or {}).get("deployment_approval_summary") or {})
    validation_surface = _surface_strip_summary(validation_report, surface_type="validation")
    checklist_status = str((checklist or {}).get("overall_status") or "UNKNOWN").upper()
    risk_status = str(risk_summary.get("status") or "NOT_AVAILABLE").upper()
    risk_state = str(risk_summary.get("risk_state") or "UNKNOWN").upper()
    stage_value = str(stage or "CHECK_MANUALLY")
    post_unlock_stage = str(unlock_summary.get("expected_stage_after_unlock") or "")
    post_unlock_checklist = str(unlock_summary.get("expected_checklist_status_after_unlock") or "")
    review_window_open = (
        risk_status == "PASS"
        and risk_state == "OPEN"
        and lineage_gate_ready
        and edge_sample_gate_ready
    )
    active = bool(unlock_summary.get("active", False)) or review_window_open
    if review_window_open:
        next_review_step = "review_validation_and_checklist_before_runtime_reopen"
    elif risk_state != "OPEN" or risk_status != "PASS":
        next_review_step = "wait_for_operating_lock_to_clear"
    else:
        next_review_step = "wait_for_lineage_sample_and_runtime_gate_alignment"
    bundle_review_command = (
        f"./.venv/bin/python scripts/run_post_unlock_review.py "
        f"--symbol {symbol} --universe {universe} --days {days}"
    )
    primary_review_command = (
        f"./.venv/bin/python scripts/run_micro_live_preflight.py "
        f"--symbol {symbol} --universe {universe} --days {days}"
    )
    secondary_review_command = (
        f"./.venv/bin/python scripts/run_post_live_pruning_review.py "
        f"--symbol {symbol} --universe {universe} --days {days}"
    )
    signoff_review_command = (
        f"./.venv/bin/python scripts/run_runtime_signoff_review.py "
        f"--symbol {symbol} --universe {universe} --days {days}"
    )
    summary = (
        f"post_unlock_review: active={active} | review_window_open={review_window_open} | "
        f"current_stage={stage_value} | checklist={checklist_status} | "
        f"validation={deployment.get('playbook_go_no_go') or validation_surface.get('approve_value') or 'n/a'}"
    )
    if post_unlock_stage:
        summary = f"{summary} | expected_stage={post_unlock_stage}"
    if post_unlock_checklist:
        summary = f"{summary} | expected_checklist={post_unlock_checklist}"
    return {
        "active": active,
        "review_window_open": review_window_open,
        "risk_gate_status": risk_status,
        "risk_gate_state": risk_state,
        "current_stage": stage_value,
        "current_checklist_status": checklist_status,
        "current_validation_playbook_go_no_go": str(deployment.get("playbook_go_no_go") or ""),
        "current_validation_approve_value": str(validation_surface.get("approve_value") or ""),
        "expected_stage_after_unlock": post_unlock_stage or None,
        "expected_checklist_status_after_unlock": post_unlock_checklist or None,
        "next_review_step": next_review_step,
        "bundle_review_command": bundle_review_command,
        "primary_review_command": primary_review_command,
        "secondary_review_command": secondary_review_command,
        "signoff_review_command": signoff_review_command,
        "summary": summary,
    }


def _post_unlock_review_summary_line(item: dict[str, Any] | None) -> str:
    summary = dict(item or {})
    return (
        f"post_unlock_review: active={bool(summary.get('active', False))} | "
        f"review_window_open={bool(summary.get('review_window_open', False))} | "
        f"current_stage={summary.get('current_stage') or 'unknown'} | "
        f"checklist={summary.get('current_checklist_status') or 'UNKNOWN'} | "
        f"validation={summary.get('current_validation_playbook_go_no_go') or summary.get('current_validation_approve_value') or 'n/a'} | "
        f"next={summary.get('next_review_step') or 'wait_for_operating_lock_to_clear'}"
    )


def _post_unlock_review_commands_line(item: dict[str, Any] | None) -> str:
    summary = dict(item or {})
    return (
        f"post_unlock_review_commands: bundle={summary.get('bundle_review_command') or 'n/a'} | "
        f"primary={summary.get('primary_review_command') or 'n/a'} | "
        f"secondary={summary.get('secondary_review_command') or 'n/a'} | "
        f"signoff={summary.get('signoff_review_command') or 'n/a'}"
    )


def _default_post_unlock_bundle_result(review_summary: dict[str, Any] | None) -> dict[str, Any]:
    summary = dict(review_summary or {})
    review_window_open = bool(summary.get("review_window_open", False))
    status = "review_window_open_pending_bundle" if review_window_open else "waiting_for_review_window"
    summary_text = (
        "post-unlock bundle review is waiting for execution after the review window opens"
        if review_window_open
        else "post-unlock bundle review is waiting for the review window to open"
    )
    return {
        "active": bool(summary.get("active", False)),
        "executed": False,
        "status": status,
        "summary": summary_text,
        "bundle_review_command": str(summary.get("bundle_review_command") or ""),
    }


def _post_unlock_bundle_result_line(item: dict[str, Any] | None) -> str:
    summary = dict(item or {})
    return (
        f"post_unlock_bundle: active={bool(summary.get('active', False))} | "
        f"executed={bool(summary.get('executed', False))} | "
        f"status={summary.get('status') or 'not_available'}"
    )


def _runtime_reopen_status(
    *,
    risk_gate_summary: dict[str, Any] | None,
    review_summary: dict[str, Any] | None,
    bundle_result: dict[str, Any] | None,
) -> dict[str, Any]:
    risk_summary = dict(risk_gate_summary or {})
    review = dict(review_summary or {})
    bundle = dict(bundle_result or {})
    risk_closed = str(risk_summary.get("risk_state") or "").upper() == "CLOSED"
    review_window_open = bool(review.get("review_window_open", False))
    bundle_status = str(bundle.get("status") or "").upper()

    if risk_closed:
        status = "waiting_for_operating_lock"
        ready = False
    elif not review_window_open:
        status = "waiting_for_review_window"
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
    return {
        "status": status,
        "ready": ready,
        "summary": f"runtime_reopen_status={status}",
    }


def _runtime_reopen_status_line(item: dict[str, Any] | None) -> str:
    summary = dict(item or {})
    return (
        f"runtime_reopen_status: status={summary.get('status') or 'not_available'} | "
        f"ready={bool(summary.get('ready', False))}"
    )


def _runtime_signoff_summary(
    *,
    validation_report: dict[str, Any] | None,
    checklist: dict[str, Any] | None,
    runtime_reopen_status: dict[str, Any] | None,
) -> dict[str, Any]:
    runtime = dict(runtime_reopen_status or {})
    validation = dict(validation_report or {})
    checklist_payload = dict(checklist or {})

    deployment = dict(validation.get("deployment_approval_summary") or {})
    friction = dict(validation.get("execution_friction_measurement_summary") or {})
    kill_condition = dict(validation.get("kill_condition_automation_summary") or {})
    edge_review = dict(validation.get("edge_experiment_review_summary") or {})
    edge_kpis = dict(edge_review.get("daily_edge_kpis") or {})
    checklist_checks = list(checklist_payload.get("checks") or [])
    approval_template_focus = dict(validation.get("approval_template_focus") or {})

    required_reviews: list[dict[str, str]] = []
    advisory_reviews: list[dict[str, str]] = []

    def _append_unique(
        target: list[dict[str, str]],
        code: str,
        summary: str,
        *,
        current_value: str = "",
        clear_when: str = "",
    ) -> None:
        if any(item.get("code") == code for item in target):
            return
        target.append(
            {
                "code": code,
                "summary": summary,
                "current_value": current_value,
                "clear_when": clear_when,
            }
        )

    if str(deployment.get("playbook_go_no_go") or "") == "MANUAL_REVIEW":
        worst_scenario = str(deployment.get("replay_derived_worst_scenario") or "not_available")
        worst_scenario_status = str(deployment.get("replay_derived_worst_scenario_status") or "NOT_AVAILABLE")
        worst_scenario_reason = str(deployment.get("replay_derived_worst_scenario_reason") or "not_available")
        _append_unique(
            required_reviews,
            "approval_template_review",
            (
                "approval template warning remains because the replay-derived "
                f"worst scenario {worst_scenario} is still {worst_scenario_status}"
            ),
            current_value=(
                f"topline_code={deployment.get('topline_code') or deployment.get('template_reason') or 'unknown'}"
                f", playbook_go_no_go={deployment.get('playbook_go_no_go') or 'unknown'}"
                f", worst={worst_scenario}/{worst_scenario_status}"
                f", reason={worst_scenario_reason}"
            ),
            clear_when="validation topline REVIEW clears and playbook_go_no_go is no longer MANUAL_REVIEW",
        )
        required_reviews[-1]["worst_scenario"] = worst_scenario
        required_reviews[-1]["worst_scenario_status"] = worst_scenario_status
        required_reviews[-1]["worst_scenario_reason"] = worst_scenario_reason

    reconciliation_state = str(friction.get("reconciliation_state") or "")
    if reconciliation_state.startswith("degraded"):
        _append_unique(
            required_reviews,
            "execution_reconciliation_review",
            "execution reconciliation remains degraded and should be reviewed before reopening",
            current_value=f"reconciliation_state={reconciliation_state or 'unknown'}",
            clear_when="execution reconciliation state is no longer degraded",
        )

    kill_condition_state = str(kill_condition.get("kill_condition_state") or "")
    if kill_condition_state == "kill_switch_review":
        _append_unique(
            required_reviews,
            "kill_switch_review",
            "kill-switch review is still advisory-active and should be acknowledged before reopening",
            current_value=f"kill_condition_state={kill_condition_state or 'unknown'}",
            clear_when="kill_condition_state is no longer kill_switch_review",
        )

    portfolio_warn = next(
        (
            check
            for check in checklist_checks
            if str(check.get("item_id") or "") == "portfolio_headroom" and str(check.get("status") or "") == "WARN"
        ),
        None,
    )
    if portfolio_warn is not None:
        _append_unique(
            advisory_reviews,
            "portfolio_headroom_review",
            str(portfolio_warn.get("summary") or "portfolio headroom remains constrained"),
            current_value=str(portfolio_warn.get("summary") or "portfolio headroom remains constrained"),
            clear_when="portfolio headroom warning clears or the next candidate fits within current caps",
        )

    closed_trade_count = int(edge_review.get("closed_trade_count") or edge_kpis.get("closed_trade_count") or 0)
    goal_closed_trades = int(edge_review.get("edge_proof_goal_closed_trades") or 0)
    if goal_closed_trades > 0 and closed_trade_count < goal_closed_trades:
        _append_unique(
            advisory_reviews,
            "symbol_edge_thin",
            f"BTCUSDC symbol proof is still thin at {closed_trade_count}/{goal_closed_trades}",
            current_value=f"btc_symbol_sample={closed_trade_count}/{goal_closed_trades}",
            clear_when="BTCUSDC symbol proof reaches its target or is explicitly treated as advisory-only",
        )

    runtime_ready = run_runtime_signoff_review._runtime_signoff_eligible_status(runtime.get("status"))
    if not runtime_ready:
        status = "not_ready"
    elif required_reviews:
        status = "manual_signoff_required"
    else:
        status = "ready_for_operator_signoff"

    operator_recommendation, operator_recommendation_reason = run_runtime_signoff_review._fallback_operator_recommendation(
        runtime_ready=runtime_ready,
        required_reviews=required_reviews,
    )
    runtime_decision: dict[str, Any] = {}
    runtime_reopen_gate_summary: dict[str, Any] = {}
    if approval_template_focus:
        runtime_decision = run_runtime_signoff_review._build_runtime_decision(
            runtime_ready=runtime_ready,
            required_reviews=required_reviews,
            approval_template_focus=approval_template_focus,
        )
        if runtime_decision.get("effective_action"):
            operator_recommendation = str(runtime_decision.get("effective_action") or operator_recommendation)
            if operator_recommendation == "conditional_micro_live_signoff":
                operator_recommendation_reason = (
                    "legacy replay remains red, but the post-patch mitigation cohort cleared the red thresholds; "
                    "limit any reopen to MICRO_LIVE while operator sign-off remains manual"
                )
            elif operator_recommendation == "conditional_full_live_signoff":
                operator_recommendation_reason = (
                    "legacy replay remains red, but the post-patch mitigation cohort cleared the conditional FULL LIVE "
                    "thresholds; any reopen still requires explicit operator sign-off"
                )
            elif operator_recommendation == "hold_runtime_reopen":
                operator_recommendation_reason = "replay downside exceeds operating tolerance; keep runtime closed"
            elif operator_recommendation == "manual_signoff_required":
                operator_recommendation_reason = "runtime is reopen-ready but required operator review items remain"
            elif operator_recommendation == "proceed_to_operator_signoff":
                operator_recommendation_reason = "runtime is reopen-ready and no required operator review items remain"
        runtime_reopen_gate_summary = run_runtime_signoff_review._build_runtime_reopen_gate_summary(
            approval_template_focus,
            runtime_decision,
        )

    review_labels = ", ".join(item["code"] for item in required_reviews) or "none"
    summary = (
        f"runtime sign-off status={status} | required={review_labels}"
        if runtime_ready
        else f"runtime sign-off is pending until reopen status becomes ready | required={review_labels}"
    )
    return {
        "status": status,
        "required_reviews": required_reviews,
        "advisory_reviews": advisory_reviews,
        "required_count": len(required_reviews),
        "advisory_count": len(advisory_reviews),
        "required_clearance_line": " | ".join(
            f"{item['code']}=>{item.get('clear_when') or 'clear when warning is removed'}"
            for item in required_reviews
        ),
        "operator_recommendation": operator_recommendation,
        "operator_recommendation_reason": operator_recommendation_reason,
        "summary": summary,
        "approval_template_focus": approval_template_focus,
        "runtime_decision": runtime_decision,
        "runtime_reopen_gate_summary": runtime_reopen_gate_summary,
    }


def _runtime_signoff_summary_line(item: dict[str, Any] | None) -> str:
    summary = dict(item or {})
    required = list(summary.get("required_reviews") or [])
    decision = dict(summary.get("runtime_decision") or {})
    labels = ",".join(str(item.get("code") or "") for item in required) or "none"
    clearance_line = str(summary.get("required_clearance_line") or "")
    focus = ""
    for review in required:
        if str(review.get("code") or "") == "approval_template_review":
            worst = str(review.get("worst_scenario") or "").strip()
            status = str(review.get("worst_scenario_status") or "").strip()
            if worst and status:
                focus = f"{worst}/{status}"
            break
    return (
        f"runtime_signoff: status={summary.get('status') or 'not_available'} | "
        f"required={labels} | advisory_count={int(summary.get('advisory_count') or 0)}"
        + (f" | band={decision.get('band')}" if decision.get("band") else "")
        + (f" | focus={focus}" if focus else "")
        + (f" | recommend={summary.get('operator_recommendation')}" if summary.get("operator_recommendation") else "")
        + (f" | clear_when={clearance_line}" if clearance_line else "")
    )


def _runtime_reopen_gate_summary_line(item: dict[str, Any] | None) -> str:
    summary = dict(item or {})
    micro = dict(summary.get("micro_live") or {})
    full = dict(summary.get("full_live") or {})
    return (
        "runtime_reopen_gate: "
        f"micro={micro.get('status') or 'not_available'}"
        f"({int(micro.get('closed_trade_count') or 0)}/{int(micro.get('min_closed_trades') or 0)})"
        f" | full={full.get('status') or 'not_available'}"
        f"({int(full.get('closed_trade_count') or 0)}/{int(full.get('min_closed_trades') or 0)})"
        + (f" | scope={summary.get('active_scope')}" if summary.get("active_scope") else "")
        + (f" | action={summary.get('effective_action')}" if summary.get("effective_action") else "")
    )


def _runtime_preflight_summary_line(item: dict[str, Any] | None) -> str:
    summary = dict(item or {})
    failed_checks = list(summary.get("failed_checks") or [])
    first_failed = dict(failed_checks[0]) if failed_checks else {}
    return (
        f"runtime_preflight: status={summary.get('status') or 'not_available'}"
        + (f" | action={summary.get('effective_action')}" if summary.get("effective_action") else "")
        + (f" | summary={summary.get('summary')}" if summary.get("summary") else "")
        + (
            f" | first_failed={first_failed.get('name')}/{first_failed.get('message')}"
            if first_failed
            else ""
        )
    )


def _runtime_operator_signoff_summary_line(item: dict[str, Any] | None) -> str:
    summary = dict(item or {})
    review_codes = ",".join(str(code) for code in list(summary.get("required_review_codes") or []) if str(code).strip()) or "none"
    return (
        f"runtime_operator_signoff: status={summary.get('status') or 'not_available'}"
        + (f" | action={summary.get('effective_action')}" if summary.get("effective_action") else "")
        + (f" | scope={summary.get('allowed_scope')}" if summary.get("allowed_scope") else "")
        + (f" | preflight={summary.get('preflight_status')}" if summary.get("preflight_status") else "")
        + (f" | required={review_codes}" if review_codes else "")
        + (f" | next={summary.get('next_step')}" if summary.get("next_step") else "")
    )


def _runtime_mitigation_summary_line(item: dict[str, Any] | None) -> str:
    summary = dict(item or {})
    return (
        f"runtime_mitigation: primary={summary.get('primary_focus_label') or summary.get('primary_action_code') or 'none'}"
        f"/{summary.get('primary_action_status') or 'none'}"
        + (
            f" | next={summary.get('secondary_focus_label') or 'none'}/{summary.get('secondary_status') or 'none'}"
            if summary
            else ""
        )
        + (
            f" | cmd={summary.get('primary_action_command')}"
            if summary.get("primary_action_command")
            else ""
        )
    )


def _runtime_mitigation_wait_summary_line(item: dict[str, Any] | None) -> str:
    summary = dict(item or {})
    allowed_sessions = ",".join(str(item) for item in list(summary.get("allowed_sessions") or []) if str(item).strip())
    return (
        f"runtime_mitigation_wait: focus={summary.get('focus_label') or 'none'}"
        f" | status={summary.get('status') or 'not_available'}"
        f" | session={summary.get('current_session') or 'unknown'}"
        f" | allowed={allowed_sessions or 'none'}"
        + (
            f" | next={summary.get('next_trigger')}"
            if summary.get("next_trigger")
            else ""
        )
        + (
            f" | constraint={summary.get('wait_constraint')}"
            if summary.get("wait_constraint")
            else ""
        )
        + (
            f" | candidate={summary.get('candidate_symbol')}/{summary.get('candidate_family')}/{summary.get('candidate_status')}"
            if summary.get("candidate_symbol")
            else ""
        )
        + (
            f" | watcher={summary.get('watch_tick_status')}"
            if summary.get("watch_tick_status")
            else ""
        )
    )


def _post_patch_sample_summary_line(item: dict[str, Any] | None) -> str:
    summary = dict(item or {})
    if not summary:
        return "post_patch_sample: unavailable"
    top_symbols = "/".join(str(entry.get("symbol") or "UNKNOWN") for entry in list(summary.get("top_symbols") or [])[:3])
    return (
        f"post_patch_sample: {int(summary.get('closed_trade_count', 0) or 0)}/"
        f"{int(summary.get('target_closed_trades', 0) or 0)}"
        f" | remaining={int(summary.get('remaining_to_target', 0) or 0)}"
        f" | stop_loss={float(summary.get('stop_loss_share', 0.0) or 0.0):.0%}"
        f" | confirm_loss={float(summary.get('confirm_named_loss_share', 0.0) or 0.0):.0%}"
        + (f" | top={top_symbols}" if top_symbols else "")
    )


def _enrich_risk_gate_unlock_summary(
    unlock_summary: dict[str, Any] | None,
    *,
    checklist: dict[str, Any] | None,
    selected_trial_run_id: Any,
    trial_runs_written: Any,
    candidate_gate_ready: bool,
    edge_sample_gate_ready: bool,
) -> dict[str, Any]:
    summary = dict(unlock_summary or {})
    if not bool(summary.get("active", False)):
        return summary

    checklist_payload = dict(checklist or {})
    blocking_failures = int(checklist_payload.get("blocking_failures", 0) or 0)
    warnings = int(checklist_payload.get("warnings", 0) or 0)
    manual_actions = int(checklist_payload.get("manual_actions", 0) or 0)
    if blocking_failures == 1:
        if manual_actions > 0:
            expected_checklist_status = "FAIL"
        elif warnings > 0:
            expected_checklist_status = "WARN"
        else:
            expected_checklist_status = "PASS"
        summary["expected_checklist_status_after_unlock"] = expected_checklist_status

        if bool(selected_trial_run_id) or int(trial_runs_written or 0) > 0:
            summary["expected_stage_after_unlock"] = "2_LINEAGE_READY"
        elif candidate_gate_ready or edge_sample_gate_ready:
            summary["expected_stage_after_unlock"] = "1_SAMPLE_COLLECTION"

    summary["summary"] = (
        f"operating lock is expected to auto-clear at {summary.get('unlock_at')}; "
        f"expected_stage_after_unlock={summary.get('expected_stage_after_unlock', 'unknown')}"
    )
    return summary


def _stage_from_payload(
    validation_report: dict[str, Any],
    checklist: dict[str, Any],
    dashboard: dict[str, Any],
) -> str:
    deployment = validation_report.get("deployment_approval_summary") or {}
    playbook_go_no_go = str(deployment.get("playbook_go_no_go") or "").upper()
    resolved_selected_trial = _resolved_selected_trial(validation_report)
    selected_trial_run_id = resolved_selected_trial.get("selected_trial_run_id")
    sample_counts = (
        (validation_report.get("strategy_v2_pbo_dsr_trial_writer_summary") or {}).get("sample_counts") or {}
    )
    eligible_closed_trades = int(sample_counts.get("eligible_closed_trades") or 0)
    trial_runs_written = int(sample_counts.get("trial_runs_written") or 0)
    close_only_active = _active_close_only(dashboard)

    if (
        dashboard.get("new_entries_allowed") is False
        or close_only_active
        or playbook_go_no_go == "NO_GO"
        or str(checklist.get("overall_status") or "").upper() == "FAIL"
    ):
        return "0_BLOCKED"
    if selected_trial_run_id is not None or trial_runs_written > 0:
        return "2_LINEAGE_READY"
    if trial_runs_written == 0 and eligible_closed_trades > 0:
        return "1_SAMPLE_COLLECTION"
    if playbook_go_no_go in {"MANUAL_REVIEW", "GO"}:
        return "3_APPROVAL_REVIEW"
    return "CHECK_MANUALLY"


def _stage_message_fields(
    stage: str,
    validation_report: dict[str, Any],
    checklist: dict[str, Any],
    dashboard: dict[str, Any],
) -> dict[str, str]:
    deployment = validation_report.get("deployment_approval_summary") or {}
    playbook_go_no_go = str(deployment.get("playbook_go_no_go") or "").upper()
    close_only_active = _active_close_only(dashboard)
    execution_status = str(
        ((validation_report.get("execution_degradation_advisory_summary") or {}).get("status") or "")
    ).lower()
    trial_writer_summary = validation_report.get("strategy_v2_pbo_dsr_trial_writer_summary") or {}
    resolved_selected_trial = _resolved_selected_trial(validation_report)
    dashboard_strip = dict(dashboard.get("approval_strip_summary") or {})
    sample_counts = trial_writer_summary.get("sample_counts") or {}
    eligible_closed_trades = int(sample_counts.get("eligible_closed_trades") or 0)
    trial_runs_written = int(sample_counts.get("trial_runs_written") or 0)
    selected_trial_run_id = resolved_selected_trial.get("selected_trial_run_id")
    checklist_status = str(checklist.get("overall_status") or "").upper()

    blockers: list[str] = []
    if dashboard.get("new_entries_allowed") is False:
        blockers.append("runtime_no_go")
    if close_only_active:
        blockers.append("close_only_active")
    if checklist_status == "FAIL":
        blockers.append("checklist_fail")
    if playbook_go_no_go == "NO_GO":
        blockers.append("NO_GO")
    if execution_status == "manual_review":
        blockers.append("manual_review")

    if selected_trial_run_id:
        sample_progress_hint = (
            "selected lineage winner is resolved; remaining blockers are runtime/checklist approval gates"
        )
    elif trial_runs_written > 0:
        sample_progress_hint = (
            f"trial runs are present ({trial_runs_written}) but selected lineage winner is still unresolved"
        )
    elif eligible_closed_trades > 0:
        sample_progress_hint = (
            f"eligible_closed_trades={eligible_closed_trades}, trial_runs_written={trial_runs_written}"
        )
    else:
        sample_progress_hint = "lineage sample collection has not produced eligible closed trades yet"

    if stage == "0_BLOCKED":
        return {
            "stage_reason": " + ".join(blockers) if blockers else "operator entry expansion is blocked",
            "next_step_hint": (
                str(dashboard_strip.get("act_value") or "")
                or "resolve approval blocker and execution review before reopening entries"
            ),
            "sample_progress_hint": sample_progress_hint,
        }
    if stage == "1_SAMPLE_COLLECTION":
        return {
            "stage_reason": "eligible closed trades exist but no trial runs have been written",
            "next_step_hint": "continue paper lineage collection during active sessions",
            "sample_progress_hint": "waiting for trial_runs_written > 0 to start lineage selection",
        }
    if stage == "2_LINEAGE_READY":
        return {
            "stage_reason": (
                "selected trial is available"
                if selected_trial_run_id is not None
                else "trial runs have started and lineage selection can progress"
            ),
            "next_step_hint": "review validation and checklist surfaces for approval progression",
            "sample_progress_hint": sample_progress_hint,
        }
    if stage == "3_APPROVAL_REVIEW":
        return {
            "stage_reason": "lineage is ready enough for approval review but rollout still needs operator confirmation",
            "next_step_hint": "review validation and checklist before changing any runtime state",
            "sample_progress_hint": sample_progress_hint,
        }
    return {
        "stage_reason": "stage needs manual interpretation from validation, checklist, and dashboard surfaces",
        "next_step_hint": "review server-side operator surfaces directly",
        "sample_progress_hint": sample_progress_hint,
    }


def _apply_runtime_stage_override(payload: dict[str, Any]) -> dict[str, Any]:
    current = dict(payload or {})
    signoff = dict(current.get("runtime_signoff_summary") or {})
    decision = dict(signoff.get("runtime_decision") or current.get("runtime_decision") or {})
    gate = dict(current.get("runtime_reopen_gate_summary") or signoff.get("runtime_reopen_gate_summary") or {})
    action = str(decision.get("effective_action") or "")
    if action not in {
        "conditional_micro_live_signoff",
        "conditional_full_live_signoff",
        "manual_signoff_required",
        "proceed_to_operator_signoff",
    }:
        return current

    current["stage"] = "3_APPROVAL_REVIEW"
    if action == "conditional_micro_live_signoff":
        current["stage_reason"] = "post-patch cohort cleared the conditional MICRO_LIVE thresholds"
        current["next_step_hint"] = "review manual sign-off and, if accepted, reopen MICRO_LIVE only"
    elif action == "conditional_full_live_signoff":
        current["stage_reason"] = "post-patch cohort cleared the conditional FULL LIVE thresholds"
        current["next_step_hint"] = "review manual sign-off and decide whether to reopen MICRO_LIVE or LIVE"
    elif action == "proceed_to_operator_signoff":
        current["stage_reason"] = "runtime is reopen-ready and final operator sign-off can proceed"
        current["next_step_hint"] = "record final operator sign-off before reopening runtime"
    else:
        current["stage_reason"] = "runtime is reopen-ready but required operator review items remain"
        current["next_step_hint"] = "review the remaining required warning before reopening runtime"

    full_gate = dict(gate.get("full_live") or {})
    micro_gate = dict(gate.get("micro_live") or {})
    if micro_gate or full_gate:
        current["sample_progress_hint"] = (
            f"MICRO_LIVE={micro_gate.get('status') or 'n/a'} "
            f"({int(micro_gate.get('closed_trade_count') or 0)}/{int(micro_gate.get('min_closed_trades') or 0)}), "
            f"FULL_LIVE={full_gate.get('status') or 'n/a'} "
            f"({int(full_gate.get('closed_trade_count') or 0)}/{int(full_gate.get('min_closed_trades') or 0)})"
        )
    return current


def _build_stage_payload(
    validation_report: dict[str, Any],
    checklist: dict[str, Any],
    dashboard: dict[str, Any],
    *,
    symbol: str = "BTCUSDC",
    universe: str = "usdc_perp_top30",
    days: int = 30,
    lineage_sample_scope: str = "symbol_edge_proof",
    lineage_families: str = "sweep_reversal",
    lineage_proof_goal_closed_trades: int = 100,
    lineage_sample_days: int = 180,
) -> dict[str, Any]:
    deployment = validation_report.get("deployment_approval_summary") or {}
    trial_writer_summary = validation_report.get("strategy_v2_pbo_dsr_trial_writer_summary") or {}
    sample_counts = trial_writer_summary.get("sample_counts") or {}
    resolved_selected_trial = _resolved_selected_trial(validation_report)
    execution_advisory = validation_report.get("execution_degradation_advisory_summary") or {}
    operator_action_priority = validation_report.get("operator_action_priority_summary") or {}
    alpha_research_pipeline = validation_report.get("alpha_research_pipeline_summary") or {}
    validation_strip = _surface_strip_summary(validation_report, surface_type="validation")
    checklist_strip = _surface_strip_summary(checklist, surface_type="checklist")
    dashboard_strip = _surface_strip_summary(dashboard, surface_type="dashboard")
    edge_experiment_review = _edge_experiment_summary(validation_report, dashboard)
    edge_evolution_rule = _edge_evolution_summary(validation_report, dashboard)
    review_followup_ledger = _review_followup_summary(validation_report, dashboard)
    risk_gate_summary = _risk_gate_summary(checklist)
    risk_gate_unlock_summary = _risk_gate_unlock_summary(risk_gate_summary)
    lineage_sample_summary = _lineage_sample_summary(
        scope=lineage_sample_scope,
        symbol=symbol,
        edge_experiment_review=edge_experiment_review,
        families=_family_set(lineage_families),
        proof_goal_closed_trades=lineage_proof_goal_closed_trades,
        sample_days=lineage_sample_days,
    )
    representative_candidates = _representative_candidates(dashboard)
    open_lineage_sample_summary = _open_lineage_samples(_family_set(lineage_families))
    active_lineage_samples = list(open_lineage_sample_summary.get("samples") or [])
    active_lineage_sample_focus = dict(active_lineage_samples[0]) if active_lineage_samples else None
    active_lineage_sample_health = _active_lineage_sample_health(active_lineage_sample_focus)
    entry_timing_review_target = _experiment_review_target(
        operator_action_priority,
        target_key="entry_timing_target",
        preferred_key="entry_timing_preferred_variant",
        action="run_entry_timing_split_review",
        universe=universe,
        days=days,
    )
    execution_style_review_target = _experiment_review_target(
        operator_action_priority,
        target_key="execution_style_target",
        preferred_key="execution_style_preferred_variant",
        action="run_execution_style_split_review",
        universe=universe,
        days=days,
    )

    stage = _stage_from_payload(validation_report, checklist, dashboard)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "close_only_active": _active_close_only(dashboard),
        "playbook_go_no_go": deployment.get("playbook_go_no_go"),
        "deployment_go_no_go": deployment.get("deployment_go_no_go"),
        "checklist_status": checklist.get("overall_status"),
        "eligible_closed_trades": sample_counts.get("eligible_closed_trades"),
        "trial_runs_written": sample_counts.get("trial_runs_written"),
        "selected_trial_run_id": resolved_selected_trial.get("selected_trial_run_id"),
        "selected_trial_resolution_source": resolved_selected_trial.get("resolution_source"),
        "raw_trial_writer_selected_trial_run_id": resolved_selected_trial.get("raw_trial_writer_selected_trial_run_id"),
        "threshold_lineage_winner_run_id": resolved_selected_trial.get("threshold_lineage_winner_run_id"),
        "threshold_lineage_winner_source": resolved_selected_trial.get("threshold_lineage_winner_source"),
        "threshold_lineage_winner_type": resolved_selected_trial.get("threshold_lineage_winner_type"),
        "threshold_lineage_audit_status": resolved_selected_trial.get("threshold_lineage_audit_status"),
        "execution_degradation": execution_advisory.get("status"),
        "top_operator_action": operator_action_priority.get("top_action"),
        "top_operator_action_followup_command": operator_action_priority.get("top_action_followup_command") or "",
        "dashboard_approval_strip": dashboard_strip,
        "validation_approval_strip": validation_strip,
        "checklist_approval_strip": checklist_strip,
        "edge_experiment_review": edge_experiment_review,
        "edge_evolution_rule": edge_evolution_rule,
        "review_followup_ledger": review_followup_ledger,
        "risk_gate_summary": risk_gate_summary,
        "risk_gate_unlock_summary": risk_gate_unlock_summary,
        "lineage_sample_summary": lineage_sample_summary,
        "lineage_closed_fill_health": _lineage_closed_fill_health(lineage_sample_summary),
        "entry_timing_review_target": entry_timing_review_target,
        "execution_style_review_target": execution_style_review_target,
        "representative_candidates": representative_candidates,
        "open_lineage_sample_summary": open_lineage_sample_summary,
        "active_lineage_sample_focus": active_lineage_sample_focus,
        "active_lineage_sample_health": active_lineage_sample_health,
        "alpha_research_next_step": (
            alpha_research_pipeline.get("recommended_action")
            or alpha_research_pipeline.get("softening_top_bucket")
            or alpha_research_pipeline.get("promotion_top_bucket")
        ),
    }
    payload["readiness_gates"] = _readiness_gates(
        selected_trial_run_id=resolved_selected_trial.get("selected_trial_run_id"),
        trial_runs_written=sample_counts.get("trial_runs_written"),
        representative_candidates=representative_candidates,
        entry_timing_review_target=entry_timing_review_target,
        execution_style_review_target=execution_style_review_target,
        active_lineage_sample_focus=active_lineage_sample_focus,
        edge_experiment_review=edge_experiment_review,
        lineage_sample_summary=lineage_sample_summary,
    )
    payload["lineage_gate_ready"] = bool(payload["readiness_gates"]["lineage_gate_ready"])
    payload["candidate_gate_ready"] = bool(payload["readiness_gates"]["candidate_gate_ready"])
    payload["edge_sample_gate_ready"] = bool(payload["readiness_gates"]["edge_sample_gate_ready"])
    payload["all_readiness_gates_ready"] = bool(payload["readiness_gates"]["all_ready"])
    payload["risk_gate_unlock_summary"] = _enrich_risk_gate_unlock_summary(
        payload.get("risk_gate_unlock_summary"),
        checklist=checklist,
        selected_trial_run_id=payload.get("selected_trial_run_id"),
        trial_runs_written=payload.get("trial_runs_written"),
        candidate_gate_ready=payload["candidate_gate_ready"],
        edge_sample_gate_ready=payload["edge_sample_gate_ready"],
    )
    payload["post_unlock_review_summary"] = _post_unlock_review_summary(
        risk_gate_summary=payload.get("risk_gate_summary"),
        risk_gate_unlock_summary=payload.get("risk_gate_unlock_summary"),
        validation_report=validation_report,
        checklist=checklist,
        stage=stage,
        lineage_gate_ready=payload["lineage_gate_ready"],
        edge_sample_gate_ready=payload["edge_sample_gate_ready"],
        symbol=symbol,
        universe=universe,
        days=days,
    )
    payload["post_unlock_bundle_result"] = _default_post_unlock_bundle_result(payload.get("post_unlock_review_summary"))
    payload["runtime_reopen_status"] = _runtime_reopen_status(
        risk_gate_summary=payload.get("risk_gate_summary"),
        review_summary=payload.get("post_unlock_review_summary"),
        bundle_result=payload.get("post_unlock_bundle_result"),
    )
    payload["runtime_signoff_summary"] = _runtime_signoff_summary(
        validation_report=validation_report,
        checklist=checklist,
        runtime_reopen_status=payload.get("runtime_reopen_status"),
    )
    payload["runtime_reopen_gate_summary"] = dict(
        (payload.get("runtime_signoff_summary") or {}).get("runtime_reopen_gate_summary") or {}
    )
    payload.update(_stage_message_fields(stage, validation_report, checklist, dashboard))
    payload = _apply_runtime_stage_override(payload)
    return payload


def _reuse_recent_runtime_monitor_fields(
    payload: dict[str, Any],
    previous_stage: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = dict(payload or {})
    previous = dict(previous_stage or {})
    if not previous:
        return current

    previous_generated_at = _parse_ts(previous.get("generated_at"))
    reference_now = now or datetime.now(timezone.utc)
    if previous_generated_at is None:
        return current
    if (reference_now - previous_generated_at).total_seconds() > float(_RUNTIME_MONITOR_REUSE_SECONDS):
        return current

    same_selected_trial = str(previous.get("selected_trial_run_id") or "") == str(current.get("selected_trial_run_id") or "")
    same_risk_state = str((previous.get("risk_gate_summary") or {}).get("risk_state") or "") == str(
        (current.get("risk_gate_summary") or {}).get("risk_state") or ""
    )
    same_checklist_status = str(previous.get("checklist_status") or "") == str(current.get("checklist_status") or "")
    same_playbook = str(previous.get("playbook_go_no_go") or "") == str(current.get("playbook_go_no_go") or "")
    same_lineage_count = int(((previous.get("lineage_sample_summary") or {}).get("closed_trade_count") or 0)) == int(
        ((current.get("lineage_sample_summary") or {}).get("closed_trade_count") or 0)
    )

    if not all((same_selected_trial, same_risk_state, same_checklist_status, same_playbook, same_lineage_count)):
        return current

    for key in (
        "post_unlock_bundle_result",
        "runtime_reopen_status",
        "runtime_signoff_summary",
        "runtime_reopen_gate_summary",
        "runtime_preflight_summary",
        "runtime_operator_signoff_summary",
        "runtime_mitigation_summary",
        "runtime_mitigation_packet_result",
        "runtime_mitigation_wait_summary",
    ):
        value = previous.get(key)
        if value is not None:
            current[key] = value
    current["runtime_monitor_snapshot_reused"] = True
    current["runtime_monitor_snapshot_reused_from"] = previous_generated_at.isoformat()
    return current


def _print_human(payload: dict[str, Any]) -> None:
    print(f"stage: {payload['stage']}")
    print(f"stage_reason: {payload['stage_reason']}")
    print(f"next_step_hint: {payload['next_step_hint']}")
    print(f"sample_progress_hint: {payload['sample_progress_hint']}")
    print(f"close_only_active: {payload['close_only_active']}")
    print(_surface_summary_line("dashboard_surface", payload.get("dashboard_approval_strip") or {}))
    print(_surface_summary_line("validation_surface", payload.get("validation_approval_strip") or {}))
    print(_surface_summary_line("checklist_surface", payload.get("checklist_approval_strip") or {}))
    print(_edge_experiment_summary_line(payload.get("edge_experiment_review")))
    print(_edge_evolution_summary_line(payload.get("edge_evolution_rule")))
    print(_review_followup_summary_line(payload.get("review_followup_ledger")))
    print(_risk_gate_summary_line(payload.get("risk_gate_summary")))
    print(_risk_gate_unlock_summary_line(payload.get("risk_gate_unlock_summary")))
    print(_post_unlock_review_summary_line(payload.get("post_unlock_review_summary")))
    print(_post_unlock_review_commands_line(payload.get("post_unlock_review_summary")))
    print(_post_unlock_bundle_result_line(payload.get("post_unlock_bundle_result")))
    print(_runtime_reopen_status_line(payload.get("runtime_reopen_status")))
    print(_runtime_signoff_summary_line(payload.get("runtime_signoff_summary")))
    print(_runtime_reopen_gate_summary_line(payload.get("runtime_reopen_gate_summary")))
    print(_runtime_preflight_summary_line(payload.get("runtime_preflight_summary")))
    print(_runtime_operator_signoff_summary_line(payload.get("runtime_operator_signoff_summary")))
    print(_post_patch_sample_summary_line(payload.get("post_patch_sample_summary")))
    print(_runtime_mitigation_summary_line(payload.get("runtime_mitigation_summary")))
    print(_runtime_mitigation_wait_summary_line(payload.get("runtime_mitigation_wait_summary")))
    print(_lineage_sample_summary_line(payload.get("lineage_sample_summary")))
    print(_lineage_closed_fill_health_line(payload.get("lineage_closed_fill_health")))
    print(_experiment_review_target_line("entry_timing_review_target", payload.get("entry_timing_review_target")))
    print(_experiment_review_target_line("execution_style_review_target", payload.get("execution_style_review_target")))
    representative_candidates = payload.get("representative_candidates") or {}
    print(_representative_candidate_summary_line("accepted_candidate_focus", representative_candidates.get("accepted")))
    print(_representative_candidate_summary_line("blocked_candidate_focus", representative_candidates.get("blocked")))
    print(_open_lineage_sample_summary_line(payload.get("open_lineage_sample_summary")))
    print(_active_lineage_sample_focus_line(payload.get("active_lineage_sample_focus")))
    print(_active_lineage_sample_health_line(payload.get("active_lineage_sample_health")))
    print(f"readiness_gates: {(payload.get('readiness_gates') or {}).get('summary', 'unavailable')}")
    print(f"checklist_status: {payload['checklist_status']}")
    print(f"eligible_closed_trades: {payload['eligible_closed_trades']}")
    print(f"trial_runs_written: {payload['trial_runs_written']}")
    print(f"selected_trial_run_id: {payload['selected_trial_run_id']}")
    print(f"selected_trial_resolution_source: {payload.get('selected_trial_resolution_source') or 'unresolved'}")
    if payload.get("threshold_lineage_winner_run_id"):
        print(f"threshold_lineage_winner_run_id: {payload.get('threshold_lineage_winner_run_id')}")
    print(f"execution_degradation: {payload['execution_degradation']}")
    print(f"top_operator_action: {payload['top_operator_action']}")
    print(f"top_operator_action_followup_command: {payload.get('top_operator_action_followup_command') or 'none'}")
    print(f"alpha_research_next_step: {payload['alpha_research_next_step']}")


def main() -> int:
    args = parse_args()
    stage_file_path = Path(args.stage_file).resolve()
    previous_stage = _read_stage_file(stage_file_path)
    validation = _request_json(
        args.base_url,
        "POST",
        "/validation/report",
        query={"symbol": args.symbol, "refresh": False},
    )
    checklist = _request_json(
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
    dashboard = _request_json(
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
    payload = _build_stage_payload(
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
    payload = _reuse_recent_runtime_monitor_fields(payload, previous_stage)
    payload["runtime_operator_signoff_summary"] = run_runtime_signoff_review._build_runtime_operator_signoff_summary(
        runtime_decision=dict(payload.get("runtime_decision") or {}),
        runtime_preflight_summary=dict(payload.get("runtime_preflight_summary") or {}),
        runtime_signoff_summary=dict(payload.get("runtime_signoff_summary") or {}),
    )
    payload = _apply_runtime_stage_override(payload)
    if not args.no_write_stage:
        _write_stage_file(stage_file_path, payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        _print_human(payload)
        print("")
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
