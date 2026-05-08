#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from http.client import RemoteDisconnected
from pathlib import Path
import socket
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
_REQUEST_RETRY_ATTEMPTS = 5
_REQUEST_RETRY_BASE_DELAY_SECONDS = 1.0
_REQUEST_TIMEOUT_SECONDS = 90
_DEFAULT_STAGE_FILE = ROOT_DIR / "reports/operations/stage_monitor/current_stage.json"
_DEFAULT_DB_PATH = ROOT_DIR / "trading.db"
_SYMBOL_DIVERSITY_MIN_COHORT_TRADES = 20
_SYMBOL_DIVERSITY_SOFT_CAP_COUNT = 6
_SYMBOL_DIVERSITY_SOFT_CAP_SHARE = 0.10
_PAPER_FAMILY_CLUSTER_WINDOW_MINUTES = 60
_PAPER_MAX_SAME_FAMILY_ENTRIES_PER_WINDOW = 1
_PAPER_RECENT_LOSS_COOLDOWN_MINUTES = 90
_PAPER_RECENT_LOSS_TRIGGER_COUNT = 2
_ENTRY_VARIANT_PREFERENCE = {
    "limit": 0,
    "sweep_confirm": 1,
    "confirm": 2,
    "unknown": 3,
}


def _database_url() -> str:
    return str(os.environ.get("DATABASE_URL") or "").strip()


def _current_db_path() -> Path:
    database_url = _database_url()
    for prefix in ("sqlite+pysqlite:///", "sqlite:///"):
        if database_url.startswith(prefix):
            raw_path = database_url[len(prefix) :].split("?", 1)[0].strip()
            if not raw_path or raw_path in {":memory:", "file::memory:"}:
                return _DEFAULT_DB_PATH
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = (ROOT_DIR / candidate).resolve()
            return candidate
    return _DEFAULT_DB_PATH


def _load_trend_proof_priority_snapshot(*, families: set[str]) -> dict[str, Any]:
    if "trend_continuation" not in families:
        return {
            "available": False,
            "active": False,
            "summary": "trend_continuation is not requested for this PAPER drill pass",
        }
    stage_payload = _load_json(_DEFAULT_STAGE_FILE)
    summary = dict((stage_payload or {}).get("trend_proof_post_patch_sample_summary") or {})
    target_closed_trades = int(summary.get("target_closed_trades", 5) or 5)
    closed_trade_count = int(summary.get("closed_trade_count", 0) or 0)
    remaining_to_target = max(int(summary.get("remaining_to_target", target_closed_trades - closed_trade_count) or 0), 0)
    eligible_symbols = [
        str(item or "").strip().upper()
        for item in (summary.get("eligible_symbols") or ["BTCUSDC", "ETHUSDC"])
        if str(item or "").strip()
    ]
    payload = {
        "available": True,
        "active": remaining_to_target > 0,
        "target_closed_trades": target_closed_trades,
        "closed_trade_count": closed_trade_count,
        "remaining_to_target": remaining_to_target,
        "eligible_symbols": eligible_symbols,
        "eligible_families": ["trend_continuation"],
        "eligible_entry_models": ["LIMIT"],
    }
    payload["summary"] = (
        f"trend_proof={closed_trade_count}/{target_closed_trades}"
        f" | remaining={remaining_to_target}"
        f" | symbols={','.join(eligible_symbols) or 'none'}"
    )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a PAPER candidate drill for eligible strategy families against the local API."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--symbol", default=None, help="Optional symbol pin. If omitted, pick the best eligible candidate.")
    parser.add_argument("--universe", default="usdc_perp_top30")
    parser.add_argument("--families", default="trend_continuation,sweep_reversal")
    parser.add_argument("--candidate-limit", type=int, default=100)
    parser.add_argument("--include-manual-review", action="store_true")
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--limit-symbols", type=int, default=30)
    parser.add_argument("--symbol-concurrency", type=int, default=4)
    parser.add_argument("--limit-1m", type=int, default=900)
    parser.add_argument("--limit-5m", type=int, default=500)
    parser.add_argument("--limit-15m", type=int, default=500)
    parser.add_argument("--submit-paper", action="store_true")
    parser.add_argument("--paper-scenario", default="fill", choices=["fill", "partial_fill", "cancel", "timeout", "reject", "attach_failure"])
    parser.add_argument(
        "--paper-lineage-override",
        action="store_true",
        help="Allow PAPER-only lineage override for eligible family candidates blocked by active-plan thesis duplication.",
    )
    parser.add_argument(
        "--symbol-diversity-min-cohort-trades",
        type=int,
        default=_SYMBOL_DIVERSITY_MIN_COHORT_TRADES,
    )
    parser.add_argument(
        "--symbol-diversity-soft-cap-count",
        type=int,
        default=_SYMBOL_DIVERSITY_SOFT_CAP_COUNT,
    )
    parser.add_argument(
        "--symbol-diversity-soft-cap-share",
        type=float,
        default=_SYMBOL_DIVERSITY_SOFT_CAP_SHARE,
    )
    parser.add_argument("--report-dir", default="reports/operations/paper_candidate_drill")
    parser.add_argument("--no-write-report", action="store_true")
    return parser.parse_args()


def _now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _request_json(
    base_url: str,
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any] | list[Any]:
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url += f"?{urlencode(query, doseq=True)}"
    data: bytes | None = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    last_error: RuntimeError | None = None
    for attempt in range(1, _REQUEST_RETRY_ATTEMPTS + 1):
        request = Request(url=url, data=data, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            retryable = exc.code >= 500 or "database is locked" in payload.lower() or "sqlite busy" in payload.lower()
            last_error = RuntimeError(f"{method.upper()} {path} failed with HTTP {exc.code}: {payload}")
            if retryable and attempt < _REQUEST_RETRY_ATTEMPTS:
                time.sleep(_REQUEST_RETRY_BASE_DELAY_SECONDS * attempt)
                continue
            raise last_error from exc
        except (URLError, TimeoutError, socket.timeout, RemoteDisconnected) as exc:
            reason = exc.reason if isinstance(exc, URLError) else str(exc)
            last_error = RuntimeError(f"{method.upper()} {path} failed: {reason}")
            if attempt < _REQUEST_RETRY_ATTEMPTS:
                time.sleep(_REQUEST_RETRY_BASE_DELAY_SECONDS * attempt)
                continue
            raise last_error from exc

    assert last_error is not None
    raise last_error


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _family_set(raw: str) -> set[str]:
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _parse_iso_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(payload) if isinstance(payload, dict) else None


def _stage_post_patch_baseline(stage_payload: dict[str, Any] | None) -> datetime | None:
    stage = dict(stage_payload or {})
    candidates = [
        dict(stage.get("post_patch_sample_summary") or {}),
        dict(dict(stage.get("approval_template_focus") or {}).get("post_patch_sample_summary") or {}),
        dict(
            dict(dict(stage.get("runtime_signoff_summary") or {}).get("approval_template_focus") or {}).get(
                "post_patch_sample_summary"
            )
            or {}
        ),
    ]
    for item in candidates:
        baseline = _parse_iso_ts(item.get("baseline_ts"))
        if baseline is not None:
            return baseline
    return None


def _load_symbol_diversity_snapshot(
    *,
    families: set[str],
    min_cohort_trades: int,
    soft_cap_count: int,
    soft_cap_share: float,
) -> dict[str, Any]:
    stage_payload = _load_json(_DEFAULT_STAGE_FILE)
    baseline_ts = _stage_post_patch_baseline(stage_payload)
    counts: Counter[str] = Counter()
    active_open_symbols: set[str] = set()
    db_path = _current_db_path()

    if not db_path.exists():
        return {
            "available": False,
            "baseline_ts": baseline_ts.isoformat() if baseline_ts else "",
            "closed_trade_count": 0,
            "symbol_closed_counts": {},
            "overrepresented_symbols": [],
            "active_open_symbols": [],
            "database_path": str(db_path),
            "summary": "local sqlite database is unavailable; symbol diversity weighting is disabled",
        }

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("select symbol, state, validity from plans where state in ('CLOSED','ENTERED','PARTIAL_EXIT')").fetchall()
    finally:
        conn.close()

    for symbol_raw, state_raw, validity_raw in rows:
        symbol = str(symbol_raw or "").strip().upper()
        state = str(state_raw or "").strip().upper()
        if not symbol or not isinstance(validity_raw, str):
            continue
        try:
            validity = json.loads(validity_raw) if validity_raw else {}
        except json.JSONDecodeError:
            continue
        if not isinstance(validity, dict):
            continue
        family = str(validity.get("strategy_family") or "").strip().lower()
        if family not in families:
            continue
        if state in {"ENTERED", "PARTIAL_EXIT"}:
            active_open_symbols.add(symbol)
        if state != "CLOSED":
            continue
        closed_ts = _parse_iso_ts(validity.get("final_exit_ts") or validity.get("last_exit_ts"))
        if baseline_ts is not None and (closed_ts is None or closed_ts < baseline_ts):
            continue
        counts[symbol] += 1

    closed_trade_count = int(sum(counts.values()))
    overrepresented_symbols: list[str] = []
    if closed_trade_count >= max(0, int(min_cohort_trades or 0)):
        for symbol, count in counts.items():
            share = float(count) / float(closed_trade_count) if closed_trade_count > 0 else 0.0
            if count >= max(0, int(soft_cap_count or 0)) and share >= max(0.0, float(soft_cap_share or 0.0)):
                overrepresented_symbols.append(symbol)

    overrepresented_symbols.sort()
    return {
        "available": True,
        "database_path": str(db_path),
        "baseline_ts": baseline_ts.isoformat() if baseline_ts else "",
        "closed_trade_count": closed_trade_count,
        "symbol_closed_counts": dict(counts),
        "overrepresented_symbols": overrepresented_symbols,
        "active_open_symbols": sorted(active_open_symbols),
        "summary": (
            f"closed={closed_trade_count}"
            f" | overrepresented={','.join(overrepresented_symbols) or 'none'}"
            f" | active_open={','.join(sorted(active_open_symbols)) or 'none'}"
        ),
    }


def _load_family_cluster_guard_snapshot(
    *,
    families: set[str],
    cluster_window_minutes: int = _PAPER_FAMILY_CLUSTER_WINDOW_MINUTES,
    max_same_family_entries: int = _PAPER_MAX_SAME_FAMILY_ENTRIES_PER_WINDOW,
    recent_loss_cooldown_minutes: int = _PAPER_RECENT_LOSS_COOLDOWN_MINUTES,
    recent_loss_trigger_count: int = _PAPER_RECENT_LOSS_TRIGGER_COUNT,
) -> dict[str, Any]:
    now = _now()
    entry_cutoff = now.timestamp() - max(0, int(cluster_window_minutes)) * 60
    loss_cutoff = now.timestamp() - max(0, int(recent_loss_cooldown_minutes)) * 60
    family_window_entries: dict[str, list[dict[str, Any]]] = {family: [] for family in families}
    family_recent_losses: dict[str, list[dict[str, Any]]] = {family: [] for family in families}
    db_path = _current_db_path()

    if not db_path.exists():
        return {
            "available": False,
            "database_path": str(db_path),
            "summary": "local sqlite database is unavailable; family cluster guard is disabled",
            "families": {},
        }

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "select plan_id, symbol, state, valid_from, valid_until, validity from plans where state in ('CLOSED','ENTERED','PARTIAL_EXIT')"
        ).fetchall()
    finally:
        conn.close()

    for plan_id_raw, symbol_raw, state_raw, valid_from_raw, valid_until_raw, validity_raw in rows:
        symbol = str(symbol_raw or "").strip().upper()
        state = str(state_raw or "").strip().upper()
        if not symbol or not isinstance(validity_raw, str):
            continue
        try:
            validity = json.loads(validity_raw) if validity_raw else {}
        except json.JSONDecodeError:
            continue
        if not isinstance(validity, dict):
            continue
        family = str(validity.get("strategy_family") or "").strip().lower()
        if family not in families:
            continue
        if state in {"ENTERED", "PARTIAL_EXIT"}:
            opened_ts = _parse_iso_ts(validity.get("entry_ts")) or _parse_iso_ts(valid_from_raw)
            if opened_ts is not None and opened_ts.timestamp() >= entry_cutoff:
                family_window_entries[family].append(
                    {
                        "plan_id": str(plan_id_raw or ""),
                        "symbol": symbol,
                        "state": state,
                        "opened_ts": opened_ts.isoformat(),
                    }
                )
        if state != "CLOSED":
            continue
        closed_ts = _parse_iso_ts(validity.get("final_exit_ts") or validity.get("last_exit_ts"))
        if closed_ts is None or closed_ts.timestamp() < loss_cutoff:
            continue
        realized_r = _float(validity.get("final_exit_realized_r"), default=0.0)
        if realized_r >= 0.0:
            continue
        family_recent_losses[family].append(
            {
                "plan_id": str(plan_id_raw or ""),
                "symbol": symbol,
                "closed_ts": closed_ts.isoformat(),
                "realized_r": round(realized_r, 4),
                "exit_reason": str(validity.get("final_exit_reason") or ""),
            }
        )

    family_payload: dict[str, Any] = {}
    active_families: list[str] = []
    for family in sorted(families):
        window_entries = sorted(
            family_window_entries.get(family) or [],
            key=lambda item: str(item.get("opened_ts") or ""),
            reverse=True,
        )
        recent_losses = sorted(
            family_recent_losses.get(family) or [],
            key=lambda item: str(item.get("closed_ts") or ""),
            reverse=True,
        )
        cluster_active = len(window_entries) >= max(0, int(max_same_family_entries))
        cooldown_active = len(recent_losses) >= max(0, int(recent_loss_trigger_count))
        if cluster_active or cooldown_active:
            active_families.append(family)
        family_payload[family] = {
            "cluster_window_minutes": int(cluster_window_minutes),
            "max_same_family_entries": int(max_same_family_entries),
            "recent_window_entry_count": len(window_entries),
            "recent_window_entries": window_entries,
            "recent_loss_cooldown_minutes": int(recent_loss_cooldown_minutes),
            "recent_loss_trigger_count": int(recent_loss_trigger_count),
            "recent_loss_count": len(recent_losses),
            "recent_losses": recent_losses,
            "cluster_guard_active": bool(cluster_active),
            "loss_cooldown_active": bool(cooldown_active),
            "active": bool(cluster_active or cooldown_active),
        }

    return {
        "available": True,
        "database_path": str(db_path),
        "families": family_payload,
        "active_families": active_families,
        "summary": (
            " | ".join(
                f"{family}:entries={family_payload[family]['recent_window_entry_count']},losses={family_payload[family]['recent_loss_count']},active={family_payload[family]['active']}"
                for family in sorted(families)
            )
            if family_payload
            else "no family cluster guard snapshot"
        ),
    }


def _decorate_symbol_diversity(
    row: dict[str, Any],
    *,
    diversity_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    item = dict(row or {})
    snapshot = dict(diversity_snapshot or {})
    symbol = str(item.get("symbol") or "").strip().upper()
    counts = dict(snapshot.get("symbol_closed_counts") or {})
    closed_trade_count = int(snapshot.get("closed_trade_count", 0) or 0)
    symbol_closed_count = int(counts.get(symbol, 0) or 0)
    symbol_closed_share = float(symbol_closed_count) / float(closed_trade_count) if closed_trade_count > 0 else 0.0
    overrepresented = symbol in {str(value).upper() for value in list(snapshot.get("overrepresented_symbols") or [])}
    active_open = symbol in {str(value).upper() for value in list(snapshot.get("active_open_symbols") or [])}
    item["symbol_diversity_recent_closed_count"] = symbol_closed_count
    item["symbol_diversity_recent_closed_share"] = round(symbol_closed_share, 4)
    item["symbol_diversity_overrepresented"] = bool(overrepresented)
    item["symbol_diversity_active_open_symbol"] = bool(active_open)
    return item


def _decorate_family_cluster_guard(
    row: dict[str, Any],
    *,
    guard_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    item = dict(row or {})
    snapshot = dict(guard_snapshot or {})
    family = str(item.get("strategy_family") or "").strip().lower()
    family_state = dict((snapshot.get("families") or {}).get(family) or {})
    item["family_cluster_guard_active"] = bool(family_state.get("cluster_guard_active", False))
    item["family_loss_cooldown_active"] = bool(family_state.get("loss_cooldown_active", False))
    item["family_cluster_window_entry_count"] = int(family_state.get("recent_window_entry_count", 0) or 0)
    item["family_recent_loss_count"] = int(family_state.get("recent_loss_count", 0) or 0)
    item["family_cluster_guard_summary"] = family_state
    return item


def _decorate_trend_proof_priority(
    row: dict[str, Any],
    *,
    trend_proof_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    item = dict(row or {})
    snapshot = dict(trend_proof_snapshot or {})
    symbol = str(item.get("symbol") or "").strip().upper()
    family = str(item.get("strategy_family") or "").strip().lower()
    entry_variant = _candidate_entry_variant(item)
    eligible_symbols = {
        str(value or "").strip().upper()
        for value in (snapshot.get("eligible_symbols") or [])
        if str(value or "").strip()
    }
    active = bool(snapshot.get("active", False))
    item["trend_proof_priority_active"] = bool(
        active
        and family == "trend_continuation"
        and entry_variant == "limit"
        and symbol in eligible_symbols
    )
    item["trend_proof_priority_summary"] = snapshot
    return item


def _candidate_entry_variant(row: dict[str, Any] | None) -> str:
    item = dict(row or {})
    entry_model = str(item.get("entry_model") or "").strip().upper()
    if entry_model == "LIMIT":
        return "limit"
    if entry_model == "SWEEP_CONFIRM":
        return "sweep_confirm"
    if entry_model == "CONFIRM":
        return "confirm"
    plan_id = str(item.get("plan_id") or "")
    if "_sweep_confirm" in plan_id:
        return "sweep_confirm"
    if "_confirm" in plan_id:
        return "confirm"
    if "_limit" in plan_id:
        return "limit"
    return "unknown"


def _scanner_candidate_strip_summary(row: dict[str, Any] | None) -> dict[str, str] | None:
    candidate = dict(row or {})
    if not candidate:
        return None
    deployment_state = str(candidate.get("deployment_go_no_go") or "MANUAL_REVIEW").upper()
    approve_value = "approval usable"
    if deployment_state == "NO_GO":
        approve_value = "runtime no_go"
    elif deployment_state == "MANUAL_REVIEW":
        approve_value = "manual review first"
    act_value = "continue_candidate_review_under_portfolio_caps"
    if str(candidate.get("block_reason") or ""):
        act_value = "review_candidate_block_reason"
    return {
        "primary_reason": str(candidate.get("deployment_message") or candidate.get("block_reason_message") or ""),
        "approve_value": approve_value,
        "approve_reason": str(candidate.get("deployment_message") or ""),
        "align_value": "candidate_surface",
        "align_reason": "scanner candidate surface is a runtime context layer",
        "act_value": act_value,
        "act_reason": str(candidate.get("block_reason_message") or candidate.get("deployment_message") or ""),
        "act_priority_level": "watch" if deployment_state == "MANUAL_REVIEW" else "monitor",
    }


def _approval_strip_summary(payload: dict[str, Any] | None) -> dict[str, str] | None:
    approval = dict(payload or {})
    if not approval:
        return None
    approval_state = str(approval.get("approval_state") or "").upper()
    deployment_go_no_go = str(approval.get("deployment_go_no_go") or "MANUAL_REVIEW").upper()
    playbook_go_no_go = str(approval.get("playbook_go_no_go") or deployment_go_no_go).upper()
    deployment_message = str(approval.get("deployment_message") or "").strip()
    playbook_message = str(approval.get("playbook_message") or "").strip()
    approve_value = "approval usable"
    if approval_state == "BLOCKED" or deployment_go_no_go == "NO_GO":
        approve_value = "execution blocked"
    elif approval_state == "APPROVED_MANUAL" or deployment_go_no_go == "MANUAL_REVIEW":
        approve_value = "manual review first"
    elif approval_state == "APPROVED_SHADOW":
        approve_value = "shadow only"
    align_value = "aligned" if deployment_go_no_go == playbook_go_no_go else "playbook_drift"
    priority_map = {
        "BLOCKED": "urgent",
        "APPROVED_MANUAL": "watch",
        "APPROVED_SHADOW": "watch",
        "APPROVED_AUTO": "monitor",
    }
    return {
        "primary_reason": deployment_message or playbook_message,
        "approve_value": approve_value,
        "approve_reason": deployment_message or playbook_message,
        "align_value": align_value,
        "align_reason": playbook_message or deployment_message,
        "act_value": str(approval.get("playbook_action") or "review_execution_gate_before_submit"),
        "act_reason": playbook_message or deployment_message,
        "act_priority_level": priority_map.get(approval_state, "monitor"),
    }


def _edge_experiment_summary(validation_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    source = dict(
        (((validation_payload or {}).get("validation_report") or validation_payload or {}).get("edge_experiment_review_summary") or {})
    )
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


def _top_refresh_block(diag: dict[str, Any] | None) -> tuple[str | None, int]:
    source = dict(diag or {})
    for key in (
        "hard_gate_block_counts",
        "generic_setup_block_counts",
        "router_block_counts",
        "reaction_skip_counts",
        "mode_block_counts",
        "setup_disable_counts",
        "legacy_router_reason_counts",
    ):
        counts = dict(source.get(key) or {})
        if counts:
            first_key = next(iter(counts))
            return str(first_key), int(counts.get(first_key, 0) or 0)
    return None, 0


def _symbol_refresh_summary(indicator_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    refresh = dict((indicator_payload or {}).get("refresh") or {})
    if not refresh:
        return None
    diagnostics = dict(refresh.get("plan_generation_diagnostics") or {})
    top_block_reason, top_block_count = _top_refresh_block(diagnostics)
    summary = {
        "symbol": str(refresh.get("symbol") or (indicator_payload or {}).get("symbol") or "").upper() or None,
        "updated": bool(refresh.get("updated", False)),
        "generated_plan_count": int(refresh.get("plans", 0) or 0),
        "active_signal_plan_count": int(refresh.get("active_signal_plan_count", 0) or 0),
        "active_zone_count": int(refresh.get("active_zone_count", diagnostics.get("active_zone_count", 0)) or 0),
        "regime_label": str(refresh.get("regime_label") or diagnostics.get("regime_profile") or "unknown"),
        "transition_state": str(refresh.get("transition_state") or diagnostics.get("transition_state") or "unknown"),
        "generation_state": str(diagnostics.get("generation_state") or "unknown"),
        "top_block_reason": top_block_reason,
        "top_block_count": int(top_block_count or 0),
        "plan_generation_diagnostics": diagnostics,
    }
    if summary["generated_plan_count"] > 0:
        summary["message"] = (
            f"{summary['symbol'] or 'symbol'} refresh generated {summary['generated_plan_count']} fresh plan(s); "
            f"scanner/portfolio eligibility is the remaining gate."
        )
    elif top_block_reason:
        summary["message"] = (
            f"{summary['symbol'] or 'symbol'} refresh generated 0 fresh plan(s) from {summary['active_zone_count']} active zone(s); "
            f"top block={top_block_reason} x{summary['top_block_count']} "
            f"under {summary['regime_label']}/{summary['transition_state']}."
        )
    else:
        summary["message"] = (
            f"{summary['symbol'] or 'symbol'} refresh generated 0 fresh plan(s) from {summary['active_zone_count']} active zone(s)."
        )
    return summary


def _edge_experiment_summary_line(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "edge_experiment: unavailable"
    posture = dict(summary.get("edge_proof_posture") or {})
    kpis = dict(summary.get("daily_edge_kpis") or {})
    return (
        f"edge_experiment: state={summary.get('edge_state', 'insufficient_edge_measurement')} | "
        f"entry_timing={summary.get('entry_timing_preferred_variant', 'none')} | "
        f"execution_style={summary.get('execution_style_preferred_variant', 'none')} | "
        f"proof={posture.get('state', 'unknown')}/{posture.get('claim_state', 'unknown')} | "
        f"closes={int(kpis.get('closed_trade_count', 0) or 0)}/{int(summary.get('edge_proof_goal_closed_trades', 0) or 0)} | "
        f"remaining={int(summary.get('remaining_closed_trades_to_edge_proof_goal', 0) or 0)} | "
        f"regime={kpis.get('regime_dependency_state', 'not_available')} | "
        f"true_edge={float(kpis.get('true_edge_ratio', summary.get('true_edge_ratio')) or 0.0):.4f} | "
        f"decay={float(kpis.get('edge_decay_rate', summary.get('edge_decay_rate')) or 0.0):.4f}"
    )


def _edge_experiment_next_step(summary: dict[str, Any] | None) -> str | None:
    if not summary:
        return None
    posture = dict(summary.get("edge_proof_posture") or {})
    kpis = dict(summary.get("daily_edge_kpis") or {})
    proof_state = str(posture.get("state") or "unknown")
    proof_goal = max(int(summary.get("edge_proof_goal_closed_trades", 0) or 0), 0)
    remaining = max(int(summary.get("remaining_closed_trades_to_edge_proof_goal", 0) or 0), 0)
    if proof_state == "sample_building":
        return (
            "Advisory only: PAPER lineage is still in sample-building mode; treat split preferences as directional "
            f"while {remaining} closed trades remain to the {proof_goal}-close proof goal."
        )
    if proof_state == "regime_limited":
        return (
            "Advisory only: the edge proof goal is met, but regime dependency is still active; keep PAPER lineage "
            "running before treating the preferred branch as portable."
        )
    if proof_state == "proof_goal_met_but_edge_weak":
        return (
            "Advisory only: the proof goal is met, but current true-edge/decay still looks weak; keep PAPER-only "
            "until the edge stabilizes."
        )
    edge_state = str(summary.get("edge_state") or "")
    entry_timing = str(summary.get("entry_timing_preferred_variant") or "none")
    execution_style = str(summary.get("execution_style_preferred_variant") or "none")
    if edge_state == "fragile_edge":
        return (
            "Advisory only: fragile post-cost edge; keep PAPER lineage running but queue a controlled split review "
            f"for entry_timing={entry_timing} and execution_style={execution_style}."
        )
    if edge_state == "watch_edge":
        return (
            "Advisory only: unstable post-cost edge; compare PAPER outcomes against "
            f"entry_timing={entry_timing} and execution_style={execution_style} before changing the entry design."
        )
    if edge_state == "insufficient_edge_measurement":
        return "Advisory only: keep collecting closed PAPER samples before promoting edge experiment conclusions."
    return None


def _candidate_edge_experiment_focus(
    candidate: dict[str, Any] | None,
    edge_experiment_review: dict[str, Any] | None,
) -> dict[str, Any] | None:
    item = dict(candidate or {})
    if not item:
        return None
    row_focus = dict(item.get("edge_experiment_focus") or {})
    source = row_focus or dict(edge_experiment_review or {})
    if not source:
        return None
    return {
        "symbol": str(item.get("symbol") or ""),
        "strategy_family": str(item.get("strategy_family") or ""),
        "block_reason": str(item.get("block_reason") or ""),
        "edge_state": str(source.get("edge_state") or "insufficient_edge_measurement"),
        "entry_timing_preferred_variant": str(source.get("entry_timing_preferred_variant") or "none"),
        "execution_style_preferred_variant": str(source.get("execution_style_preferred_variant") or "none"),
        "true_edge_ratio": round(_float(source.get("true_edge_ratio")), 4),
        "focus_source": "row_level" if row_focus else "top_level_fallback",
    }


def _candidate_edge_experiment_focus_line(payload: dict[str, Any] | None) -> str:
    focus = dict(payload or {})
    if not focus:
        return "candidate_edge_focus: unavailable"
    line = (
        f"candidate_edge_focus: {focus.get('symbol') or 'unknown'} | "
        f"family={focus.get('strategy_family') or 'unknown'} | "
        f"edge={focus.get('edge_state') or 'insufficient_edge_measurement'} | "
        f"split={(focus.get('entry_timing_preferred_variant') or 'none')}/{(focus.get('execution_style_preferred_variant') or 'none')}"
    )
    if focus.get("block_reason"):
        line = f"{line} | reason={focus.get('block_reason')}"
    line = f"{line} | source={focus.get('focus_source') or 'unknown'}"
    return line


def _is_allowed_runtime_state(row: dict[str, Any], include_manual: bool) -> bool:
    state = str(row.get("deployment_go_no_go") or "").upper()
    if state == "GO":
        return True
    return include_manual and state == "MANUAL_REVIEW"


def _runtime_state_allows_override(row: dict[str, Any], include_manual: bool) -> bool:
    state = str(row.get("deployment_go_no_go") or "").upper()
    if not state:
        return True
    return _is_allowed_runtime_state(row, include_manual)


def _strategy_grade(row: dict[str, Any]) -> str:
    validity = dict(row.get("validity") or {})
    strategy_sizing = dict(row.get("strategy_sizing") or {})
    return str(
        row.get("strategy_grade")
        or validity.get("strategy_grade")
        or strategy_sizing.get("strategy_grade")
        or row.get("setup_grade")
        or ""
    ).upper()


def _rank_candidates(
    rows: list[dict[str, Any]],
    *,
    symbol: str | None,
    families: set[str],
    include_manual: bool,
    diversity_snapshot: dict[str, Any] | None = None,
    family_guard_snapshot: dict[str, Any] | None = None,
    trend_proof_snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for row in rows:
        family = str(row.get("strategy_family") or "").lower()
        if family not in families:
            continue
        if symbol and str(row.get("symbol") or "").upper() != symbol.upper():
            continue
        if not _is_allowed_runtime_state(row, include_manual):
            continue
        if float(row.get("recommended_risk_r") or 0.0) <= 0.0:
            continue
        item = _decorate_symbol_diversity(row, diversity_snapshot=diversity_snapshot)
        item = _decorate_family_cluster_guard(item, guard_snapshot=family_guard_snapshot)
        item = _decorate_trend_proof_priority(item, trend_proof_snapshot=trend_proof_snapshot)
        item["entry_variant_preference"] = _candidate_entry_variant(item)
        if bool(item.get("family_cluster_guard_active")) or bool(item.get("family_loss_cooldown_active")):
            continue
        filtered.append(item)
    if not filtered:
        return None
    filtered.sort(
        key=lambda row: (
            not bool(row.get("trend_proof_priority_active")),
            bool(row.get("symbol_diversity_active_open_symbol")),
            bool(row.get("symbol_diversity_overrepresented")),
            int(_ENTRY_VARIANT_PREFERENCE.get(str(row.get("entry_variant_preference") or "unknown"), 3)),
            -float(row.get("expected_ev_at_recommended_size_r") or 0.0),
            -float(row.get("expected_ev_r") or 0.0),
            int(row.get("symbol_diversity_recent_closed_count") or 0),
            -float(row.get("recommended_risk_r") or 0.0),
        )
    )
    return filtered


def _choose_candidate(
    rows: list[dict[str, Any]],
    *,
    symbol: str | None,
    families: set[str],
    include_manual: bool,
    diversity_snapshot: dict[str, Any] | None = None,
    family_guard_snapshot: dict[str, Any] | None = None,
    trend_proof_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    ranked = _rank_candidates(
        rows,
        symbol=symbol,
        families=families,
        include_manual=include_manual,
        diversity_snapshot=diversity_snapshot,
        family_guard_snapshot=family_guard_snapshot,
        trend_proof_snapshot=trend_proof_snapshot,
    )
    if not ranked:
        return None
    return ranked[0]


def _trend_proof_candidate_summary(
    *,
    scanner_rows: list[dict[str, Any]],
    portfolio_payload: dict[str, Any] | None,
    include_manual: bool,
    diversity_snapshot: dict[str, Any] | None,
    family_guard_snapshot: dict[str, Any] | None,
    trend_proof_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot = dict(trend_proof_snapshot or {})
    if not bool(snapshot.get("available", False)):
        return {
            "available": False,
            "active": False,
            "availability_state": "not_requested",
            "summary": str(snapshot.get("summary") or "trend proof is not active for this drill pass"),
        }

    eligible_symbols = {
        str(item or "").strip().upper()
        for item in list(snapshot.get("eligible_symbols") or [])
        if str(item or "").strip()
    }
    scanner_matches = [
        dict(row)
        for row in scanner_rows
        if str(row.get("symbol") or "").strip().upper() in eligible_symbols
        and str(row.get("strategy_family") or "").strip().lower() == "trend_continuation"
    ]
    scanner_limit_matches = [row for row in scanner_matches if _candidate_entry_variant(row) == "limit"]
    ranked = _rank_candidates(
        scanner_rows,
        symbol=None,
        families={"trend_continuation"},
        include_manual=include_manual,
        diversity_snapshot=diversity_snapshot,
        family_guard_snapshot=family_guard_snapshot,
        trend_proof_snapshot=trend_proof_snapshot,
    ) or []

    portfolio = dict(portfolio_payload or {})
    portfolio_rows: list[dict[str, Any]] = []
    for key in ("accepted_candidates", "blocked_candidates", "alpha_research_candidates"):
        value = portfolio.get(key)
        if isinstance(value, list):
            portfolio_rows.extend(dict(item) for item in value if isinstance(item, dict))
    portfolio_matches = [
        row
        for row in portfolio_rows
        if str(row.get("symbol") or "").strip().upper() in eligible_symbols
        and str(row.get("strategy_family") or "").strip().lower() == "trend_continuation"
    ]
    blocked_reason_counts = Counter(
        str(row.get("block_reason") or "unknown")
        for row in portfolio_matches
        if str(row.get("block_reason") or "").strip()
    )

    if not scanner_matches and not portfolio_matches:
        state = "no_trend_surface_candidate_visible"
        summary = "BTC/ETH trend_continuation candidates are not visible on the current scanner or portfolio surface."
    elif scanner_matches and not scanner_limit_matches:
        state = "trend_surface_visible_but_not_limit"
        summary = "BTC/ETH trend_continuation candidates are visible, but none are LIMIT variants yet."
    elif scanner_limit_matches and not ranked:
        state = "trend_limit_visible_but_not_runtime_eligible"
        summary = "BTC/ETH trend_continuation LIMIT candidates are visible, but none currently pass runtime eligibility."
    else:
        state = "trend_limit_candidate_ready"
        top = dict(ranked[0] or {}) if ranked else {}
        summary = (
            f"BTC/ETH trend_continuation LIMIT candidate is visible: "
            f"{top.get('symbol') or 'unknown'} / {top.get('plan_id') or 'unknown'}."
        )

    if blocked_reason_counts:
        summary = (
            f"{summary} Blocked reasons: "
            + ", ".join(f"{reason}={count}" for reason, count in blocked_reason_counts.most_common(3))
            + "."
        )

    top_ranked = dict(ranked[0] or {}) if ranked else {}
    return {
        "available": True,
        "active": bool(snapshot.get("active", False)),
        "availability_state": state,
        "eligible_symbols": sorted(eligible_symbols),
        "scanner_candidate_count": len(scanner_matches),
        "scanner_limit_candidate_count": len(scanner_limit_matches),
        "portfolio_candidate_count": len(portfolio_matches),
        "runtime_eligible_candidate_count": len(ranked),
        "blocked_reason_counts": dict(blocked_reason_counts),
        "top_runtime_candidate_symbol": str(top_ranked.get("symbol") or ""),
        "top_runtime_candidate_plan_id": str(top_ranked.get("plan_id") or ""),
        "summary": summary,
    }


def _portfolio_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("accepted_candidates", "blocked_candidates"):
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    return rows


def _top_family_counts(rows: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    counts = Counter(str(row.get("strategy_family") or "unknown") for row in rows if isinstance(row, dict))
    return [{"family": family, "count": count} for family, count in counts.most_common(limit)]


def _match_family_rows(rows: list[dict[str, Any]], families: set[str]) -> list[dict[str, Any]]:
    return [row for row in rows if str(row.get("strategy_family") or "").lower() in families]


def _family_availability_summary(
    *,
    scanner_rows: list[dict[str, Any]],
    portfolio_payload: dict[str, Any] | None,
    families: set[str],
) -> dict[str, Any]:
    portfolio = dict(portfolio_payload or {})
    accepted_rows = [dict(row) for row in (portfolio.get("accepted_candidates") or []) if isinstance(row, dict)]
    blocked_rows = [dict(row) for row in (portfolio.get("blocked_candidates") or []) if isinstance(row, dict)]
    alpha_rows = [dict(row) for row in (portfolio.get("alpha_research_candidates") or []) if isinstance(row, dict)]

    scanner_matches = _match_family_rows(scanner_rows, families)
    accepted_matches = _match_family_rows(accepted_rows, families)
    blocked_matches = _match_family_rows(blocked_rows, families)
    alpha_matches = _match_family_rows(alpha_rows, families)
    portfolio_match_count = len(accepted_matches) + len(blocked_matches) + len(alpha_matches)

    dominant_scanner = (_top_family_counts(scanner_rows, limit=1) or [{}])[0]
    dominant_blocked = (_top_family_counts(blocked_rows, limit=1) or [{}])[0]

    if len(scanner_rows) == 0 and portfolio_match_count == 0:
        availability_state = "scanner_surface_empty"
        summary = "Scanner returned zero rows for the current universe snapshot."
    elif len(scanner_matches) == 0 and portfolio_match_count == 0:
        availability_state = "requested_families_absent"
        summary = (
            f"No requested family candidate is present on the current surface; "
            f"scanner is dominated by `{dominant_scanner.get('family', 'unknown')}` "
            f"({int(dominant_scanner.get('count', 0) or 0)})."
        )
    else:
        availability_state = "requested_families_present_but_ineligible"
        summary = (
            f"Requested families are present but not currently eligible; "
            f"scanner_matches={len(scanner_matches)} portfolio_matches={portfolio_match_count}."
        )

    if dominant_blocked:
        summary = (
            f"{summary} Top blocked portfolio family is "
            f"`{dominant_blocked.get('family', 'unknown')}` "
            f"({int(dominant_blocked.get('count', 0) or 0)})."
        )

    return {
        "requested_families": sorted(families),
        "availability_state": availability_state,
        "summary": summary,
        "scanner_surface_count": len(scanner_rows),
        "scanner_match_count": len(scanner_matches),
        "portfolio_match_count": portfolio_match_count,
        "accepted_match_count": len(accepted_matches),
        "blocked_match_count": len(blocked_matches),
        "alpha_match_count": len(alpha_matches),
        "scanner_top_families": _top_family_counts(scanner_rows),
        "blocked_top_families": _top_family_counts(blocked_rows),
        "alpha_top_families": _top_family_counts(alpha_rows),
    }


def _rank_override_candidates(
    rows: list[dict[str, Any]],
    *,
    symbol: str | None,
    families: set[str],
    include_manual: bool,
    diversity_snapshot: dict[str, Any] | None = None,
    family_guard_snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    eligible_blocks = {"thesis_duplicate_blocked", "thesis_active_cap_reached"}
    filtered: list[dict[str, Any]] = []
    for row in rows:
        family = str(row.get("strategy_family") or "").lower()
        if family not in families:
            continue
        if symbol and str(row.get("symbol") or "").upper() != symbol.upper():
            continue
        if not _runtime_state_allows_override(row, include_manual):
            continue
        if _strategy_grade(row) != "A":
            continue
        if str(row.get("block_reason") or "") not in eligible_blocks:
            continue
        item = _decorate_symbol_diversity(row, diversity_snapshot=diversity_snapshot)
        item = _decorate_family_cluster_guard(item, guard_snapshot=family_guard_snapshot)
        item["entry_variant_preference"] = _candidate_entry_variant(item)
        if bool(item.get("family_cluster_guard_active")) or bool(item.get("family_loss_cooldown_active")):
            continue
        filtered.append(item)
    if not filtered:
        return None
    filtered.sort(
        key=lambda row: (
            bool(row.get("symbol_diversity_active_open_symbol")),
            bool(row.get("symbol_diversity_overrepresented")),
            int(_ENTRY_VARIANT_PREFERENCE.get(str(row.get("entry_variant_preference") or "unknown"), 3)),
            -float(row.get("expected_ev_r") or 0.0),
            -float(row.get("expected_ev_at_recommended_size_r") or 0.0),
            -float(row.get("final_rank_score") or 0.0),
            int(row.get("symbol_diversity_recent_closed_count") or 0),
            -float(row.get("recommended_risk_r") or 0.0),
        )
    )
    return filtered


def _choose_override_candidate(
    rows: list[dict[str, Any]],
    *,
    symbol: str | None,
    families: set[str],
    include_manual: bool,
    diversity_snapshot: dict[str, Any] | None = None,
    family_guard_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    ranked = _rank_override_candidates(
        rows,
        symbol=symbol,
        families=families,
        include_manual=include_manual,
        diversity_snapshot=diversity_snapshot,
        family_guard_snapshot=family_guard_snapshot,
    )
    if not ranked:
        return None
    return ranked[0]


def _skip_existing_sample_submit_block(intent: dict[str, Any] | None) -> bool:
    payload = dict(intent or {})
    submit_decision = str(payload.get("submit_decision") or "").strip().upper()
    reason_code = str(payload.get("decision_reason_code") or "").strip().lower()
    reason_message = str(payload.get("decision_reason_message") or "").strip().lower()
    if submit_decision == "SUBMIT":
        return False
    return (
        "duplicate_active_thesis" in reason_code
        or "plan_reentry_blocked" in reason_code
        or "skip_already_submitted" in submit_decision.lower()
        or "plan already has routed submission" in reason_message
        or "skip_existing_active_plan" in reason_code
        or "duplicate thesis detected against active plan" in reason_message
    )


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# PAPER Candidate Drill")
    lines.append("")
    lines.append(f"- generated_at: {payload['generated_at']}")
    lines.append(f"- overall_status: {payload['overall_status']}")
    lines.append(f"- summary: {payload['summary_line']}")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    for row in payload["checks"]:
        lines.append(f"- [{row['status']}] {row['name']}: {row['message']}")
    lines.append("")
    lines.append("## Approval Strip")
    lines.append("")
    approval_strip = payload.get("approval_strip_summary") or {}
    if approval_strip:
        lines.append(
            f"- approve={approval_strip.get('approve_value')} | "
            f"align={approval_strip.get('align_value')} | "
            f"act={approval_strip.get('act_value')} | "
            f"priority={approval_strip.get('act_priority_level')}"
        )
        lines.append(f"- reason: {approval_strip.get('primary_reason') or approval_strip.get('approve_reason')}")
    else:
        lines.append("- approval strip unavailable")
    lines.append("")
    lines.append("## Symbol Diversity")
    lines.append("")
    diversity = payload.get("symbol_diversity_summary") or {}
    if diversity:
        lines.append(
            f"- closed={int(diversity.get('closed_trade_count', 0) or 0)} | "
            f"overrepresented={','.join(diversity.get('overrepresented_symbols') or []) or 'none'} | "
            f"active_open={','.join(diversity.get('active_open_symbols') or []) or 'none'}"
        )
    else:
        lines.append("- symbol diversity summary unavailable")
    lines.append("")
    lines.append("## Family Cluster Guard")
    lines.append("")
    family_guard = payload.get("family_cluster_guard_summary") or {}
    if family_guard:
        lines.append(f"- {family_guard.get('summary') or 'family cluster guard summary unavailable'}")
    else:
        lines.append("- family cluster guard summary unavailable")
    lines.append("")
    lines.append("## Edge Experiment")
    lines.append("")
    edge_experiment = payload.get("edge_experiment_review") or {}
    if edge_experiment:
        lines.append(f"- {_edge_experiment_summary_line(edge_experiment)}")
        lines.append(f"- summary: {edge_experiment.get('summary', '')}")
    else:
        lines.append("- edge experiment unavailable")
    lines.append(f"- {_candidate_edge_experiment_focus_line(payload.get('candidate_edge_experiment_focus'))}")
    lines.append("")
    lines.append("## Candidate")
    lines.append("")
    candidate = payload.get("candidate") or {}
    if candidate:
        lines.append(f"- symbol: {candidate.get('symbol', '')}")
        lines.append(f"- plan_id: {candidate.get('plan_id', '')}")
        lines.append(f"- family: {candidate.get('strategy_family', '')}")
        lines.append(f"- candidate_surface: {candidate.get('deployment_go_no_go', '') or candidate.get('operator_status', '')}")
        lines.append(f"- expected_summary: {candidate.get('expected_summary', '')}")
    else:
        lines.append("- no eligible candidate found")
    family_availability = payload.get("family_availability_summary") or {}
    if family_availability:
        lines.append(f"- family_availability: {family_availability.get('availability_state', 'unknown')}")
        lines.append(f"- family_summary: {family_availability.get('summary', '')}")
    trend_proof = payload.get("trend_proof_candidate_summary") or {}
    if trend_proof:
        lines.append(f"- trend_proof_availability: {trend_proof.get('availability_state', 'unknown')}")
        lines.append(f"- trend_proof_summary: {trend_proof.get('summary', '')}")
    lines.append("")
    lines.append("## Next Steps")
    lines.append("")
    for step in payload.get("next_steps", []):
        lines.append(f"- {step}")
    lines.append("")
    lines.append("## Raw Payload")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    lines.append("```")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    generated_at = _now()
    families = _family_set(args.families)
    diversity_snapshot = _load_symbol_diversity_snapshot(
        families=families,
        min_cohort_trades=int(getattr(args, "symbol_diversity_min_cohort_trades", _SYMBOL_DIVERSITY_MIN_COHORT_TRADES) or 0),
        soft_cap_count=int(getattr(args, "symbol_diversity_soft_cap_count", _SYMBOL_DIVERSITY_SOFT_CAP_COUNT) or 0),
        soft_cap_share=float(getattr(args, "symbol_diversity_soft_cap_share", _SYMBOL_DIVERSITY_SOFT_CAP_SHARE) or 0.0),
    )
    family_guard_snapshot = _load_family_cluster_guard_snapshot(families=families)
    trend_proof_snapshot = _load_trend_proof_priority_snapshot(families=families)

    sync_payload: dict[str, Any] | None = None
    if not args.skip_sync:
        sync_payload = _request_json(
            args.base_url,
            "POST",
            "/internal/binance/sync-universe",
            query={
                "limit_symbols": args.limit_symbols,
                "symbol_concurrency": args.symbol_concurrency,
                "limit_1m": args.limit_1m,
                "limit_5m": args.limit_5m,
                "limit_15m": args.limit_15m,
            },
        )

    scanner = _request_json(
        args.base_url,
        "GET",
        "/scanner/top",
        query={"universe": args.universe, "limit": args.candidate_limit},
    )
    scanner_rows = scanner if isinstance(scanner, list) else []
    candidate_pool = _rank_candidates(
        scanner_rows,
        symbol=args.symbol,
        families=families,
        include_manual=args.include_manual_review,
        diversity_snapshot=None if args.symbol else diversity_snapshot,
        family_guard_snapshot=family_guard_snapshot,
        trend_proof_snapshot=trend_proof_snapshot,
    )
    candidate = candidate_pool[0] if candidate_pool else None
    portfolio_payload: dict[str, Any] | None = None
    if candidate is None and args.paper_lineage_override:
        portfolio_raw = _request_json(
            args.base_url,
            "GET",
            "/portfolio/budget",
            query={"universe": args.universe, "limit": args.candidate_limit, "write_report": "false"},
        )
        portfolio_payload = portfolio_raw if isinstance(portfolio_raw, dict) else {}
        candidate_pool = _rank_override_candidates(
            _portfolio_candidates(portfolio_payload),
            symbol=args.symbol,
            families=families,
            include_manual=args.include_manual_review,
            diversity_snapshot=None if args.symbol else diversity_snapshot,
            family_guard_snapshot=family_guard_snapshot,
        )
        candidate = candidate_pool[0] if candidate_pool else None
    elif candidate is None:
        portfolio_raw = _request_json(
            args.base_url,
            "GET",
            "/portfolio/budget",
            query={"universe": args.universe, "limit": args.candidate_limit, "write_report": "false"},
        )
        portfolio_payload = portfolio_raw if isinstance(portfolio_raw, dict) else {}
    trend_proof_candidate_summary = _trend_proof_candidate_summary(
        scanner_rows=scanner_rows,
        portfolio_payload=portfolio_payload,
        include_manual=args.include_manual_review,
        diversity_snapshot=None if args.symbol else diversity_snapshot,
        family_guard_snapshot=family_guard_snapshot,
        trend_proof_snapshot=trend_proof_snapshot,
    )

    preview: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
    intent: dict[str, Any] | None = None
    submission: dict[str, Any] | None = None
    validation_context: dict[str, Any] | None = None
    edge_experiment_review: dict[str, Any] | None = None
    symbol_refresh_summary: dict[str, Any] | None = None
    skipped_active_duplicate_candidates: list[dict[str, str]] = []
    if candidate is not None:
        for candidate_option in candidate_pool:
            validation_context = _request_json(
                args.base_url,
                "POST",
                "/validation/report",
                query={"symbol": str(candidate_option["symbol"])},
            )
            edge_experiment_review = _edge_experiment_summary(validation_context)
            preview_body = {
                "plan_id": candidate_option["plan_id"],
                "paper_lineage_override": bool(args.paper_lineage_override),
            }
            preview = _request_json(
                args.base_url,
                "POST",
                "/execution/plans/preview",
                body=preview_body,
            )
            approval = _request_json(
                args.base_url,
                "POST",
                "/execution/approve-plan",
                body=preview_body,
            )
            intent = _request_json(
                args.base_url,
                "POST",
                "/execution/order-intents",
                body={
                    "plan_id": candidate_option["plan_id"],
                    "execution_mode": "PAPER",
                    "paper_lineage_override": bool(args.paper_lineage_override),
                },
            )
            candidate = candidate_option
            if args.submit_paper and _skip_existing_sample_submit_block(intent):
                skipped_active_duplicate_candidates.append(
                    {
                        "symbol": str(candidate_option.get("symbol") or ""),
                        "plan_id": str(candidate_option.get("plan_id") or ""),
                        "reason_code": str(intent.get("decision_reason_code") or ""),
                    }
                )
                continue
            if args.submit_paper and str(intent.get("submit_decision") or "") == "SUBMIT":
                submission = _request_json(
                    args.base_url,
                    "POST",
                    "/execution/submit",
                    body={
                        "intent_id": intent["intent_id"],
                        "live": False,
                        "paper_scenario": args.paper_scenario,
                    },
                )
            break
    elif args.symbol:
        indicator_payload = _request_json(
            args.base_url,
            "GET",
            "/indicators/summary",
            query={"symbol": str(args.symbol), "refresh": "true", "plan_limit": 3, "zone_limit": 5},
        )
        if isinstance(indicator_payload, dict):
            symbol_refresh_summary = _symbol_refresh_summary(indicator_payload)
    candidate_edge_experiment_focus = _candidate_edge_experiment_focus(candidate, edge_experiment_review)
    candidate_surface_summary = _scanner_candidate_strip_summary(candidate)
    approval_strip_summary = _approval_strip_summary(approval) or candidate_surface_summary
    family_availability_summary = _family_availability_summary(
        scanner_rows=scanner_rows,
        portfolio_payload=portfolio_payload,
        families=families,
    )

    checks: list[dict[str, str]] = []
    if sync_payload is not None:
        checks.append(
            {
                "name": "universe_sync",
                "status": _status(int(sync_payload.get("success", 0) or 0) > 0 or int(sync_payload.get("processed_symbols", 0) or 0) > 0),
                "message": f"success={sync_payload.get('success', 0)} failed={sync_payload.get('failed', 0)} processed={sync_payload.get('processed_symbols', 0)}",
            }
        )
    checks.append(
        {
            "name": "eligible_candidate_found",
            "status": _status(candidate is not None),
            "message": (
                (
                    "No eligible trend_continuation/sweep_reversal candidate found in scanner output."
                    + (
                        f" {symbol_refresh_summary.get('message', '')}"
                        if symbol_refresh_summary and str(symbol_refresh_summary.get("message") or "")
                        else ""
                    )
                )
                if candidate is None
                else (
                    f"{candidate.get('symbol')} {candidate.get('strategy_family')} "
                    f"approve={(candidate_surface_summary or {}).get('approve_value', candidate.get('deployment_go_no_go', ''))} | "
                    f"act={(candidate_surface_summary or {}).get('act_value', 'continue_candidate_review_under_portfolio_caps')}"
                    + (
                        " via paper lineage override"
                        if bool(args.paper_lineage_override)
                        and str(candidate.get("block_reason") or "") in {"thesis_duplicate_blocked", "thesis_active_cap_reached"}
                        else ""
                    )
                )
            ),
        }
    )
    if candidate is not None:
        checks.append(
            {
                "name": "preview_ready",
                "status": _status(preview is not None),
                "message": f"entry_type={preview.get('entry_type', '')} semantics={preview.get('entry_semantics', '')}" if preview else "preview unavailable",
            }
        )
        approval_state = str((approval or {}).get("approval_state") or "")
        allowed_execution_mode = str((approval or {}).get("allowed_execution_mode") or "")
        checks.append(
            {
                "name": "approval_for_paper",
                "status": _status(approval_state in {"APPROVED_AUTO", "APPROVED_MANUAL"} and allowed_execution_mode in {"PAPER", "MICRO_LIVE", "LIVE"}),
                "message": (
                    f"approve={(approval_strip_summary or {}).get('approve_value', approval_state)} | "
                    f"align={(approval_strip_summary or {}).get('align_value', 'aligned')} | "
                    f"act={(approval_strip_summary or {}).get('act_value', '')} | "
                    f"approval_state={approval_state} allowed_execution_mode={allowed_execution_mode}"
                    + (
                        f" override={approval.get('paper_lineage_override_reason', '')}"
                        if approval and approval.get("paper_lineage_override_applied")
                        else ""
                    )
                ),
            }
        )
        submit_decision = str((intent or {}).get("submit_decision") or "")
        checks.append(
            {
                "name": "intent_submit_ready",
                "status": _status(submit_decision == "SUBMIT"),
                "message": f"submit_decision={submit_decision or 'unknown'} reason={(intent or {}).get('decision_reason_code', '')}",
            }
        )
        if args.submit_paper:
            checks.append(
                {
                    "name": "paper_submit",
                    "status": _status(submission is not None and str(submission.get('submit_status') or "") in {"FILLED", "ACKNOWLEDGED", "PARTIALLY_FILLED"}),
                    "message": (
                        "paper submit not attempted"
                        if submission is None
                        else f"submit_status={submission.get('submit_status', '')} state={submission.get('state', '')}"
                    ),
                }
            )

    fail_count = sum(1 for row in checks if row["status"] == "FAIL")
    overall_status = "READY_FOR_PAPER_SAMPLE" if fail_count == 0 else "NOT_READY"

    next_steps: list[str] = []
    if candidate is None:
        next_steps.append("Wait for London/New York session and rerun this helper until an eligible family candidate appears.")
        next_steps.append("Keep focus on trend_continuation or sweep_reversal families; legacy_zone_plan does not advance MICRO_LIVE lineage.")
        active_families = list((family_guard_snapshot.get("active_families") or [])) if isinstance(family_guard_snapshot, dict) else []
        if active_families:
            next_steps.append(
                f"PAPER lineage family guard is active for {', '.join(active_families)}; wait for same-window cluster/loss cooldown to clear before adding more samples."
            )
        if family_availability_summary.get("availability_state") == "scanner_surface_empty":
            next_steps.append("Scanner returned zero rows for this universe snapshot; treat this as a surface-empty wait and recheck the next session window.")
        elif family_availability_summary.get("availability_state") == "requested_families_absent":
            next_steps.append("Requested PAPER lineage families are absent from both scanner and portfolio surfaces; this is a market-availability wait, not an approval blockage.")
        else:
            next_steps.append("Requested PAPER lineage families are present but not eligible; inspect portfolio block reasons before widening scope.")
        if bool(trend_proof_candidate_summary.get("available", False)) and str(
            trend_proof_candidate_summary.get("availability_state") or ""
        ) != "trend_limit_candidate_ready":
            next_steps.append(str(trend_proof_candidate_summary.get("summary") or "Trend proof candidate is still not ready."))
        if symbol_refresh_summary and str(symbol_refresh_summary.get("message") or ""):
            next_steps.append(str(symbol_refresh_summary["message"]))
    else:
        if bool(diversity_snapshot.get("available", False)) and (
            bool(candidate.get("symbol_diversity_active_open_symbol"))
            or bool(candidate.get("symbol_diversity_overrepresented"))
        ):
            next_steps.append(
                "Selected candidate still carries symbol concentration pressure because no cleaner family alternative was eligible in this pass."
            )
        if intent is not None and str(intent.get("submit_decision") or "") != "SUBMIT":
            next_steps.append(f"Candidate found but PAPER intent is not submit-ready: {(intent or {}).get('decision_reason_message', '')}")
        elif not args.submit_paper:
            next_steps.append("Rerun with --submit-paper to create a PAPER submission once the candidate looks acceptable.")
        elif submission is not None:
            next_steps.append("Monitor execution/operator-dashboard and validation/report after the PAPER submission closes.")
            next_steps.append("Repeat this drill until enough closed v2 trades exist to resolve threshold lineage winner.")
        if skipped_active_duplicate_candidates:
            skipped_symbols = ", ".join(
                f"{item.get('symbol') or 'unknown'}[{item.get('reason_code') or 'duplicate'}]"
                for item in skipped_active_duplicate_candidates
            )
            next_steps.append(f"Skipped active-sample duplicates while searching for a new PAPER lineage candidate: {skipped_symbols}.")
    advisory_next_step = _edge_experiment_next_step(edge_experiment_review)
    if advisory_next_step:
        next_steps.append(advisory_next_step)
    if submission is None and args.submit_paper:
        next_steps.append("No PAPER submission occurred in this run.")

    payload = {
        "generated_at": generated_at.isoformat(),
        "symbol": (args.symbol or "").upper() or None,
        "universe": args.universe,
        "families": sorted(families),
        "symbol_diversity_summary": diversity_snapshot,
        "family_cluster_guard_summary": family_guard_snapshot,
        "trend_proof_priority_summary": trend_proof_snapshot,
        "trend_proof_candidate_summary": trend_proof_candidate_summary,
        "paper_lineage_override": bool(args.paper_lineage_override),
        "overall_status": overall_status,
        "summary_line": (
            "Eligible PAPER candidate is ready."
            if overall_status == "READY_FOR_PAPER_SAMPLE"
            else f"{fail_count} blocking drill check(s) remain."
        ),
        "checks": checks,
        "sync": sync_payload,
        "portfolio": portfolio_payload,
        "candidate": candidate,
        "candidate_surface_summary": candidate_surface_summary,
        "family_availability_summary": family_availability_summary,
        "symbol_refresh_summary": symbol_refresh_summary,
        "validation_context": validation_context,
        "preview": preview,
        "approval": approval,
        "approval_strip_summary": approval_strip_summary,
        "edge_experiment_review": edge_experiment_review,
        "candidate_edge_experiment_focus": candidate_edge_experiment_focus,
        "intent": intent,
        "submission": submission,
        "next_steps": next_steps,
    }

    if not args.no_write_report:
        ts = generated_at.strftime("%Y%m%dT%H%M%SZ")
        symbol_tag = (candidate or {}).get("symbol") or (args.symbol or "UNIVERSE").upper()
        report_path = ROOT_DIR / args.report_dir / f"paper_candidate_drill_{symbol_tag}_{ts}.md"
        _write_report(report_path, payload)
        payload["report_path"] = str(report_path.relative_to(ROOT_DIR))

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))
    return 0 if overall_status == "READY_FOR_PAPER_SAMPLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
