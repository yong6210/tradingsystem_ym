#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import OrderIntent
from app.db.session import SessionLocal, init_db
from app.services.active_contract_replay_baseline import usdt_proxy_rows_for_active_contract
from app.services.family_rollout import RolloutPolicyBootstrap
from app.services.historical_walk_forward_split_review import HistoricalWalkForwardSplitReviewService
from app.services.live_route_contract import row_session_name
from app.services.live_order_lifecycle import LiveOrderLifecycleReporter
from app.services.market_data import configured_usdt_universe_name
from app.services.runtime_worker_heartbeat import read_worker_heartbeat
from scripts.operation_report_io import atomic_write_text, parse_report_generated_at, write_latest_aliases


_ACTIVE_CONTRACT_REPLAY_BASELINE_FILE = "strategy_proof_contract_live_subset.json"
_MIN_EXPECTED_WINDOW_CANDIDATES_FOR_SYMBOL_ALERT = 2.0
_PORTFOLIO_FLOW_SHORTFALL_STAGES = {"signal_or_plan_generation_gap", "live_flow_thin"}
_PORTFOLIO_ORDER_GATE_STAGES = {"approval_gate_blocked", "submitted_waiting_for_fill"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare live MICRO_LIVE flow against replay/dashboard flow baseline.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--all-live-symbols", action="store_true")
    parser.add_argument("--universe", default=configured_usdt_universe_name())
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--since-ws-start", action="store_true", help="Compatibility flag; runtime scope is the default when ws started_at is available.")
    parser.add_argument("--lookback-only", action="store_true", help="Ignore ws started_at and use the full --days lookback as the active parity window.")
    parser.add_argument("--heartbeat-dir", default="")
    parser.add_argument("--dashboard-json", default="")
    parser.add_argument("--min-flow-ratio", type=float, default=0.25)
    parser.add_argument("--report-dir", default="reports/operations/live_replay_parity")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-fail-exit", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="Write report artifacts without printing stdout.")
    return parser.parse_args()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _resolve_root_path(raw_path: str) -> Path:
    path = Path(str(raw_path or "")).expanduser()
    return path if path.is_absolute() else ROOT_DIR / path


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _expected_window_candidates(expected_per_week: float, cadence: dict[str, Any]) -> float | None:
    days = _safe_float(cadence.get("cadence_window_days"), default=0.0)
    if expected_per_week <= 0.0 or days <= 0.0:
        return None
    return expected_per_week * days / 7.0


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


def _ws_runtime_started_at(heartbeat_dir: str = "") -> datetime | None:
    raw_dir = str(heartbeat_dir or "").strip()
    if raw_dir:
        try:
            payload = json.loads((Path(raw_dir).expanduser() / "ws.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    else:
        payload = read_worker_heartbeat("ws")
    details = dict(payload.get("details") or {}) if isinstance(payload, dict) else {}
    return _parse_utc_ts(details.get("started_at"))


def _request_dashboard(*, base_url: str, symbol: str, universe: str, days: int) -> dict[str, Any]:
    query = urlencode({"symbol": symbol, "universe": universe, "days": max(1, int(days))})
    url = f"{base_url.rstrip('/')}/execution/operator-dashboard?{query}"
    request = Request(url=url, headers={"Accept": "application/json"}, method="GET")  # noqa: S310
    with urlopen(request, timeout=20) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _csv_set(raw: Any, *, lower: bool = False) -> set[str]:
    items: set[str] = set()
    for item in str(raw or "").split(","):
        value = item.strip()
        if not value:
            continue
        items.add(value.lower() if lower else value.upper())
    return items


def _direction_contract(raw: Any) -> dict[str, list[str]]:
    contract: dict[str, list[str]] = {}
    for item in str(raw or "").split(","):
        if ":" not in item:
            continue
        symbol, directions = item.split(":", 1)
        values = [value.strip().upper() for value in directions.replace("/", "|").split("|") if value.strip()]
        if symbol.strip() and values:
            contract[symbol.strip().upper()] = values
    return contract


def _rollout_family_sessions(families: list[str] | set[str]) -> dict[str, list[str]]:
    rollout = RolloutPolicyBootstrap()
    out: dict[str, list[str]] = {}
    normalized_families = {str(item or "").strip().lower() for item in families if str(item or "").strip()}
    for family in sorted(normalized_families):
        policy = rollout.get(family)
        sessions = sorted({str(item or "").strip().lower() for item in list(policy.allowed_sessions or []) if str(item).strip()})
        if sessions:
            out[family] = sessions
    return out


def _active_contract_filters_from_settings(symbol: str) -> dict[str, Any]:
    settings = get_settings()
    normalized_symbol = str(symbol or "").strip().upper()
    families = sorted(_csv_set(getattr(settings, "auto_trading_micro_live_allowed_families", ""), lower=True))
    configured_sessions = sorted(_csv_set(getattr(settings, "auto_trading_micro_live_allowed_sessions", ""), lower=True))
    family_sessions = _rollout_family_sessions(families)
    effective_sessions = configured_sessions or sorted({session for sessions in family_sessions.values() for session in sessions})
    return {
        "symbol": normalized_symbol,
        "execution_mode": "MICRO_LIVE",
        "strategy_families": families,
        "entry_models": sorted(_csv_set(getattr(settings, "auto_trading_micro_live_allowed_entry_models", ""))),
        "directions": list(_direction_contract(getattr(settings, "auto_trading_micro_live_direction_contract", "")).get(normalized_symbol) or []),
        "sessions": effective_sessions,
        "family_sessions": family_sessions,
        "session_filter_source": (
            "micro_live_settings"
            if configured_sessions
            else "family_rollout_policy"
            if effective_sessions
            else "none"
        ),
    }


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(payload) if isinstance(payload, dict) else {}
    return {}


def _intent_executable_plan(row: OrderIntent) -> dict[str, Any]:
    payload = _json_dict(getattr(row, "payload", None))
    executable = payload.get("executable_plan")
    return dict(executable) if isinstance(executable, dict) else {}


def _intent_session_name(row: OrderIntent) -> str:
    session_payload = _json_dict(getattr(row, "session_guidance", None))
    resolved = row_session_name({"session_guidance": session_payload})
    if resolved:
        return resolved
    current_session = session_payload.get("current_session")
    if isinstance(current_session, dict) and str(current_session.get("name") or "").strip():
        return str(current_session.get("name") or "").strip().lower()

    approval = _json_dict(getattr(row, "approval_snapshot", None))
    for key in ("session_guidance", "operating_lock", "safety_state"):
        payload = approval.get(key)
        if not isinstance(payload, dict):
            continue
        resolved = row_session_name({"operating_lock": payload} if key == "operating_lock" else {"session_guidance": payload})
        if resolved:
            return resolved
        current = payload.get("current_session")
        if isinstance(current, dict) and str(current.get("name") or "").strip():
            return str(current.get("name") or "").strip().lower()
        if str(payload.get("session_name") or "").strip():
            return str(payload.get("session_name") or "").strip().lower()
    return ""


def _intent_matches_active_contract(row: OrderIntent, filters: dict[str, Any]) -> bool:
    family = str(getattr(row, "strategy_family", "") or "").strip().lower()
    families = {str(item or "").strip().lower() for item in list(filters.get("strategy_families") or []) if str(item).strip()}
    if families and family not in families:
        return False

    executable = _intent_executable_plan(row)
    entry_model = str(executable.get("entry_model") or "").strip().upper()
    entry_models = {str(item or "").strip().upper() for item in list(filters.get("entry_models") or []) if str(item).strip()}
    if entry_models and entry_model and entry_model not in entry_models:
        return False

    direction = str(executable.get("direction") or "").strip().upper()
    directions = {str(item or "").strip().upper() for item in list(filters.get("directions") or []) if str(item).strip()}
    if directions and direction and direction not in directions:
        return False

    session_name = _intent_session_name(row)
    sessions = {str(item or "").strip().lower() for item in list(filters.get("sessions") or []) if str(item).strip()}
    if sessions and session_name and session_name not in sessions:
        return False

    family_sessions = {
        str(key or "").strip().lower(): {str(item or "").strip().lower() for item in list(value or []) if str(item).strip()}
        for key, value in dict(filters.get("family_sessions") or {}).items()
    }
    allowed_family_sessions = family_sessions.get(family) or set()
    if allowed_family_sessions and session_name and session_name not in allowed_family_sessions:
        return False
    return True


def _flow_cadence_from_db(
    *,
    symbol: str,
    filters: dict[str, Any],
    days: int,
    start_at: datetime | None = None,
) -> dict[str, Any]:
    normalized_days = max(1, int(days))
    now = datetime.now(UTC)
    lookback_cutoff = now - timedelta(days=normalized_days)
    parsed_start = _as_utc(start_at)
    cutoff = max(lookback_cutoff, parsed_start) if parsed_start is not None else lookback_cutoff
    cutoff = min(cutoff, now)
    window_days = max((now - cutoff).total_seconds() / 86400.0, 1.0 / 1440.0)
    families = {str(item or "").lower() for item in list(filters.get("strategy_families") or []) if str(item or "").strip()}
    stmt = (
        select(OrderIntent)
        .where(
            OrderIntent.created_at >= cutoff,
            OrderIntent.symbol == str(symbol or "").upper(),
            OrderIntent.execution_mode == "MICRO_LIVE",
        )
        .order_by(OrderIntent.created_at.desc())
    )
    if families:
        stmt = stmt.where(OrderIntent.strategy_family.in_(sorted(families)))
    init_db()
    with SessionLocal() as db:
        rows = list(db.scalars(stmt))
    rows = [row for row in rows if _intent_matches_active_contract(row, filters)]
    last_created_at = max((_as_utc(row.created_at) for row in rows), default=None)
    return {
        "cadence_window_days": round(window_days, 4) if parsed_start is not None else normalized_days,
        "requested_lookback_days": normalized_days,
        "cadence_window_basis": (
            "runtime_since_ws_start_active_contract_intents_local_db"
            if parsed_start is not None
            else "recent_active_contract_intents_local_db"
        ),
        "window_start": cutoff.isoformat(),
        "runtime_started_at": parsed_start.isoformat() if parsed_start is not None else None,
        "hours_since_last_active_contract_intent": (
            round((now - last_created_at).total_seconds() / 3600.0, 4)
            if last_created_at is not None
            else None
        ),
        "runtime_candidates_current_snapshot": 0,
        "current_window_active_contract_intent_count": len(rows),
        "current_window_active_contract_intents_per_week": round((len(rows) / window_days) * 7.0, 4),
        "flow_state": "active_now" if rows else "no_recent_active_contract_flow",
    }


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _local_replay_flow_baseline(*, filters: dict[str, Any], cadence_window: dict[str, Any]) -> dict[str, Any] | None:
    settings = get_settings()
    usdt_proxy = usdt_proxy_rows_for_active_contract(settings, filters)
    if usdt_proxy is not None:
        replay_window_days = max(_safe_float(usdt_proxy.get("days"), 0.0), 1.0)
        replay_window_weeks = replay_window_days / 7.0
        replay_rows = list(usdt_proxy.get("rows") or [])
        expected_per_week = round(len(replay_rows) / replay_window_weeks, 4) if replay_window_weeks > 0 else 0.0
        observed = _safe_float(cadence_window.get("current_window_active_contract_intents_per_week"))
        return {
            "available": True,
            "source": str(usdt_proxy.get("source") or "micro_main_usdt_proxy_backtest"),
            "source_path": str(usdt_proxy.get("source_path") or ""),
            "generated_at": str(usdt_proxy.get("generated_at") or ""),
            "contract_filters": {
                "symbol": str(filters.get("symbol") or "").strip().upper(),
                "strategy_families": sorted(
                    {str(item or "").strip().lower() for item in list(filters.get("strategy_families") or []) if str(item or "").strip()}
                ),
                "entry_models": sorted(
                    {str(item or "").strip().upper() for item in list(filters.get("entry_models") or []) if str(item or "").strip()}
                ),
                "directions": sorted(
                    {str(item or "").strip().upper() for item in list(filters.get("directions") or []) if str(item or "").strip()}
                ),
                "sessions": sorted(
                    {str(item or "").strip().lower() for item in list(filters.get("sessions") or []) if str(item or "").strip()}
                ),
                "family_sessions": {
                    str(key or "").strip().lower(): sorted(
                        {str(item or "").strip().lower() for item in list(value or []) if str(item).strip()}
                    )
                    for key, value in dict(filters.get("family_sessions") or {}).items()
                },
                "session_filter_source": str(filters.get("session_filter_source") or ""),
            },
            "replay_window_days": round(replay_window_days, 4),
            "replay_trade_count": len(replay_rows),
            "expected_active_contract_candidates_per_week_from_replay": expected_per_week,
            "expected_closed_per_week_from_replay": expected_per_week,
            "observed_current_window_active_contract_intents_per_week_live": observed,
            "live_vs_replay_flow_ratio": round(observed / expected_per_week, 4) if expected_per_week > 0 else None,
            "comparison_only": True,
            "matched_replay_rows": len(replay_rows),
        }

    cache_path = Path(getattr(settings, "validation_report_dir", "reports/validation")) / "historical_walk_forward_cache" / _ACTIVE_CONTRACT_REPLAY_BASELINE_FILE
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    simulation_start = _as_utc(payload.get("simulation_start_ts"))
    simulation_end = _as_utc(payload.get("simulation_end_ts"))
    if simulation_start is None or simulation_end is None:
        return None
    replay_window_days = max((simulation_end - simulation_start).total_seconds() / 86400.0, 1.0)
    replay_window_weeks = replay_window_days / 7.0

    filter_symbol = str(filters.get("symbol") or "").strip().upper()
    strategy_families = {str(item or "").strip().lower() for item in list(filters.get("strategy_families") or []) if str(item or "").strip()}
    entry_models = {str(item or "").strip().upper() for item in list(filters.get("entry_models") or []) if str(item or "").strip()}
    directions = {str(item or "").strip().upper() for item in list(filters.get("directions") or []) if str(item or "").strip()}
    sessions = {str(item or "").strip().lower() for item in list(filters.get("sessions") or []) if str(item or "").strip()}
    family_sessions = {
        str(key or "").strip().lower(): {str(item or "").strip().lower() for item in list(value or []) if str(item).strip()}
        for key, value in dict(filters.get("family_sessions") or {}).items()
    }
    split_review = HistoricalWalkForwardSplitReviewService(settings=settings)

    replay_rows: list[dict[str, Any]] = []
    for raw_row in list(payload.get("trade_rows") or []):
        if not isinstance(raw_row, dict):
            continue
        row = dict(raw_row)
        family = str(row.get("strategy_family") or "").strip().lower()
        generated_ts = _as_utc(row.get("generated_ts")) or _as_utc(row.get("closed_ts"))
        generated_session = split_review._session_bucket(generated_ts)
        row["generated_session"] = generated_session
        if filter_symbol and str(row.get("symbol") or "").strip().upper() != filter_symbol:
            continue
        if strategy_families and family not in strategy_families:
            continue
        if entry_models and str(row.get("entry_model") or "").strip().upper() not in entry_models:
            continue
        if directions and str(row.get("direction") or "").strip().upper() not in directions:
            continue
        if sessions and generated_session not in sessions:
            continue
        allowed_family_sessions = family_sessions.get(family) or set()
        if allowed_family_sessions and generated_session not in allowed_family_sessions:
            continue
        replay_rows.append(row)
    expected_per_week = round(len(replay_rows) / replay_window_weeks, 4) if replay_window_weeks > 0 else 0.0
    observed = _safe_float(cadence_window.get("current_window_active_contract_intents_per_week"))
    return {
        "available": True,
        "source_path": str(cache_path),
        "contract_filters": {
            "symbol": filter_symbol,
            "strategy_families": sorted(strategy_families),
            "entry_models": sorted(entry_models),
            "directions": sorted(directions),
            "sessions": sorted(sessions),
            "family_sessions": {key: sorted(value) for key, value in sorted(family_sessions.items())},
            "session_filter_source": str(filters.get("session_filter_source") or ""),
        },
        "replay_window_days": round(replay_window_days, 4),
        "expected_active_contract_candidates_per_week_from_replay": expected_per_week,
        "expected_closed_per_week_from_replay": expected_per_week,
        "observed_current_window_active_contract_intents_per_week_live": observed,
        "live_vs_replay_flow_ratio": round(observed / expected_per_week, 4) if expected_per_week > 0 else None,
        "comparison_only": True,
        "matched_replay_rows": len(replay_rows),
    }


def _build_dashboard_from_db(
    *,
    symbol: str,
    universe: str,
    days: int,
    start_at: datetime | None = None,
) -> dict[str, Any]:
    del universe
    filters = _active_contract_filters_from_settings(symbol)
    cadence = _flow_cadence_from_db(symbol=symbol, filters=filters, days=days, start_at=start_at)
    replay = _local_replay_flow_baseline(filters=filters, cadence_window=cadence)
    return {
        "active_contract": {
            "filters": filters,
            "flow_cadence": cadence,
            "replay_flow_baseline": replay,
        }
    }


def _load_dashboard(path: str) -> dict[str, Any]:
    if not str(path or "").strip():
        return {}
    try:
        payload = json.loads(_resolve_root_path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _flow_diagnosis(
    *,
    expected: float,
    ratio: float,
    min_flow_ratio: float,
    summary: dict[str, Any],
    live_intents: dict[str, Any],
    top_reasons: dict[str, Any],
) -> dict[str, Any]:
    intent_count = _safe_int(live_intents.get("total"))
    submit_ready = _safe_int(live_intents.get("submit_ready"))
    blocked = _safe_int(live_intents.get("blocked"))
    submissions = _safe_int(summary.get("submission_count"))
    requested_live = _safe_int(summary.get("requested_live_count"))
    rejected_or_error = _safe_int(summary.get("rejected_or_error_count"))
    entry_fills = _safe_int(summary.get("entry_fill_count"))
    top_reason = next(iter(top_reasons.keys()), "")
    decision_counts = {
        str(key or ""): _safe_int(value)
        for key, value in dict(live_intents.get("by_decision") or {}).items()
    }
    non_submit_decision_count = sum(
        count
        for decision, count in decision_counts.items()
        if decision.upper() not in {"SUBMIT_READY", "SUBMITTED", "SUBMIT"}
    )

    if expected <= 0.0:
        stage = "baseline_unavailable"
        primary_reason = "replay_flow_baseline_unavailable"
        action = "리플레이 baseline 파일/API/DB 산출물을 먼저 복구"
        summary_ko = "리플레이 기준 빈도를 읽지 못해 라이브 빈도 비교가 불가능합니다."
    elif intent_count <= 0 and ratio < max(0.0, float(min_flow_ratio)):
        stage = "signal_or_plan_generation_gap"
        primary_reason = "no_recent_live_intents_against_replay_baseline"
        action = "scanner/plan 생성, session_impulse_retest runtime routing, 심볼 allowlist를 확인"
        summary_ko = "리플레이상 후보가 나와야 하는데 최근 라이브 intent 자체가 없습니다."
    elif submit_ready > 0 and submissions <= 0 and requested_live <= 0:
        stage = "intent_to_submission_gap"
        primary_reason = "submit_ready_intents_without_submission"
        action = "worker 실행 상태, order intent submit loop, exchange client 라우팅을 확인"
        summary_ko = "제출 가능한 intent가 있는데 거래소 주문 제출이 없습니다."
    elif rejected_or_error > 0:
        stage = "exchange_submission_rejected_or_error"
        primary_reason = "live_submission_rejected_or_error"
        action = "Binance reject/error payload, minNotional/stepSize/leverage/margin 규칙을 확인"
        summary_ko = "라이브 주문 제출 이후 거래소 reject/error가 발생했습니다."
    elif (
        intent_count > 0
        and submit_ready <= 0
        and submissions <= 0
        and (
            blocked >= intent_count
            or bool(top_reasons)
            or non_submit_decision_count >= intent_count
        )
    ):
        stage = "approval_gate_blocked"
        primary_reason = str(top_reason or "all_recent_live_intents_not_submit_ready")
        action = "validation_block_detail, rollout/session gate, runtime deployment gate를 확인"
        summary_ko = "신호는 intent까지 왔지만 승인 게이트에서 전부 막혔습니다."
    elif submissions > 0 and entry_fills <= 0:
        stage = "submitted_waiting_for_fill"
        primary_reason = "submitted_without_entry_fill"
        action = "limit price 거리, 주문 만료/취소 정책, 미체결 주문 상태를 확인"
        summary_ko = "주문 제출은 되었지만 아직 진입 체결이 없습니다."
    elif ratio < max(0.0, float(min_flow_ratio)):
        stage = "live_flow_thin"
        primary_reason = "live_flow_below_replay_baseline"
        action = "심볼별 runtime selection과 validation/rollout 차단 비중을 함께 확인"
        summary_ko = "라이브 flow가 리플레이 기대치보다 얇습니다."
    else:
        stage = "flow_within_baseline"
        primary_reason = "live_flow_within_replay_baseline"
        action = "추가 조치 없음"
        summary_ko = "라이브 flow가 리플레이 기준 대비 허용 범위 안에 있습니다."

    return {
        "stage": stage,
        "primary_reason": primary_reason,
        "recommended_action": action,
        "summary": summary_ko,
        "intent_count": intent_count,
        "submit_ready": submit_ready,
        "blocked": blocked,
        "submissions": submissions,
        "requested_live": requested_live,
        "rejected_or_error": rejected_or_error,
        "entry_fills": entry_fills,
        "top_block_reason": str(top_reason or ""),
        "decision_counts": decision_counts,
        "non_submit_decision_count": non_submit_decision_count,
    }


def _runtime_evidence_floor_wait_flow(flow: dict[str, Any]) -> dict[str, Any]:
    payload = dict(flow or {})
    payload["original_stage"] = payload.get("stage")
    payload["original_primary_reason"] = payload.get("primary_reason")
    payload["stage"] = "runtime_evidence_floor_wait"
    payload["primary_reason"] = "runtime_window_below_evidence_floor_no_current_flow"
    payload["recommended_action"] = "추가 조치 없음; 현재 runtime의 다음 fresh 후보를 대기"
    payload["summary"] = (
        "현재 runtime 창의 replay 기대 후보가 판단 기준보다 적어 flow shortfall로 보지 않고 fresh 후보 대기로 봅니다."
    )
    payload["actionable"] = False
    return payload


def evaluate_parity(*, dashboard: dict[str, Any], lifecycle: dict[str, Any], min_flow_ratio: float) -> dict[str, Any]:
    active_contract = dict(dashboard.get("active_contract") or {})
    cadence = dict(active_contract.get("flow_cadence") or {})
    replay = dict(active_contract.get("replay_flow_baseline") or {})
    expected = _safe_float(replay.get("expected_active_contract_candidates_per_week_from_replay"))
    observed = _safe_float(replay.get("observed_current_window_active_contract_intents_per_week_live"))
    if observed <= 0.0:
        observed = _safe_float(cadence.get("current_window_active_contract_intents_per_week"))
    ratio = observed / expected if expected > 0.0 else 0.0
    expected_window = _expected_window_candidates(expected, cadence)
    thin_symbol_window = (
        expected_window is not None
        and expected_window < _MIN_EXPECTED_WINDOW_CANDIDATES_FOR_SYMBOL_ALERT
    )
    runtime_scope = str(cadence.get("cadence_window_basis") or "").startswith("runtime_since_ws_start")
    summary = dict(lifecycle.get("summary") or {})
    live_intents = dict(summary.get("live_intents") or {})
    top_reasons = dict(live_intents.get("top_block_reasons") or {})
    flow = _flow_diagnosis(
        expected=expected,
        ratio=ratio,
        min_flow_ratio=min_flow_ratio,
        summary=summary,
        live_intents=live_intents,
        top_reasons=top_reasons,
    )
    flow_stage = str(flow.get("stage") or "")
    runtime_window_below_evidence_floor = bool(runtime_scope and thin_symbol_window)
    runtime_no_actionable_flow = bool(
        runtime_window_below_evidence_floor
        and flow_stage == "signal_or_plan_generation_gap"
        and _safe_int(live_intents.get("total")) <= 0
        and _safe_int(summary.get("submission_count")) <= 0
        and _safe_int(summary.get("requested_live_count")) <= 0
        and _safe_int(summary.get("rejected_or_error_count")) <= 0
    )
    if runtime_no_actionable_flow:
        flow = _runtime_evidence_floor_wait_flow(flow)
        flow_stage = str(flow.get("stage") or "")

    if expected <= 0.0:
        status = "INSUFFICIENT_BASELINE"
        reason = "replay_flow_baseline_unavailable"
    elif runtime_no_actionable_flow:
        status = "PASS"
        reason = "runtime_window_below_live_replay_parity_evidence_floor"
    elif ratio < max(0.0, float(min_flow_ratio)):
        if thin_symbol_window:
            status = "WATCH"
            reason = "symbol_live_flow_thin_window_below_replay_baseline"
        else:
            status = "ALERT"
            reason = "live_flow_below_replay_baseline"
    else:
        status = "PASS"
        reason = "live_flow_within_replay_baseline"

    order_flow_status = "PASS"
    order_flow_reason = "order_flow_clear"
    flow_reason = str(flow.get("primary_reason") or "")
    if flow_stage in {"intent_to_submission_gap", "exchange_submission_rejected_or_error"}:
        order_flow_status = "ALERT"
        order_flow_reason = flow_reason or flow_stage
    elif flow_stage in {"approval_gate_blocked", "submitted_waiting_for_fill"}:
        order_flow_status = "WATCH"
        order_flow_reason = flow_reason or flow_stage

    if status == "PASS" and order_flow_status == "WATCH":
        status = "WATCH"
        reason = order_flow_reason
    elif status == "WATCH" and order_flow_status == "WATCH":
        reason = order_flow_reason
    elif status != "INSUFFICIENT_BASELINE" and order_flow_status == "ALERT":
        status = "ALERT"
        reason = order_flow_reason

    if expected <= 0.0:
        diagnosis = "리플레이 baseline을 읽지 못했습니다. local baseline cache, local API, 또는 --dashboard-json 산출물을 확인해야 합니다."
    elif order_flow_status == "ALERT":
        diagnosis = "라이브 intent가 제출 가능하거나 제출됐지만 order submission/exchange 단계에서 문제가 감지됐습니다."
    elif order_flow_status == "WATCH":
        diagnosis = "리플레이 대비 후보 빈도는 충분해도 실제 주문 flow는 승인/체결 단계에서 막혀 있습니다."
    elif runtime_no_actionable_flow:
        diagnosis = (
            "런타임 재시작 이후 parity 판단 창의 replay 기대 후보가 2건 미만입니다. "
            "현재 창에 live intent/submission도 없으므로 flow shortfall 경고가 아니라 fresh 후보 대기로 봅니다."
        )
    elif status == "WATCH" and thin_symbol_window:
        diagnosis = (
            "심볼 단일 짧은 창에서는 replay 기대 건수가 2건 미만이라 ALERT 대신 WATCH로 봅니다. "
            "포트폴리오 aggregate와 다음 창의 반복 여부를 함께 확인해야 합니다."
        )
    elif ratio < max(0.0, float(min_flow_ratio)):
        diagnosis = (
            "백테스트/리플레이 기대 빈도 대비 라이브 intent 빈도가 낮습니다. "
            "전략 자체보다 runtime selection, validation, rollout/session gate를 우선 확인해야 합니다."
        )
    else:
        diagnosis = "리플레이 대비 라이브 flow 차이가 차단 기준 이하로 보입니다."

    return {
        "status": status,
        "reason": reason,
        "expected_per_week": round(expected, 4),
        "observed_per_week": round(observed, 4),
        "live_vs_replay_flow_ratio": round(ratio, 4) if expected > 0.0 else None,
        "min_flow_ratio": float(min_flow_ratio),
        "expected_window_candidates": round(expected_window, 4) if expected_window is not None else None,
        "min_expected_window_candidates_for_alert": _MIN_EXPECTED_WINDOW_CANDIDATES_FOR_SYMBOL_ALERT,
        "thin_symbol_window": thin_symbol_window,
        "runtime_window_below_evidence_floor": runtime_window_below_evidence_floor,
        "runtime_no_actionable_flow": runtime_no_actionable_flow,
        "recent_live_intents": int(live_intents.get("total") or 0),
        "recent_live_submissions": int(summary.get("submission_count") or 0),
        "top_block_reasons": top_reasons,
        "order_flow_status": order_flow_status,
        "order_flow_reason": order_flow_reason,
        "flow_diagnosis": flow,
        "diagnosis": diagnosis,
    }


def _evaluation_summary(payload: dict[str, Any]) -> dict[str, Any]:
    evaluation = dict(payload.get("evaluation") or {})
    return {
        "status": payload.get("overall_status") or evaluation.get("status"),
        "reason": evaluation.get("reason"),
        "expected_per_week": evaluation.get("expected_per_week"),
        "observed_per_week": evaluation.get("observed_per_week"),
        "live_vs_replay_flow_ratio": evaluation.get("live_vs_replay_flow_ratio"),
        "expected_window_candidates": evaluation.get("expected_window_candidates"),
        "recent_live_intents": evaluation.get("recent_live_intents"),
        "recent_live_submissions": evaluation.get("recent_live_submissions"),
        "top_block_reasons": evaluation.get("top_block_reasons") or {},
        "flow_stage_counts": evaluation.get("flow_stage_counts") or {},
        "flow_primary_reason_counts": evaluation.get("flow_primary_reason_counts") or {},
        "alert_symbol_count": evaluation.get("alert_symbol_count"),
        "watch_symbol_count": evaluation.get("watch_symbol_count"),
    }


def _annotate_runtime_pass_with_lookback_warning(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep lookback context visible without paging when the fresh runtime window is too thin."""
    enriched = dict(payload)
    evaluation = dict(enriched.get("evaluation") or {})
    lookback = dict(enriched.get("lookback_evaluation_summary") or {})
    current_reason = str(evaluation.get("reason") or "")
    current_status = str(enriched.get("overall_status") or evaluation.get("status") or "")
    lookback_status = str(lookback.get("status") or "")
    if (
        current_status == "PASS"
        and current_reason in {
            "runtime_window_below_live_replay_parity_evidence_floor",
            "portfolio_runtime_window_below_live_replay_parity_evidence_floor",
        }
        and lookback_status in {"WATCH", "ALERT"}
    ):
        evaluation["lookback_advisory"] = True
        evaluation["lookback_status"] = lookback_status
        evaluation["lookback_reason"] = lookback.get("reason")
        evaluation["lookback_top_block_reasons"] = lookback.get("top_block_reasons") or {}
        evaluation["operator_action_required"] = False
        enriched["evaluation"] = evaluation
    return enriched


def build_payload(
    *,
    base_url: str,
    symbol: str,
    universe: str,
    days: int,
    dashboard_json: str,
    min_flow_ratio: float,
    start_at: datetime | None = None,
    include_lookback_context: bool = True,
) -> dict[str, Any]:
    dashboard = _load_dashboard(dashboard_json)
    dashboard_source = "dashboard_json" if dashboard else ""
    dashboard_errors: list[str] = []
    if not dashboard:
        try:
            dashboard = _build_dashboard_from_db(symbol=symbol, universe=universe, days=days, start_at=start_at)
            dashboard_source = "local_db_replay_baseline" if dashboard else ""
        except Exception as exc:
            dashboard_errors.append(f"local_db_replay_baseline:{exc.__class__.__name__}:{exc}")
    if not dashboard:
        try:
            dashboard = _request_dashboard(base_url=base_url, symbol=symbol, universe=universe, days=days)
            dashboard_source = "local_api_operator_dashboard" if dashboard else ""
        except Exception as exc:
            dashboard_errors.append(f"local_api_operator_dashboard:{exc.__class__.__name__}:{exc}")

    active_contract = dict(dashboard.get("active_contract") or {})
    filters = dict(active_contract.get("filters") or {})
    strategy_families = [
        str(item or "").strip()
        for item in list(filters.get("strategy_families") or [])
        if str(item or "").strip()
    ]

    init_db()
    with SessionLocal() as db:
        lifecycle = LiveOrderLifecycleReporter(db).generate(
            days=days,
            symbol=symbol,
            live_only=True,
            limit=200,
            start_at=start_at,
            strategy_families=strategy_families or None,
        )
    evaluation = evaluate_parity(dashboard=dashboard, lifecycle=lifecycle, min_flow_ratio=min_flow_ratio)
    if dashboard_errors and evaluation["status"] == "INSUFFICIENT_BASELINE":
        evaluation["dashboard_errors"] = dashboard_errors
    payload = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "symbol": symbol.upper(),
        "window_days": max(1, int(days)),
        "parity_scope": "runtime_since_ws_start" if start_at is not None else "lookback_window",
        "runtime_started_at": start_at.isoformat().replace("+00:00", "Z") if start_at is not None else None,
        "overall_status": evaluation["status"],
        "dashboard_source": dashboard_source or "unavailable",
        "dashboard_errors": dashboard_errors,
        "evaluation": evaluation,
        "active_contract": dict(dashboard.get("active_contract") or {}),
        "lifecycle_summary": dict(lifecycle.get("summary") or {}),
    }
    if start_at is not None and include_lookback_context:
        lookback_payload = build_payload(
            base_url=base_url,
            symbol=symbol,
            universe=universe,
            days=days,
            dashboard_json=dashboard_json,
            min_flow_ratio=min_flow_ratio,
            start_at=None,
            include_lookback_context=False,
        )
        payload["lookback_evaluation_summary"] = _evaluation_summary(lookback_payload)
        payload["lookback_lifecycle_summary"] = dict(lookback_payload.get("lifecycle_summary") or {})
    else:
        payload["lookback_evaluation_summary"] = {}
        payload["lookback_lifecycle_summary"] = {}
    payload = _annotate_runtime_pass_with_lookback_warning(payload)
    return payload


def _live_symbols_from_settings() -> list[str]:
    settings = get_settings()
    return sorted(_csv_set(getattr(settings, "auto_trading_micro_live_allowed_symbols", "")))


def build_portfolio_payload(
    *,
    base_url: str,
    universe: str,
    days: int,
    min_flow_ratio: float,
    start_at: datetime | None = None,
    include_lookback_context: bool = True,
) -> dict[str, Any]:
    symbols = _live_symbols_from_settings()
    rows = [
        build_payload(
            base_url=base_url,
            symbol=symbol,
            universe=universe,
            days=days,
            dashboard_json="",
            min_flow_ratio=min_flow_ratio,
            start_at=start_at,
            include_lookback_context=False,
        )
        for symbol in symbols
    ]
    expected = sum(_safe_float(dict(row.get("evaluation") or {}).get("expected_per_week")) for row in rows)
    observed = sum(_safe_float(dict(row.get("evaluation") or {}).get("observed_per_week")) for row in rows)
    ratio = observed / expected if expected > 0.0 else 0.0
    expected_window_values = [
        _safe_float(dict(row.get("evaluation") or {}).get("expected_window_candidates"), default=0.0)
        for row in rows
    ]
    expected_window = sum(value for value in expected_window_values if value > 0.0)
    reason_counts: dict[str, int] = {}
    flow_stage_counts: dict[str, int] = {}
    flow_reason_counts: dict[str, int] = {}
    for row in rows:
        evaluation = dict(row.get("evaluation") or {})
        for reason, count in dict(evaluation.get("top_block_reasons") or {}).items():
            reason_counts[str(reason)] = reason_counts.get(str(reason), 0) + int(count or 0)
        flow = dict(evaluation.get("flow_diagnosis") or {})
        stage = str(flow.get("stage") or "unknown")
        primary_reason = str(flow.get("primary_reason") or "unknown")
        flow_stage_counts[stage] = flow_stage_counts.get(stage, 0) + 1
        flow_reason_counts[primary_reason] = flow_reason_counts.get(primary_reason, 0) + 1
    alert_symbol_count = sum(1 for row in rows if dict(row.get("evaluation") or {}).get("status") == "ALERT")
    watch_symbol_count = sum(1 for row in rows if dict(row.get("evaluation") or {}).get("status") == "WATCH")
    insufficient_symbol_count = sum(
        1 for row in rows if dict(row.get("evaluation") or {}).get("status") == "INSUFFICIENT_BASELINE"
    )
    flow_shortfall_watch_count = sum(flow_stage_counts.get(stage, 0) for stage in _PORTFOLIO_FLOW_SHORTFALL_STAGES)
    order_gate_watch_count = sum(flow_stage_counts.get(stage, 0) for stage in _PORTFOLIO_ORDER_GATE_STAGES)
    runtime_below_floor_symbol_count = sum(
        1 for row in rows if bool(dict(row.get("evaluation") or {}).get("runtime_no_actionable_flow"))
    )
    runtime_window_below_evidence_floor = bool(
        start_at is not None
        and expected_window < _MIN_EXPECTED_WINDOW_CANDIDATES_FOR_SYMBOL_ALERT
        and alert_symbol_count <= 0
        and watch_symbol_count <= 0
    )
    if not symbols or expected <= 0.0:
        status = "INSUFFICIENT_BASELINE"
        reason = "portfolio_replay_flow_baseline_unavailable"
    elif alert_symbol_count > 0:
        status = "ALERT"
        reason = "portfolio_symbol_live_flow_below_replay_baseline"
    elif watch_symbol_count > 0:
        status = "WATCH"
        if flow_shortfall_watch_count > 0 and order_gate_watch_count > 0:
            reason = "portfolio_symbol_live_flow_and_order_gate_watch"
        elif flow_shortfall_watch_count > 0:
            reason = "portfolio_symbol_live_flow_watch_thin_window"
        elif order_gate_watch_count > 0:
            reason = "portfolio_symbol_order_flow_blocked_or_waiting"
        else:
            reason = "portfolio_symbol_watch"
    elif runtime_window_below_evidence_floor:
        status = "PASS"
        reason = "portfolio_runtime_window_below_live_replay_parity_evidence_floor"
    elif ratio < max(0.0, float(min_flow_ratio)):
        status = "ALERT"
        reason = "portfolio_live_flow_below_replay_baseline"
    else:
        status = "PASS"
        reason = "portfolio_live_flow_within_replay_baseline"
    payload = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "scope": "all_live_symbols",
        "symbols": symbols,
        "window_days": max(1, int(days)),
        "parity_scope": "runtime_since_ws_start" if start_at is not None else "lookback_window",
        "runtime_started_at": start_at.isoformat().replace("+00:00", "Z") if start_at is not None else None,
        "overall_status": status,
        "evaluation": {
            "status": status,
            "reason": reason,
            "expected_per_week": round(expected, 4),
            "observed_per_week": round(observed, 4),
            "live_vs_replay_flow_ratio": round(ratio, 4) if expected > 0.0 else None,
            "min_flow_ratio": float(min_flow_ratio),
            "expected_window_candidates": round(expected_window, 4),
            "min_expected_window_candidates_for_alert": _MIN_EXPECTED_WINDOW_CANDIDATES_FOR_SYMBOL_ALERT,
            "runtime_window_below_evidence_floor": runtime_window_below_evidence_floor,
            "runtime_below_evidence_floor_symbol_count": runtime_below_floor_symbol_count,
            "top_block_reasons": dict(sorted(reason_counts.items(), key=lambda item: item[1], reverse=True)[:10]),
            "flow_stage_counts": dict(sorted(flow_stage_counts.items(), key=lambda item: item[1], reverse=True)[:10]),
            "flow_primary_reason_counts": dict(sorted(flow_reason_counts.items(), key=lambda item: item[1], reverse=True)[:10]),
            "symbol_count": len(symbols),
            "alert_symbol_count": alert_symbol_count,
            "watch_symbol_count": watch_symbol_count,
            "insufficient_symbol_count": insufficient_symbol_count,
            "flow_shortfall_watch_count": flow_shortfall_watch_count,
            "order_gate_watch_count": order_gate_watch_count,
        },
        "rows": rows,
    }
    if start_at is not None and include_lookback_context:
        lookback_payload = build_portfolio_payload(
            base_url=base_url,
            universe=universe,
            days=days,
            min_flow_ratio=min_flow_ratio,
            start_at=None,
            include_lookback_context=False,
        )
        payload["lookback_evaluation_summary"] = _evaluation_summary(lookback_payload)
    else:
        payload["lookback_evaluation_summary"] = {}
    payload = _annotate_runtime_pass_with_lookback_warning(payload)
    return payload


def _write_report(path: Path, payload: dict[str, Any], *, atomic: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    evaluation = dict(payload.get("evaluation") or {})
    symbol = payload.get("symbol") or payload.get("scope")
    is_portfolio = bool(payload.get("scope") == "all_live_symbols")
    lines = [
        "# Live vs Replay Parity Audit",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- {'scope' if is_portfolio else 'symbol'}: {symbol}",
        f"- parity_scope: {payload.get('parity_scope')}",
        f"- runtime_started_at: {payload.get('runtime_started_at') or 'none'}",
        f"- status: {payload.get('overall_status')}",
        f"- reason: {evaluation.get('reason')}",
        f"- expected_per_week: {evaluation.get('expected_per_week')}",
        f"- observed_per_week: {evaluation.get('observed_per_week')}",
        f"- live_vs_replay_flow_ratio: {evaluation.get('live_vs_replay_flow_ratio')}",
        f"- expected_window_candidates: {evaluation.get('expected_window_candidates')}",
        f"- lookback_evaluation_summary: {payload.get('lookback_evaluation_summary') or {}}",
    ]
    if is_portfolio:
        lines.extend(
            [
                f"- symbol_count: {evaluation.get('symbol_count')}",
                f"- alert_symbol_count: {evaluation.get('alert_symbol_count')}",
                f"- watch_symbol_count: {evaluation.get('watch_symbol_count')}",
                f"- flow_shortfall_watch_count: {evaluation.get('flow_shortfall_watch_count')}",
                f"- order_gate_watch_count: {evaluation.get('order_gate_watch_count')}",
                f"- flow_stage_counts: {evaluation.get('flow_stage_counts')}",
                f"- flow_primary_reason_counts: {evaluation.get('flow_primary_reason_counts')}",
            ]
        )
    else:
        lines.extend(
            [
                f"- dashboard_source: {payload.get('dashboard_source')}",
                f"- order_flow_status: {evaluation.get('order_flow_status')}",
                f"- order_flow_reason: {evaluation.get('order_flow_reason')}",
                f"- diagnosis: {evaluation.get('diagnosis')}",
                f"- flow_stage: {dict(evaluation.get('flow_diagnosis') or {}).get('stage')}",
                f"- flow_action: {dict(evaluation.get('flow_diagnosis') or {}).get('recommended_action')}",
            ]
        )
    lines.extend(["", "```json", json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), "```"])
    atomic_write_text(path, "\n".join(lines))


def main() -> int:
    args = parse_args()
    runtime_started_at = None if bool(args.lookback_only) else _ws_runtime_started_at(str(args.heartbeat_dir or ""))
    if bool(args.all_live_symbols):
        payload = build_portfolio_payload(
            base_url=str(args.base_url),
            universe=str(args.universe),
            days=max(1, int(args.days)),
            min_flow_ratio=float(args.min_flow_ratio),
            start_at=runtime_started_at,
        )
    else:
        payload = build_payload(
            base_url=str(args.base_url),
            symbol=str(args.symbol),
            universe=str(args.universe),
            days=max(1, int(args.days)),
            dashboard_json=str(args.dashboard_json or ""),
            min_flow_ratio=float(args.min_flow_ratio),
            start_at=runtime_started_at,
        )
    if not args.no_write_report:
        generated = parse_report_generated_at(payload.get("generated_at"))
        report_symbol = str(payload.get("symbol") or payload.get("scope") or "UNKNOWN").upper()
        report_dir = ROOT_DIR / args.report_dir
        report_path = report_dir / f"live_replay_parity_{report_symbol}_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
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
    fail = payload["overall_status"] == "ALERT"
    return 1 if fail and not bool(args.no_fail_exit) else 0


if __name__ == "__main__":
    raise SystemExit(main())
