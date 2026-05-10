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
from app.services.live_order_lifecycle import LiveOrderLifecycleReporter
from scripts.operation_report_io import atomic_write_text, parse_report_generated_at


_ACTIVE_CONTRACT_REPLAY_BASELINE_FILE = "strategy_proof_contract_live_subset.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare live MICRO_LIVE flow against replay/dashboard flow baseline.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default="BTCUSDC")
    parser.add_argument("--all-live-symbols", action="store_true")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--dashboard-json", default="")
    parser.add_argument("--min-flow-ratio", type=float, default=0.25)
    parser.add_argument("--report-dir", default="reports/operations/live_replay_parity")
    parser.add_argument("--no-write-report", action="store_true")
    parser.add_argument("--no-fail-exit", action="store_true")
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


def _active_contract_filters_from_settings(symbol: str) -> dict[str, Any]:
    settings = get_settings()
    normalized_symbol = str(symbol or "").strip().upper()
    return {
        "symbol": normalized_symbol,
        "execution_mode": "MICRO_LIVE",
        "strategy_families": sorted(_csv_set(getattr(settings, "auto_trading_micro_live_allowed_families", ""), lower=True)),
        "entry_models": sorted(_csv_set(getattr(settings, "auto_trading_micro_live_allowed_entry_models", ""))),
        "directions": list(_direction_contract(getattr(settings, "auto_trading_micro_live_direction_contract", "")).get(normalized_symbol) or []),
    }


def _flow_cadence_from_db(*, symbol: str, filters: dict[str, Any], days: int) -> dict[str, Any]:
    normalized_days = max(1, int(days))
    cutoff = datetime.now(UTC) - timedelta(days=normalized_days)
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
    last_created_at = max((_as_utc(row.created_at) for row in rows), default=None)
    return {
        "cadence_window_days": normalized_days,
        "cadence_window_basis": "recent_active_contract_intents_local_db",
        "hours_since_last_active_contract_intent": (
            round((datetime.now(UTC) - last_created_at).total_seconds() / 3600.0, 4)
            if last_created_at is not None
            else None
        ),
        "runtime_candidates_current_snapshot": 0,
        "current_window_active_contract_intent_count": len(rows),
        "current_window_active_contract_intents_per_week": round((len(rows) / normalized_days) * 7.0, 4),
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
    replay_rows = [
        dict(row)
        for row in list(payload.get("trade_rows") or [])
        if isinstance(row, dict)
        and (not filter_symbol or str(row.get("symbol") or "").strip().upper() == filter_symbol)
        and (not strategy_families or str(row.get("strategy_family") or "").strip().lower() in strategy_families)
        and (not entry_models or str(row.get("entry_model") or "").strip().upper() in entry_models)
        and (not directions or str(row.get("direction") or "").strip().upper() in directions)
    ]
    expected_per_week = round(len(replay_rows) / replay_window_weeks, 4) if replay_window_weeks > 0 else 0.0
    observed = _safe_float(cadence_window.get("current_window_active_contract_intents_per_week"))
    return {
        "available": True,
        "source_path": str(cache_path),
        "replay_window_days": round(replay_window_days, 4),
        "expected_active_contract_candidates_per_week_from_replay": expected_per_week,
        "expected_closed_per_week_from_replay": expected_per_week,
        "observed_current_window_active_contract_intents_per_week_live": observed,
        "live_vs_replay_flow_ratio": round(observed / expected_per_week, 4) if expected_per_week > 0 else None,
        "comparison_only": True,
        "matched_replay_rows": len(replay_rows),
    }


def _build_dashboard_from_db(*, symbol: str, universe: str, days: int) -> dict[str, Any]:
    del universe
    filters = _active_contract_filters_from_settings(symbol)
    cadence = _flow_cadence_from_db(symbol=symbol, filters=filters, days=days)
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
    elif intent_count > 0 and blocked >= intent_count and submit_ready <= 0:
        stage = "approval_gate_blocked"
        primary_reason = str(top_reason or "all_recent_live_intents_blocked")
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
    }


def evaluate_parity(*, dashboard: dict[str, Any], lifecycle: dict[str, Any], min_flow_ratio: float) -> dict[str, Any]:
    active_contract = dict(dashboard.get("active_contract") or {})
    cadence = dict(active_contract.get("flow_cadence") or {})
    replay = dict(active_contract.get("replay_flow_baseline") or {})
    expected = _safe_float(replay.get("expected_active_contract_candidates_per_week_from_replay"))
    observed = _safe_float(replay.get("observed_current_window_active_contract_intents_per_week_live"))
    if observed <= 0.0:
        observed = _safe_float(cadence.get("current_window_active_contract_intents_per_week"))
    ratio = observed / expected if expected > 0.0 else 0.0
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

    if expected <= 0.0:
        status = "INSUFFICIENT_BASELINE"
        reason = "replay_flow_baseline_unavailable"
    elif ratio < max(0.0, float(min_flow_ratio)):
        status = "ALERT"
        reason = "live_flow_below_replay_baseline"
    else:
        status = "PASS"
        reason = "live_flow_within_replay_baseline"

    order_flow_status = "PASS"
    order_flow_reason = "order_flow_clear"
    flow_stage = str(flow.get("stage") or "")
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
    elif status != "INSUFFICIENT_BASELINE" and order_flow_status == "ALERT":
        status = "ALERT"
        reason = order_flow_reason

    if expected <= 0.0:
        diagnosis = "리플레이 baseline을 읽지 못했습니다. local baseline cache, local API, 또는 --dashboard-json 산출물을 확인해야 합니다."
    elif order_flow_status == "ALERT":
        diagnosis = "라이브 intent가 제출 가능하거나 제출됐지만 order submission/exchange 단계에서 문제가 감지됐습니다."
    elif order_flow_status == "WATCH":
        diagnosis = "리플레이 대비 후보 빈도는 충분해도 실제 주문 flow는 승인/체결 단계에서 막혀 있습니다."
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
        "recent_live_intents": int(live_intents.get("total") or 0),
        "recent_live_submissions": int(summary.get("submission_count") or 0),
        "top_block_reasons": top_reasons,
        "order_flow_status": order_flow_status,
        "order_flow_reason": order_flow_reason,
        "flow_diagnosis": flow,
        "diagnosis": diagnosis,
    }


def build_payload(*, base_url: str, symbol: str, universe: str, days: int, dashboard_json: str, min_flow_ratio: float) -> dict[str, Any]:
    dashboard = _load_dashboard(dashboard_json)
    dashboard_source = "dashboard_json" if dashboard else ""
    dashboard_errors: list[str] = []
    if not dashboard:
        try:
            dashboard = _build_dashboard_from_db(symbol=symbol, universe=universe, days=days)
            dashboard_source = "local_db_replay_baseline" if dashboard else ""
        except Exception as exc:
            dashboard_errors.append(f"local_db_replay_baseline:{exc.__class__.__name__}:{exc}")
    if not dashboard:
        try:
            dashboard = _request_dashboard(base_url=base_url, symbol=symbol, universe=universe, days=days)
            dashboard_source = "local_api_operator_dashboard" if dashboard else ""
        except Exception as exc:
            dashboard_errors.append(f"local_api_operator_dashboard:{exc.__class__.__name__}:{exc}")

    init_db()
    with SessionLocal() as db:
        lifecycle = LiveOrderLifecycleReporter(db).generate(days=days, symbol=symbol, live_only=True, limit=200)
    evaluation = evaluate_parity(dashboard=dashboard, lifecycle=lifecycle, min_flow_ratio=min_flow_ratio)
    if dashboard_errors and evaluation["status"] == "INSUFFICIENT_BASELINE":
        evaluation["dashboard_errors"] = dashboard_errors
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "symbol": symbol.upper(),
        "window_days": max(1, int(days)),
        "overall_status": evaluation["status"],
        "dashboard_source": dashboard_source or "unavailable",
        "dashboard_errors": dashboard_errors,
        "evaluation": evaluation,
        "active_contract": dict(dashboard.get("active_contract") or {}),
        "lifecycle_summary": dict(lifecycle.get("summary") or {}),
    }


def _live_symbols_from_settings() -> list[str]:
    settings = get_settings()
    return sorted(_csv_set(getattr(settings, "auto_trading_micro_live_allowed_symbols", "")))


def build_portfolio_payload(*, base_url: str, universe: str, days: int, min_flow_ratio: float) -> dict[str, Any]:
    symbols = _live_symbols_from_settings()
    rows = [
        build_payload(
            base_url=base_url,
            symbol=symbol,
            universe=universe,
            days=days,
            dashboard_json="",
            min_flow_ratio=min_flow_ratio,
        )
        for symbol in symbols
    ]
    expected = sum(_safe_float(dict(row.get("evaluation") or {}).get("expected_per_week")) for row in rows)
    observed = sum(_safe_float(dict(row.get("evaluation") or {}).get("observed_per_week")) for row in rows)
    ratio = observed / expected if expected > 0.0 else 0.0
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
    if not symbols or expected <= 0.0:
        status = "INSUFFICIENT_BASELINE"
        reason = "portfolio_replay_flow_baseline_unavailable"
    elif alert_symbol_count > 0:
        status = "ALERT"
        reason = "portfolio_symbol_live_flow_below_replay_baseline"
    elif watch_symbol_count > 0:
        status = "WATCH"
        reason = "portfolio_symbol_order_flow_blocked_or_waiting"
    elif ratio < max(0.0, float(min_flow_ratio)):
        status = "ALERT"
        reason = "portfolio_live_flow_below_replay_baseline"
    else:
        status = "PASS"
        reason = "portfolio_live_flow_within_replay_baseline"
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "scope": "all_live_symbols",
        "symbols": symbols,
        "window_days": max(1, int(days)),
        "overall_status": status,
        "evaluation": {
            "status": status,
            "reason": reason,
            "expected_per_week": round(expected, 4),
            "observed_per_week": round(observed, 4),
            "live_vs_replay_flow_ratio": round(ratio, 4) if expected > 0.0 else None,
            "min_flow_ratio": float(min_flow_ratio),
            "top_block_reasons": dict(sorted(reason_counts.items(), key=lambda item: item[1], reverse=True)[:10]),
            "flow_stage_counts": dict(sorted(flow_stage_counts.items(), key=lambda item: item[1], reverse=True)[:10]),
            "flow_primary_reason_counts": dict(sorted(flow_reason_counts.items(), key=lambda item: item[1], reverse=True)[:10]),
            "symbol_count": len(symbols),
            "alert_symbol_count": alert_symbol_count,
            "watch_symbol_count": watch_symbol_count,
            "insufficient_symbol_count": insufficient_symbol_count,
        },
        "rows": rows,
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    evaluation = dict(payload.get("evaluation") or {})
    symbol = payload.get("symbol") or payload.get("scope")
    lines = [
        "# Live vs Replay Parity Audit",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- symbol: {symbol}",
        f"- status: {payload.get('overall_status')}",
        f"- dashboard_source: {payload.get('dashboard_source')}",
        f"- reason: {evaluation.get('reason')}",
        f"- expected_per_week: {evaluation.get('expected_per_week')}",
        f"- observed_per_week: {evaluation.get('observed_per_week')}",
        f"- live_vs_replay_flow_ratio: {evaluation.get('live_vs_replay_flow_ratio')}",
        f"- order_flow_status: {evaluation.get('order_flow_status')}",
        f"- order_flow_reason: {evaluation.get('order_flow_reason')}",
        f"- diagnosis: {evaluation.get('diagnosis')}",
        f"- flow_stage: {dict(evaluation.get('flow_diagnosis') or {}).get('stage')}",
        f"- flow_action: {dict(evaluation.get('flow_diagnosis') or {}).get('recommended_action')}",
        "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        "```",
    ]
    atomic_write_text(path, "\n".join(lines))


def main() -> int:
    args = parse_args()
    if bool(args.all_live_symbols):
        payload = build_portfolio_payload(
            base_url=str(args.base_url),
            universe=str(args.universe),
            days=max(1, int(args.days)),
            min_flow_ratio=float(args.min_flow_ratio),
        )
    else:
        payload = build_payload(
            base_url=str(args.base_url),
            symbol=str(args.symbol),
            universe=str(args.universe),
            days=max(1, int(args.days)),
            dashboard_json=str(args.dashboard_json or ""),
            min_flow_ratio=float(args.min_flow_ratio),
        )
    if not args.no_write_report:
        generated = parse_report_generated_at(payload.get("generated_at"))
        report_symbol = str(payload.get("symbol") or payload.get("scope") or "UNKNOWN").upper()
        report_path = ROOT_DIR / args.report_dir / f"live_replay_parity_{report_symbol}_{generated.strftime('%Y%m%dT%H%M%SZ')}.md"
        _write_report(report_path, payload)
        payload["report_path"] = _display_path(report_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    fail = payload["overall_status"] == "ALERT"
    return 1 if fail and not bool(args.no_fail_exit) else 0


if __name__ == "__main__":
    raise SystemExit(main())
