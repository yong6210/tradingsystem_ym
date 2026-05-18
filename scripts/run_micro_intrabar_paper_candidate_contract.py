#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text


DEFAULT_LADDER_PATH = ROOT_DIR / "reports/validation/micro_research_candidate_ladder/latest.json"

FILTER_CONTRACTS: dict[str, dict[str, Any]] = {
    "volume12_hour13_14_long": {
        "direction": "long",
        "setup_hour_utc": [13, 14],
        "min_volume_factor": 1.20,
        "description": "long-only, projected 5m volume >= 1.20x, setup hour UTC 13 or 14",
    },
    "volume12_body025_hour13_14_long": {
        "direction": "long",
        "setup_hour_utc": [13, 14],
        "min_volume_factor": 1.20,
        "min_reclaim_body_atr": 0.25,
        "description": "long-only, volume >= 1.20x, body reclaim >= 0.25 ATR, setup hour UTC 13 or 14",
    },
    "volume12_risk05_hour13_14_long": {
        "direction": "long",
        "setup_hour_utc": [13, 14],
        "min_volume_factor": 1.20,
        "min_risk_atr": 0.50,
        "description": "long-only, volume >= 1.20x, risk ATR >= 0.50, setup hour UTC 13 or 14",
    },
    "volume12_risk05_hour13_15_long": {
        "direction": "long",
        "setup_hour_utc": [13, 14, 15],
        "min_volume_factor": 1.20,
        "min_risk_atr": 0.50,
        "description": "long-only, volume >= 1.20x, risk ATR >= 0.50, setup hour UTC 13, 14, or 15",
    },
    "body025_hour13_14_long": {
        "direction": "long",
        "setup_hour_utc": [13, 14],
        "min_reclaim_body_atr": 0.25,
        "description": "long-only, body reclaim >= 0.25 ATR, setup hour UTC 13 or 14",
    },
    "core12_volume12_hour13_14_long": {
        "direction": "long",
        "setup_hour_utc": [13, 14],
        "min_volume_factor": 1.20,
        "core12_only": True,
        "description": "core-12 subset, long-only, projected 5m volume >= 1.20x, setup hour UTC 13 or 14",
    },
}

DEFAULT_EXIT_POLICY_NAME = "structure_buffered_swing6_stop0.12_tpbuf0.08"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a paper-only contract for the best micro intrabar candidate.")
    parser.add_argument("--ladder-path", default=str(DEFAULT_LADDER_PATH))
    parser.add_argument("--candidate-name", default="")
    parser.add_argument("--report-dir", default="reports/operations/micro_intrabar_paper_candidate_contract")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


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


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_sort_key(row: dict[str, Any]) -> tuple[float, float, float]:
    stress = row.get("cost_stress")
    extra_005_total_r = None
    if isinstance(stress, dict):
        extra_005 = stress.get("extra_0_05r_per_trade")
        if isinstance(extra_005, dict):
            extra_005_total_r = _safe_float(extra_005.get("total_r"))
    return (
        -_safe_float(extra_005_total_r, _safe_float(row.get("total_r"))),
        -_safe_float(row.get("ev_r")),
        -_safe_float(row.get("total_r")),
    )


def _select_candidate(payload: dict[str, Any], *, candidate_name: str = "") -> dict[str, Any]:
    name = candidate_name.strip()
    rows = [
        dict(row)
        for row in list(payload.get("observations") or [])
        if str(row.get("decision") or "") == "PAPER_CANDIDATE"
        and str(row.get("family") or "") == "session_impulse_retest_intrabar_subset"
    ]
    if name:
        rows = [row for row in rows if str(row.get("policy_name") or "") == name]
    if not rows:
        raise ValueError("no matching PAPER_CANDIDATE intrabar subset row found")
    rows.sort(key=_candidate_sort_key)
    return rows[0]


def _report_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def build_payload(
    ladder_path: Path,
    *,
    candidate_name: str = "",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    ladder_payload = _load_json(ladder_path)
    candidate = _select_candidate(ladder_payload, candidate_name=candidate_name)
    policy_name = str(candidate.get("policy_name") or "")
    source_policy_names = [
        str(name).strip()
        for name in list(candidate.get("source_policy_names") or [])
        if str(name).strip()
    ]
    exit_policy_name = source_policy_names[0] if source_policy_names else DEFAULT_EXIT_POLICY_NAME
    filter_contract = dict(FILTER_CONTRACTS.get(policy_name) or {"description": "unknown filter; manual review required"})
    symbol_count = _safe_int(candidate.get("symbol_count"))
    live_ready = symbol_count >= 8 and str(candidate.get("decision") or "") == "LIVE_CANDIDATE_REVIEW"
    cost_stress = candidate.get("cost_stress") if isinstance(candidate.get("cost_stress"), dict) else {}
    cost_x2 = cost_stress.get("cost_x2_0") if isinstance(cost_stress, dict) else {}
    fee_fragile = isinstance(cost_x2, dict) and _safe_float(cost_x2.get("total_r")) <= 0.0
    risk_notes = [
        "Do not route this candidate to live orders from this contract.",
        "A 4-symbol positive result can collect paper evidence, but it is too narrow for broad live rollout.",
        "If paper evidence is positive, next step is expansion or explicit narrow-pilot review, not direct live enablement.",
    ]
    if fee_fragile:
        risk_notes.append("Fee stress warning: the candidate turns negative when modeled costs are doubled.")
    return {
        "schema_version": "micro_intrabar_paper_candidate_contract_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "paper_only_no_live_authority_change",
        "source_ladder_path": str(ladder_path.relative_to(ROOT_DIR) if ladder_path.is_relative_to(ROOT_DIR) else ladder_path),
        "recommended_state": "PAPER_ONLY_SHADOW_WATCH",
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": live_ready,
        "candidate": candidate,
        "paper_contract": {
            "family": "session_impulse_retest",
            "research_family": "session_impulse_retest_intrabar_subset",
            "policy_name": policy_name,
            "exit_policy_name": exit_policy_name,
            "symbols": list(candidate.get("symbols") or []),
            "filter_contract": filter_contract,
            "entry_timing_model": candidate.get("entry_timing_model"),
            "execution_mode": "PAPER_OR_SHADOW_ONLY",
            "live_risk_r": 0.0,
            "cost_stress": cost_stress,
        },
        "promotion_gates": {
            "minimum_closed_paper_trades": 30,
            "minimum_observation_days": 30,
            "post_cost_total_r_must_be_positive": True,
            "post_cost_ev_r_floor": 0.02,
            "maximum_live_promotion_without_expansion": "PAPER_EXTENDED_REVIEW",
            "full_live_review_requires_symbol_count_at_least": 8,
            "full_live_review_requires_positive_symbol_fraction_at_least": 0.60,
            "full_live_review_requires_positive_year_fraction_at_least": 0.75,
        },
        "risk_notes": risk_notes,
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    candidate = dict(payload.get("candidate") or {})
    contract = dict(payload.get("paper_contract") or {})
    gates = dict(payload.get("promotion_gates") or {})
    lines = [
        "# Micro Intrabar Paper Candidate Contract",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- authority: {payload.get('authority')}",
        f"- recommended_state: {payload.get('recommended_state')}",
        f"- live_action: {payload.get('live_action')}",
        f"- policy: {contract.get('policy_name')}",
        f"- exit_policy_name: {contract.get('exit_policy_name')}",
        f"- symbols: {','.join(list(contract.get('symbols') or []))}",
        f"- trades: {candidate.get('closed')} total_r: {candidate.get('total_r')} ev: {candidate.get('ev_r')}",
        f"- profit_to_dd: {candidate.get('profit_to_dd')} positive_year_fraction: {candidate.get('positive_year_fraction')} positive_symbol_fraction: {candidate.get('positive_symbol_fraction')}",
        "",
        "## Paper Contract",
        "",
        f"- filter: {dict(contract.get('filter_contract') or {}).get('description')}",
        f"- entry_timing_model: {contract.get('entry_timing_model')}",
        f"- execution_mode: {contract.get('execution_mode')}",
        f"- live_risk_r: {contract.get('live_risk_r')}",
        "",
        "## Promotion Gates",
        "",
        f"- minimum_closed_paper_trades: {gates.get('minimum_closed_paper_trades')}",
        f"- minimum_observation_days: {gates.get('minimum_observation_days')}",
        f"- post_cost_ev_r_floor: {gates.get('post_cost_ev_r_floor')}",
        f"- full_live_review_requires_symbol_count_at_least: {gates.get('full_live_review_requires_symbol_count_at_least')}",
        "",
        "This contract does not enable live routing.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    ladder_path = _resolve_path(args.ladder_path)
    generated_at = datetime.now(UTC)
    payload = build_payload(ladder_path, candidate_name=args.candidate_name, generated_at=generated_at)
    if args.write_report:
        report_dir = _resolve_path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = _report_stamp(generated_at)
        json_path = report_dir / f"micro_intrabar_paper_candidate_contract_{stamp}.json"
        md_path = report_dir / f"micro_intrabar_paper_candidate_contract_{stamp}.md"
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
