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


DEFAULT_WALKFORWARD_PATH = ROOT_DIR / "reports/validation/micro_intrabar_walkforward_symbol_filters/latest.json"
DEFAULT_EXIT_POLICY_NAME = "structure_buffered_swing6_stop0.12_tpbuf0.08_pm_stop0.00r_advvol_any"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a paper-only contract from a no-lookahead intrabar walk-forward candidate."
    )
    parser.add_argument("--walkforward-path", default=str(DEFAULT_WALKFORWARD_PATH))
    parser.add_argument("--candidate-rank", type=int, default=1)
    parser.add_argument("--filter-name", default="")
    parser.add_argument("--symbols", default="", help="Optional comma-separated exact selected-symbol set.")
    parser.add_argument("--exit-policy-name", default=DEFAULT_EXIT_POLICY_NAME)
    parser.add_argument("--report-dir", default="reports/operations/micro_intrabar_paper_candidate_contract")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


def _resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _csv_symbols(raw: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for part in str(raw or "").split(","):
        symbol = part.strip().upper()
        if symbol and symbol not in seen:
            out.append(symbol)
            seen.add(symbol)
    return out


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed == parsed else default


def _report_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def _candidate_matches(candidate: dict[str, Any], *, filter_name: str, symbols: list[str]) -> bool:
    if filter_name and str(candidate.get("filter_name") or "") != filter_name:
        return False
    if symbols:
        selected = [str(symbol).upper() for symbol in list(candidate.get("selected_symbols") or [])]
        if selected != symbols:
            return False
    return True


def _select_candidate(payload: dict[str, Any], *, rank: int, filter_name: str, symbols: list[str]) -> dict[str, Any]:
    candidates = [dict(item) for item in list(payload.get("candidates") or []) if isinstance(item, dict)]
    if filter_name or symbols:
        matches = [candidate for candidate in candidates if _candidate_matches(candidate, filter_name=filter_name, symbols=symbols)]
        if not matches:
            raise ValueError("no walk-forward candidate matched the requested filter/symbols")
        return matches[0]
    index = max(int(rank), 1) - 1
    if index >= len(candidates):
        raise ValueError(f"candidate rank {rank} is unavailable")
    return candidates[index]


def _display_path(path: Path) -> str:
    return str(path.relative_to(ROOT_DIR) if path.is_relative_to(ROOT_DIR) else path)


def build_payload(
    walkforward_path: Path,
    *,
    candidate_rank: int = 1,
    filter_name: str = "",
    symbols: list[str] | None = None,
    exit_policy_name: str = DEFAULT_EXIT_POLICY_NAME,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    walkforward = _load_json(walkforward_path)
    symbols = list(symbols or [])
    candidate = _select_candidate(
        walkforward,
        rank=candidate_rank,
        filter_name=str(filter_name or "").strip(),
        symbols=symbols,
    )
    selected_symbols = [str(symbol).strip().upper() for symbol in list(candidate.get("selected_symbols") or []) if str(symbol).strip()]
    filter_contract = dict(candidate.get("filter_contract") or {})
    all_summary = dict(candidate.get("all_summary") or {})
    oos_summary = dict(candidate.get("oos_summary") or {})
    train_summary = dict(candidate.get("train_summary") or {})
    source = dict(walkforward.get("source") or {})
    sources = [dict(item) for item in list(source.get("sources") or []) if isinstance(item, dict)]
    source_scope = sources[0] if sources else {}
    days = _safe_int(source_scope.get("days"), 0)
    cost_stress = candidate.get("all_cost_stress") if isinstance(candidate.get("all_cost_stress"), dict) else {}
    candidate_snapshot = {
        "decision": candidate.get("decision"),
        "reasons": candidate.get("reasons") or [],
        "source_path": _display_path(walkforward_path),
        "schema_version": walkforward.get("schema_version"),
        "generated_at": walkforward.get("generated_at"),
        "family": "session_impulse_retest_intrabar_walkforward",
        "policy_name": candidate.get("filter_name"),
        "exit_policy_name": exit_policy_name,
        "days": days,
        "symbol_count": len(selected_symbols),
        "symbols": selected_symbols,
        "entry_timing_model": "intrabar_1m_confirm_next_open",
        "no_lookahead": True,
        "closed": _safe_int(all_summary.get("closed")),
        "total_r": _safe_float(all_summary.get("total_r")),
        "ev_r": _safe_float(all_summary.get("ev_r")),
        "win_rate": _safe_float(all_summary.get("win_rate")),
        "max_dd_r": _safe_float(all_summary.get("max_dd_r")),
        "profit_to_dd": _safe_float(all_summary.get("profit_to_dd")),
        "positive_symbol_fraction": _safe_float(all_summary.get("positive_symbol_fraction")),
        "positive_year_fraction": _safe_float(all_summary.get("positive_year_fraction")),
        "oos_closed": _safe_int(oos_summary.get("closed")),
        "oos_total_r": _safe_float(oos_summary.get("total_r")),
        "oos_ev_r": _safe_float(oos_summary.get("ev_r")),
        "train_closed": _safe_int(train_summary.get("closed")),
        "train_total_r": _safe_float(train_summary.get("total_r")),
        "train_ev_r": _safe_float(train_summary.get("ev_r")),
        "filter_contract": filter_contract,
        "cost_stress": cost_stress,
    }
    risk_notes = [
        "Do not route this candidate to live orders from this contract.",
        "This candidate is no-lookahead and walk-forward positive, but it is still a narrow paper/shadow candidate.",
        "Full 31-symbol intrabar SIR is negative; only the selected-symbol/filter slice should be watched.",
        "Promotion requires live paper evidence and a separate governance decision.",
    ]
    return {
        "schema_version": "micro_intrabar_paper_candidate_contract_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "paper_only_no_live_authority_change",
        "source_walkforward_path": _display_path(walkforward_path),
        "recommended_state": "PAPER_ONLY_SHADOW_WATCH",
        "live_action": "KEEP_CLOSE_ONLY",
        "live_ready": False,
        "candidate": candidate_snapshot,
        "paper_contract": {
            "family": "session_impulse_retest",
            "research_family": "session_impulse_retest_intrabar_walkforward",
            "policy_name": candidate.get("filter_name"),
            "exit_policy_name": exit_policy_name,
            "symbols": selected_symbols,
            "filter_contract": filter_contract,
            "entry_timing_model": "intrabar_1m_confirm_next_open",
            "execution_mode": "PAPER_OR_SHADOW_ONLY",
            "live_risk_r": 0.0,
            "all_summary": all_summary,
            "train_summary": train_summary,
            "oos_summary": oos_summary,
            "cost_stress": cost_stress,
        },
        "promotion_gates": {
            "minimum_closed_paper_trades": 30,
            "minimum_observation_days": 30,
            "post_cost_total_r_must_be_positive": True,
            "post_cost_ev_r_floor": 0.02,
            "full_live_review_requires_symbol_count_at_least": 4,
            "full_live_review_requires_positive_symbol_fraction_at_least": 0.75,
            "full_live_review_requires_positive_year_fraction_at_least": 0.75,
            "full_live_review_requires_oos_total_r_positive": True,
        },
        "risk_notes": risk_notes,
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    candidate = dict(payload.get("candidate") or {})
    contract = dict(payload.get("paper_contract") or {})
    all_summary = dict(contract.get("all_summary") or {})
    oos_summary = dict(contract.get("oos_summary") or {})
    extra = dict(dict(contract.get("cost_stress") or {}).get("extra_0_05r_per_trade") or {})
    lines = [
        "# Micro Intrabar Walk-Forward Paper Contract",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- authority: {payload.get('authority')}",
        f"- recommended_state: {payload.get('recommended_state')}",
        f"- live_action: {payload.get('live_action')}",
        f"- live_ready: {payload.get('live_ready')}",
        f"- policy: {contract.get('policy_name')}",
        f"- exit_policy_name: {contract.get('exit_policy_name')}",
        f"- symbols: {','.join(list(contract.get('symbols') or []))}",
        f"- all: trades={all_summary.get('closed')} total_r={all_summary.get('total_r')} ev={all_summary.get('ev_r')} max_dd={all_summary.get('max_dd_r')}",
        f"- oos: trades={oos_summary.get('closed')} total_r={oos_summary.get('total_r')} ev={oos_summary.get('ev_r')}",
        f"- extra_0_05r_total_r: {extra.get('total_r')}",
        f"- positive_year_fraction: {candidate.get('positive_year_fraction')}",
        "",
        "This contract does not enable live routing.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    generated_at = datetime.now(UTC)
    walkforward_path = _resolve_path(args.walkforward_path)
    payload = build_payload(
        walkforward_path,
        candidate_rank=int(args.candidate_rank),
        filter_name=str(args.filter_name or ""),
        symbols=_csv_symbols(args.symbols),
        exit_policy_name=str(args.exit_policy_name or DEFAULT_EXIT_POLICY_NAME),
        generated_at=generated_at,
    )
    if args.write_report:
        report_dir = _resolve_path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = _report_stamp(generated_at)
        json_path = report_dir / f"micro_intrabar_paper_candidate_contract_{stamp}.json"
        md_path = report_dir / f"micro_intrabar_paper_candidate_contract_{stamp}.md"
        latest_json = report_dir / "latest.json"
        latest_md = report_dir / "latest.md"
        payload["report_path"] = _display_path(json_path)
        payload["latest_report_path"] = _display_path(latest_json)
        atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(md_path, _render_markdown(payload))
        atomic_write_text(latest_json, json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        atomic_write_text(latest_md, _render_markdown(payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
