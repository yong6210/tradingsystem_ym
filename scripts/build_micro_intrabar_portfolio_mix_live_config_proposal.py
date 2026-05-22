#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text


DEFAULT_PORTFOLIO_MIX_REVIEW = (
    ROOT_DIR / "reports/operations/micro_intrabar_long_short_portfolio_mix_review_drop_arb/latest.json"
)
DEFAULT_LONG_CONTRACT = ROOT_DIR / "reports/operations/micro_intrabar_paper_candidate_contract/latest.json"
DEFAULT_SHORT_CONTRACT = ROOT_DIR / "reports/operations/micro_intrabar_short_paper_candidate_contract_drop_arb/latest.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a no-live-authority config proposal for the micro intrabar portfolio mix candidate."
    )
    parser.add_argument("--portfolio-mix-review-path", default=str(DEFAULT_PORTFOLIO_MIX_REVIEW))
    parser.add_argument("--contract-path", action="append", default=[])
    parser.add_argument(
        "--allow-contract-subset",
        action="store_true",
        help="Allow an intentional subset of the portfolio-mix symbols, for example a long-only paper promotion candidate.",
    )
    parser.add_argument("--report-dir", default="reports/operations/micro_intrabar_portfolio_mix_live_config_proposal")
    parser.add_argument("--write-report", action="store_true")
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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


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


def _csv_paths(values: list[str]) -> list[Path]:
    raw_values = values or [str(DEFAULT_LONG_CONTRACT), str(DEFAULT_SHORT_CONTRACT)]
    paths: list[Path] = []
    seen: set[Path] = set()
    for item in raw_values:
        for raw in str(item or "").split(","):
            if not raw.strip():
                continue
            path = _resolve_path(raw.strip())
            if path in seen:
                continue
            seen.add(path)
            paths.append(path)
    return paths


def _paper_contract(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload.get("paper_contract") or {})


def _direction_contract(contracts: list[dict[str, Any]]) -> tuple[dict[str, str], list[str]]:
    directions: dict[str, str] = {}
    blockers: list[str] = []
    for contract in contracts:
        paper_contract = _paper_contract(contract)
        direction = str(dict(paper_contract.get("filter_contract") or {}).get("direction") or "").strip().upper()
        if direction not in {"LONG", "SHORT"}:
            blockers.append("contract_direction_missing_or_invalid")
            continue
        for raw_symbol in list(paper_contract.get("symbols") or []):
            symbol = str(raw_symbol or "").strip().upper()
            if not symbol:
                continue
            previous = directions.get(symbol)
            if previous and previous != direction:
                blockers.append(f"direction_conflict:{symbol}:{previous}_vs_{direction}")
                continue
            directions[symbol] = direction
    return directions, blockers


def _ordered_symbols(portfolio_mix: dict[str, Any], directions: dict[str, str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw_symbol in list(portfolio_mix.get("combined_symbols") or []):
        symbol = str(raw_symbol or "").strip().upper()
        if symbol and symbol in directions and symbol not in seen:
            ordered.append(symbol)
            seen.add(symbol)
    for symbol in sorted(directions):
        if symbol not in seen:
            ordered.append(symbol)
    return ordered


def _max_concurrent(portfolio_mix: dict[str, Any]) -> int:
    operator_summary = dict(portfolio_mix.get("operator_summary") or {})
    value = _safe_int(operator_summary.get("recommended_max_concurrent_positions"))
    if value > 0:
        return value
    scenarios = [dict(item) for item in list(portfolio_mix.get("recommended_portfolio_replay_scenarios") or [])]
    if scenarios:
        return max(_safe_int(scenarios[0].get("max_concurrent_positions")), 1)
    return 2


def _exit_policy_names(contracts: list[dict[str, Any]]) -> list[str]:
    names = []
    for contract in contracts:
        name = str(_paper_contract(contract).get("exit_policy_name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _direction_filter_env(contracts: list[dict[str, Any]]) -> dict[str, str]:
    env: dict[str, str] = {}
    by_direction: dict[str, dict[str, Any]] = {}
    for contract in contracts:
        filter_contract = dict(_paper_contract(contract).get("filter_contract") or {})
        direction = str(filter_contract.get("direction") or "").strip().upper()
        if direction in {"LONG", "SHORT"} and direction not in by_direction:
            by_direction[direction] = filter_contract
    for direction, prefix in (("LONG", "LONG"), ("SHORT", "SHORT")):
        filter_contract = by_direction.get(direction)
        if not filter_contract:
            continue
        hours = [
            str(_safe_int(hour))
            for hour in list(filter_contract.get("setup_hour_utc") or [])
            if str(hour).strip() != ""
        ]
        if hours:
            env[f"SESSION_IMPULSE_RETEST_INTRABAR_{prefix}_SETUP_HOURS_UTC"] = ",".join(hours)
        if filter_contract.get("min_reclaim_body_atr") is not None:
            env[f"SESSION_IMPULSE_RETEST_INTRABAR_{prefix}_MIN_RECLAIM_BODY_ATR"] = str(
                filter_contract.get("min_reclaim_body_atr")
            )
        if filter_contract.get("min_volume_factor") is not None:
            env[f"SESSION_IMPULSE_RETEST_INTRABAR_{prefix}_MIN_VOLUME_FACTOR"] = str(
                filter_contract.get("min_volume_factor")
            )
        if filter_contract.get("min_risk_atr") is not None:
            env[f"SESSION_IMPULSE_RETEST_INTRABAR_{prefix}_MIN_RISK_ATR"] = str(
                filter_contract.get("min_risk_atr")
            )
    return env


def _structure_policy_env(exit_policy_name: str) -> dict[str, str]:
    if not exit_policy_name.startswith("structure_buffered_"):
        return {}
    swing = "6"
    stop_buffer = "0.12"
    target_buffer = "0.08"
    match = re.search(r"swing(\d+)_stop([0-9.]+)_tpbuf([0-9.]+)", exit_policy_name)
    if match:
        swing, stop_buffer, target_buffer = match.group(1), match.group(2), match.group(3)
    return {
        "SESSION_IMPULSE_RETEST_EXIT_STOP_MODE": "structure_floor",
        "SESSION_IMPULSE_RETEST_EXIT_MIN_STOP_PCT": "0.003",
        "SESSION_IMPULSE_RETEST_EXIT_MIN_RISK_ATR": "0.35",
        "SESSION_IMPULSE_RETEST_EXIT_STRUCTURE_STOP_SWING_BARS": swing,
        "SESSION_IMPULSE_RETEST_EXIT_STRUCTURE_STOP_BUFFER_ATR": stop_buffer,
        "SESSION_IMPULSE_RETEST_EXIT_TARGET_RR": "2.5",
        "SESSION_IMPULSE_RETEST_EXIT_TP1_RR": "1.0",
        "SESSION_IMPULSE_RETEST_EXIT_TP1_FRACTION": "0.35",
        "SESSION_IMPULSE_RETEST_EXIT_TP2_FRACTION": "0.65",
        "SESSION_IMPULSE_RETEST_EXIT_ADAPTIVE_TARGETS_ENABLED": "true",
        "SESSION_IMPULSE_RETEST_EXIT_STRUCTURE_TARGETS_ENABLED": "true",
        "SESSION_IMPULSE_RETEST_EXIT_STRUCTURE_ENTRY_MAX_DISTANCE_ATR": "0.45",
        "SESSION_IMPULSE_RETEST_EXIT_STRUCTURE_TARGET_BUFFER_ATR": target_buffer,
        "SESSION_IMPULSE_RETEST_EXIT_STRUCTURE_TP1_MIN_RR": "0.8",
        "SESSION_IMPULSE_RETEST_EXIT_STRUCTURE_TP2_MIN_RR": "1.6",
        "SESSION_IMPULSE_RETEST_EXIT_STRUCTURE_TP_MAX_RR": "3.2",
        "SESSION_IMPULSE_RETEST_EXIT_ENTRY_CONFIRMATION_DELAY_MINUTES": "0",
    }


def _position_management_policy_env(exit_policy_name: str) -> dict[str, str]:
    env: dict[str, str] = {}
    pm_stop = re.search(r"pm_stop([0-9.]+)r", exit_policy_name)
    if pm_stop:
        env["SESSION_IMPULSE_RETEST_EXIT_STOP_AFTER_PARTIAL_RR"] = pm_stop.group(1)
        env["AUTO_TRADING_LIVE_BREAKEVEN_AFTER_PARTIAL_ENABLED"] = "true"
        if float(pm_stop.group(1)) == 0.0:
            env["AUTO_TRADING_LIVE_BREAKEVEN_OFFSET_BPS"] = "0.0"
            env["AUTO_TRADING_LIVE_BREAKEVEN_MIN_IMPROVEMENT_BPS"] = "0.0"
    if "advvol" in exit_policy_name:
        after_partial_only = "true" if "advvol_after_partial" in exit_policy_name else "false"
        env.update(
            {
                "SESSION_IMPULSE_RETEST_EXIT_ADVERSE_VOLUME_ENABLED": "true",
                "SESSION_IMPULSE_RETEST_EXIT_ADVERSE_VOLUME_AFTER_PARTIAL_ONLY": after_partial_only,
                "SESSION_IMPULSE_RETEST_EXIT_ADVERSE_VOLUME_MIN_FACTOR": "3.0",
                "SESSION_IMPULSE_RETEST_EXIT_ADVERSE_VOLUME_MIN_BODY_R": "0.35",
                "SESSION_IMPULSE_RETEST_EXIT_ADVERSE_VOLUME_LOOKBACK_BARS": "20",
                "AUTO_TRADING_LIVE_ADVERSE_VOLUME_EXIT_ENABLED": "true",
                "AUTO_TRADING_LIVE_ADVERSE_VOLUME_EXIT_AFTER_PARTIAL_ONLY": after_partial_only,
                "AUTO_TRADING_LIVE_ADVERSE_VOLUME_EXIT_MIN_FACTOR": "3.0",
                "AUTO_TRADING_LIVE_ADVERSE_VOLUME_EXIT_MIN_BODY_R": "0.35",
                "AUTO_TRADING_LIVE_ADVERSE_VOLUME_EXIT_LOOKBACK_BARS": "20",
            }
        )
    return env


def _required_core_live_slots(symbols: list[str]) -> int:
    try:
        from app.services.micro_main_universe_policy import build_micro_main_universe_policy_snapshot
    except Exception:
        return len(symbols)
    policy = build_micro_main_universe_policy_snapshot()
    entries = [dict(item) for item in list(policy.get("entries") or []) if isinstance(item, dict)]
    by_symbol = {str(item.get("symbol") or "").upper(): item for item in entries}
    required = len(symbols)
    for symbol in symbols:
        entry = by_symbol.get(symbol)
        if not entry or str(entry.get("tier") or "").lower() != "core":
            continue
        quote = "USDT" if symbol.endswith("USDT") else "USDC" if symbol.endswith("USDC") else ""
        ranked_core = sorted(
            [
                item
                for item in entries
                if str(item.get("tier") or "").lower() == "core"
                and (not quote or str(item.get("symbol") or "").upper().endswith(quote))
            ],
            key=lambda item: _safe_int(item.get("rollout_priority")),
        )
        for index, item in enumerate(ranked_core, start=1):
            if str(item.get("symbol") or "").upper() == symbol:
                required = max(required, index)
                break
    return required


def _runtime_support_gaps(exit_policy_name: str) -> list[str]:
    gaps: list[str] = []
    if exit_policy_name != "structure_buffered_swing6_stop0.12_tpbuf0.08_pm_stop0.00r_advvol_any":
        gaps.append("runtime_guard_exit_contract_support_unknown")
    pm_stop = re.search(r"pm_stop([0-9.]+)r", exit_policy_name)
    if "pm_stop" in exit_policy_name and (not pm_stop or float(pm_stop.group(1)) != 0.0):
        gaps.append("live_stop_after_partial_must_be_verified_against_candidate_policy")
    return gaps


def build_payload(
    *,
    portfolio_mix_review_path: Path,
    contract_paths: list[Path],
    allow_contract_subset: bool = False,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    portfolio_mix = _load_json(portfolio_mix_review_path)
    contracts = [_load_json(path) for path in contract_paths]
    directions, direction_blockers = _direction_contract(contracts)
    symbols = _ordered_symbols(portfolio_mix, directions)
    exit_policy_names = _exit_policy_names(contracts)
    proposal_blockers = list(direction_blockers)
    if str(portfolio_mix.get("recommended_state") or "") != "PORTFOLIO_MIX_PAPER_WATCH":
        proposal_blockers.append("portfolio_mix_not_in_paper_watch_state")
    if str(portfolio_mix.get("live_action") or "") != "KEEP_CLOSE_ONLY":
        proposal_blockers.append("portfolio_mix_live_action_not_close_only")
    if _safe_bool(portfolio_mix.get("live_ready")) or _safe_bool(portfolio_mix.get("order_submission_allowed")):
        proposal_blockers.append("portfolio_mix_has_live_authority")
    if len(exit_policy_names) != 1:
        proposal_blockers.append("candidate_contracts_do_not_share_one_exit_policy")
    portfolio_symbols = {str(item or "").upper() for item in list(portfolio_mix.get("combined_symbols") or [])}
    if set(symbols) != portfolio_symbols and not (
        allow_contract_subset and set(symbols).issubset(portfolio_symbols)
    ):
        proposal_blockers.append("portfolio_mix_symbols_do_not_match_contract_direction_symbols")

    exit_policy_name = exit_policy_names[0] if len(exit_policy_names) == 1 else ""
    max_concurrent = _max_concurrent(portfolio_mix)
    required_core_live_slots = _required_core_live_slots(symbols)
    direction_contract = ",".join(f"{symbol}:{directions[symbol]}" for symbol in symbols)
    env_values: dict[str, str] = {
        "AUTO_TRADING_CLOSE_ONLY": "true",
        "AUTO_TRADING_EXECUTION_MODE": "MICRO_LIVE",
        "AUTO_TRADING_ALLOWED_SYMBOLS": ",".join(symbols),
        "AUTO_TRADING_MICRO_LIVE_ALLOWED_SYMBOLS": ",".join(symbols),
        "AUTO_TRADING_MICRO_LIVE_SYMBOL_PRIORITY": ",".join(symbols),
        "AUTO_TRADING_MICRO_LIVE_DIRECTION_CONTRACT": direction_contract,
        "AUTO_TRADING_MICRO_LIVE_MAX_CONCURRENT_POSITIONS": str(max_concurrent),
        "AUTO_TRADING_LIVE_MAX_SAME_FAMILY_ENTRIES_PER_WINDOW": str(max_concurrent),
        "AUTO_TRADING_LIVE_MAX_SAME_FAMILY_DIRECTION_EXPOSURES": str(max_concurrent),
        "SESSION_IMPULSE_RETEST_ALLOWED_SYMBOLS": ",".join(symbols),
        "SESSION_IMPULSE_RETEST_CORE_LIVE_SLOTS": str(required_core_live_slots),
        "SESSION_IMPULSE_RETEST_ENTRY_TIMING_MODEL": "intrabar_1m_confirm_next_open",
        "SESSION_IMPULSE_RETEST_EXIT_POLICY_NAME": exit_policy_name,
        "AUTO_TRADING_LIVE_RISK_PER_TRADE_PCT": "0.01",
        "AUTO_TRADING_LIVE_LEVERAGE_CAP": "10",
    }
    env_values.update(_direction_filter_env(contracts))
    env_values.update(_structure_policy_env(exit_policy_name))
    env_values.update(_position_management_policy_env(exit_policy_name))

    support_gaps = _runtime_support_gaps(exit_policy_name)
    return {
        "schema_version": "micro_intrabar_portfolio_mix_live_config_proposal_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "config_proposal_only_no_file_edit_no_order_submission",
        "portfolio_mix_review_path": _display_path(portfolio_mix_review_path),
        "contract_paths": [_display_path(path) for path in contract_paths],
        "recommended_state": "CONFIG_PROPOSAL_BLOCKED_FOR_RUNTIME_GAPS" if support_gaps or proposal_blockers else "CONFIG_PROPOSAL_READY_FOR_MANUAL_REVIEW",
        "proposal_blockers": proposal_blockers,
        "runtime_support_gaps": support_gaps,
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": False,
        "order_submission_allowed": False,
        "symbols": symbols,
        "symbol_count": len(symbols),
        "direction_contract": {symbol: [directions[symbol]] for symbol in symbols},
        "exit_policy_name": exit_policy_name,
        "recommended_max_concurrent_positions": max_concurrent,
        "required_core_live_slots": required_core_live_slots,
        "allow_contract_subset": bool(allow_contract_subset),
        "env_proposal": env_values,
        "env_lines": [f"{key}={value}" for key, value in env_values.items()],
        "operator_summary": {
            "action": "Do not apply automatically; implement runtime gaps and rerun guards before any live promotion.",
            "order_submission_allowed": False,
        },
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Micro Intrabar Portfolio Mix Live Config Proposal",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- authority: {payload.get('authority')}",
        f"- recommended_state: {payload.get('recommended_state')}",
        f"- live_action: {payload.get('live_action')}",
        f"- order_submission_allowed: {payload.get('order_submission_allowed')}",
        f"- symbols: {payload.get('symbol_count')}",
        f"- exit_policy_name: {payload.get('exit_policy_name')}",
        f"- recommended_max_concurrent_positions: {payload.get('recommended_max_concurrent_positions')}",
        f"- proposal_blockers: {payload.get('proposal_blockers')}",
        f"- runtime_support_gaps: {payload.get('runtime_support_gaps')}",
        "",
        "## Env Proposal",
        "",
        "```dotenv",
        *list(payload.get("env_lines") or []),
        "```",
        "",
        "This proposal does not edit `.env`, submit orders, or enable live routing.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    generated_at = datetime.now(UTC)
    payload = build_payload(
        portfolio_mix_review_path=_resolve_path(args.portfolio_mix_review_path),
        contract_paths=_csv_paths(args.contract_path),
        allow_contract_subset=bool(args.allow_contract_subset),
        generated_at=generated_at,
    )
    if args.write_report:
        report_dir = _resolve_path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = generated_at.strftime("%Y%m%dT%H%M%S%fZ")
        json_path = report_dir / f"micro_intrabar_portfolio_mix_live_config_proposal_{stamp}.json"
        md_path = report_dir / f"micro_intrabar_portfolio_mix_live_config_proposal_{stamp}.md"
        payload["report_path"] = _display_path(json_path)
        payload["latest_report_path"] = _display_path(report_dir / "latest.json")
        atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(md_path, _render_markdown(payload))
        atomic_write_text(report_dir / "latest.json", json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(report_dir / "latest.md", _render_markdown(payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
