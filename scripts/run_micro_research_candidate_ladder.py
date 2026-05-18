#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.report_io import atomic_write_text


NO_LOOKAHEAD_ENTRY_MODELS = {
    "after_completed_5m_reaction_next_1m_open",
    "intrabar_1m_confirm_next_open",
}


@dataclass(frozen=True, slots=True)
class CandidateObservation:
    source_path: str
    schema_version: str
    generated_at: str
    family: str
    policy_name: str
    days: int
    symbols: tuple[str, ...]
    entry_timing_model: str
    no_lookahead: bool
    summary: dict[str, Any]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a conservative promotion ladder from micro-main research/backtest reports."
    )
    parser.add_argument(
        "--report-path",
        action="append",
        default=[],
        help="JSON report path. May be repeated. Comma-separated values are also accepted.",
    )
    parser.add_argument(
        "--report-glob",
        action="append",
        default=[],
        help="Glob for JSON reports. May be repeated.",
    )
    parser.add_argument("--report-dir", default="reports/validation/micro_research_candidate_ladder")
    parser.add_argument("--write-report", action="store_true")
    return parser.parse_args()


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


def _resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path


def _default_report_globs() -> list[str]:
    return [
        "reports/validation/structure_reaction_research/structure_reaction_research_*.json",
        "reports/validation/micro_main_intrabar_research/micro_main_intrabar_research_*.json",
        "reports/validation/micro_main_intrabar_subset_reports/micro_main_intrabar_subset_report_*.json",
    ]


def _expand_report_paths(report_paths: list[str], report_globs: list[str]) -> list[Path]:
    explicit: list[str] = []
    for item in report_paths:
        explicit.extend(part.strip() for part in str(item or "").split(",") if part.strip())
    patterns = list(report_globs) if report_globs else ([] if explicit else _default_report_globs())
    paths: list[Path] = []
    seen: set[Path] = set()
    for raw in explicit:
        path = _resolve_path(raw)
        if path.exists() and path not in seen:
            paths.append(path)
            seen.add(path)
    for pattern in patterns:
        resolved_pattern = str(_resolve_path(pattern))
        for raw_path in sorted(glob.glob(resolved_pattern)):
            path = Path(raw_path)
            if path.exists() and path not in seen:
                paths.append(path)
                seen.add(path)
    return paths


def _summary_from_proxy_result(item: dict[str, Any]) -> dict[str, Any]:
    summary = item.get("summary")
    return dict(summary) if isinstance(summary, dict) else {}


def _symbols_from_scope(scope: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(symbol).strip().upper()
        for symbol in list(scope.get("symbols") or [])
        if str(symbol).strip()
    )


def _symbols_from_totals(totals: Any, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(totals, dict):
        return fallback
    symbols = tuple(str(symbol).strip().upper() for symbol in totals if str(symbol).strip())
    return symbols or fallback


def _observations_from_intrabar_subset_report(
    path: Path,
    payload: dict[str, Any],
    *,
    schema_version: str,
    generated_at: str,
) -> list[CandidateObservation]:
    source_scope = payload.get("source_scope") if isinstance(payload.get("source_scope"), dict) else {}
    days = _safe_int(source_scope.get("days"), 0)
    source_symbols = _symbols_from_scope(source_scope)
    entry_timing_model = str(source_scope.get("entry_timing_model") or "")
    no_lookahead = entry_timing_model in NO_LOOKAHEAD_ENTRY_MODELS
    observations: list[CandidateObservation] = []
    for idx, item in enumerate(list(payload.get("results") or [])):
        if not isinstance(item, dict):
            continue
        source_policy_names = [
            str(name).strip()
            for name in list(source_scope.get("policy_names") or [])
            if str(name).strip()
        ]
        policy_breakdowns = [
            dict(policy_item)
            for policy_item in list(item.get("by_policy") or [])
            if isinstance(policy_item, dict) and isinstance(policy_item.get("summary"), dict)
        ]
        if policy_breakdowns:
            for policy_item in policy_breakdowns:
                summary = dict(policy_item.get("summary") or {})
                policy_name = str(policy_item.get("policy") or "").strip()
                if policy_name:
                    summary["source_policy_names"] = [policy_name]
                elif source_policy_names:
                    summary["source_policy_names"] = source_policy_names
                by_year_total_r = policy_item.get("by_year_total_r")
                if isinstance(by_year_total_r, dict) and not summary.get("by_year_total_r"):
                    summary["by_year_total_r"] = by_year_total_r
                by_symbol_total_r = policy_item.get("by_symbol_total_r")
                symbols = _symbols_from_totals(by_symbol_total_r, source_symbols)
                cost_stress = policy_item.get("cost_stress")
                if isinstance(cost_stress, dict):
                    summary["cost_stress"] = cost_stress
                observations.append(
                    CandidateObservation(
                        source_path=str(path.relative_to(ROOT_DIR) if path.is_relative_to(ROOT_DIR) else path),
                        schema_version=schema_version,
                        generated_at=generated_at,
                        family="session_impulse_retest_intrabar_subset",
                        policy_name=str(item.get("name") or f"subset_{idx}"),
                        days=days,
                        symbols=symbols,
                        entry_timing_model=entry_timing_model,
                        no_lookahead=no_lookahead,
                        summary=summary,
                    )
                )
            continue
        summary = dict(item.get("summary") or {})
        if not summary:
            continue
        if source_policy_names:
            summary["source_policy_names"] = source_policy_names
        by_year_total_r = item.get("by_year_total_r")
        if isinstance(by_year_total_r, dict) and not summary.get("by_year_total_r"):
            summary["by_year_total_r"] = by_year_total_r
        by_symbol_total_r = item.get("by_symbol_total_r")
        symbols = _symbols_from_totals(by_symbol_total_r, source_symbols)
        cost_stress = item.get("cost_stress")
        if isinstance(cost_stress, dict):
            summary["cost_stress"] = cost_stress
        observations.append(
            CandidateObservation(
                source_path=str(path.relative_to(ROOT_DIR) if path.is_relative_to(ROOT_DIR) else path),
                schema_version=schema_version,
                generated_at=generated_at,
                family="session_impulse_retest_intrabar_subset",
                policy_name=str(item.get("name") or f"subset_{idx}"),
                days=days,
                symbols=symbols,
                entry_timing_model=entry_timing_model,
                no_lookahead=no_lookahead,
                summary=summary,
            )
        )
    return observations


def _stress_total_r(summary: dict[str, Any], scenario: str) -> float | None:
    stress = summary.get("cost_stress")
    if not isinstance(stress, dict):
        return None
    item = stress.get(scenario)
    if not isinstance(item, dict):
        return None
    return _safe_float(item.get("total_r"))


def _observations_from_report(path: Path) -> list[CandidateObservation]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema_version = str(payload.get("schema_version") or "")
    generated_at = str(payload.get("generated_at") or "")
    if schema_version == "micro_main_intrabar_subset_report_v1":
        return _observations_from_intrabar_subset_report(
            path,
            payload,
            schema_version=schema_version,
            generated_at=generated_at,
        )
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    days = _safe_int(scope.get("days") if scope else payload.get("days"), 0)
    symbols = _symbols_from_scope(scope) or tuple(
        str(symbol).strip().upper()
        for symbol in list(payload.get("proxy_symbols") or [])
        if str(symbol).strip()
    )
    entry_timing_model = str(scope.get("entry_timing_model") or payload.get("entry_timing_model") or "")
    no_lookahead = entry_timing_model in NO_LOOKAHEAD_ENTRY_MODELS
    family = "unknown"
    if "structure_reaction" in schema_version:
        family = "htf_structure_reaction"
    elif "intrabar" in schema_version:
        family = "session_impulse_retest_intrabar"
    elif "micro_main_usdt_proxy" in schema_version or payload.get("proxy_symbols"):
        family = "session_impulse_retest_legacy_proxy"

    observations: list[CandidateObservation] = []
    results = payload.get("results")
    if isinstance(results, list):
        for idx, item in enumerate(results):
            if not isinstance(item, dict):
                continue
            policy = item.get("policy") if isinstance(item.get("policy"), dict) else {}
            policy_name = str(policy.get("name") or item.get("policy_name") or f"result_{idx}")
            summary = dict(item.get("summary") or {})
            observations.append(
                CandidateObservation(
                    source_path=str(path.relative_to(ROOT_DIR) if path.is_relative_to(ROOT_DIR) else path),
                    schema_version=schema_version,
                    generated_at=generated_at,
                    family=family,
                    policy_name=policy_name,
                    days=days,
                    symbols=symbols,
                    entry_timing_model=entry_timing_model,
                    no_lookahead=no_lookahead,
                    summary=summary,
                )
            )
    elif isinstance(results, dict):
        for key, item in sorted(results.items()):
            if not isinstance(item, dict):
                continue
            summary = _summary_from_proxy_result(item)
            if not summary:
                continue
            policy_name = str(item.get("profile_name") or key)
            observations.append(
                CandidateObservation(
                    source_path=str(path.relative_to(ROOT_DIR) if path.is_relative_to(ROOT_DIR) else path),
                    schema_version=schema_version,
                    generated_at=generated_at,
                    family=family,
                    policy_name=policy_name,
                    days=days,
                    symbols=(str(key).strip().upper(),),
                    entry_timing_model=entry_timing_model,
                    no_lookahead=no_lookahead,
                    summary=summary,
                )
            )
    return observations


def _decision(observation: CandidateObservation) -> tuple[str, list[str]]:
    summary = observation.summary
    closed = _safe_int(summary.get("closed") or summary.get("trades"), 0)
    total_r = _safe_float(summary.get("total_r"))
    ev_r = _safe_float(summary.get("ev_r"))
    max_dd_r = _safe_float(summary.get("max_dd_r"))
    profit_to_dd = _safe_float(summary.get("profit_to_dd"))
    symbol_count = _safe_int(summary.get("symbol_count"), len(observation.symbols))
    positive_symbol_fraction = _safe_float(summary.get("positive_symbol_fraction"), 1.0 if symbol_count <= 1 and total_r > 0 else 0.0)
    year_count = _safe_int(summary.get("year_count"), len(summary.get("by_year_total_r") or {}))
    positive_year_fraction = _safe_float(summary.get("positive_year_fraction"), 1.0 if year_count <= 1 and total_r > 0 else 0.0)
    reasons: list[str] = []
    warnings: list[str] = []
    cost_x2_total_r = _stress_total_r(summary, "cost_x2_0")
    extra_005_total_r = _stress_total_r(summary, "extra_0_05r_per_trade")

    if not observation.no_lookahead:
        reasons.append("not_no_lookahead_protocol")
    if closed <= 0:
        reasons.append("no_closed_trades")
    if total_r <= 0.0:
        reasons.append("non_positive_total_r")
    if ev_r <= 0.0:
        reasons.append("non_positive_ev")
    if observation.days < 365:
        reasons.append("short_horizon_under_1y")
    if year_count >= 2 and positive_year_fraction < 0.67:
        reasons.append("weak_year_consistency")
    if symbol_count >= 2 and positive_symbol_fraction < 0.50:
        reasons.append("weak_symbol_consistency")
    if max_dd_r > 0.0 and profit_to_dd < 0.50:
        reasons.append("weak_profit_to_drawdown")
    if extra_005_total_r is not None and extra_005_total_r <= 0.0:
        reasons.append("fee_stress_extra_0_05r_non_positive")
    if cost_x2_total_r is not None and cost_x2_total_r <= 0.0:
        warnings.append("fee_stress_cost_x2_non_positive")

    hard_reject = {
        "not_no_lookahead_protocol",
        "no_closed_trades",
        "non_positive_total_r",
        "non_positive_ev",
        "weak_year_consistency",
        "weak_symbol_consistency",
        "fee_stress_extra_0_05r_non_positive",
    }
    if any(reason in hard_reject for reason in reasons):
        return "REJECT", reasons + warnings

    live_fee_stress_ok = cost_x2_total_r is None or cost_x2_total_r > 0.0
    if observation.days >= 1095 and symbol_count >= 8 and ev_r >= 0.05 and profit_to_dd >= 1.0 and positive_year_fraction >= 0.75 and positive_symbol_fraction >= 0.60 and live_fee_stress_ok:
        return "LIVE_CANDIDATE_REVIEW", ["passes_long_horizon_multi_symbol_review_gate"] + warnings
    if observation.days >= 365 and symbol_count >= 4 and ev_r >= 0.02 and positive_year_fraction >= 0.67 and positive_symbol_fraction >= 0.50:
        return "PAPER_CANDIDATE", ["passes_1y_multi_symbol_paper_gate"] + warnings
    if total_r > 0.0 and ev_r > 0.0:
        if symbol_count <= 1:
            return "SHADOW_ONLY", ["single_symbol_positive_only"] + warnings
        return "SHADOW_ONLY", ["positive_but_not_promotable"] + warnings
    return "REJECT", (reasons or ["does_not_meet_minimum_gate"]) + warnings


def _observation_row(observation: CandidateObservation) -> dict[str, Any]:
    decision, reasons = _decision(observation)
    summary = observation.summary
    return {
        "decision": decision,
        "reasons": reasons,
        "source_path": observation.source_path,
        "schema_version": observation.schema_version,
        "generated_at": observation.generated_at,
        "family": observation.family,
        "policy_name": observation.policy_name,
        "days": observation.days,
        "symbol_count": _safe_int(summary.get("symbol_count"), len(observation.symbols)),
        "symbols": list(observation.symbols),
        "entry_timing_model": observation.entry_timing_model,
        "no_lookahead": observation.no_lookahead,
        "closed": _safe_int(summary.get("closed") or summary.get("trades"), 0),
        "total_r": round(_safe_float(summary.get("total_r")), 4),
        "gross_r": round(_safe_float(summary.get("gross_r")), 4),
        "ev_r": round(_safe_float(summary.get("ev_r")), 4),
        "win_rate": round(_safe_float(summary.get("win_rate")), 4),
        "max_dd_r": round(_safe_float(summary.get("max_dd_r")), 4),
        "profit_to_dd": round(_safe_float(summary.get("profit_to_dd")), 4),
        "positive_symbol_fraction": round(_safe_float(summary.get("positive_symbol_fraction")), 4),
        "positive_year_fraction": round(_safe_float(summary.get("positive_year_fraction")), 4),
        "by_year_total_r": summary.get("by_year_total_r") or {},
        "cost_stress": summary.get("cost_stress") or {},
        "source_policy_names": summary.get("source_policy_names") or [],
    }


def _sort_key(row: dict[str, Any]) -> tuple[int, float, int, float]:
    decision_rank = {
        "LIVE_CANDIDATE_REVIEW": 0,
        "PAPER_CANDIDATE": 1,
        "SHADOW_ONLY": 2,
        "REJECT": 3,
    }.get(str(row.get("decision")), 9)
    return (
        decision_rank,
        -_safe_float(row.get("total_r")),
        -_safe_int(row.get("days")),
        -_safe_float(row.get("ev_r")),
    )


def build_payload(paths: list[Path], *, generated_at: datetime | None = None) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(UTC)
    observations: list[CandidateObservation] = []
    load_errors: list[dict[str, str]] = []
    for path in paths:
        try:
            observations.extend(_observations_from_report(path))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            load_errors.append({"path": str(path), "error": str(exc)})

    rows = sorted((_observation_row(observation) for observation in observations), key=_sort_key)
    decision_counts: dict[str, int] = {}
    for row in rows:
        decision = str(row.get("decision"))
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
    return {
        "schema_version": "micro_research_candidate_ladder_v1",
        "generated_at": generated_at.isoformat(),
        "authority": "research_only_no_live_authority_change",
        "report_count": len(paths),
        "observation_count": len(rows),
        "decision_counts": dict(sorted(decision_counts.items())),
        "load_errors": load_errors,
        "promotion_rule_summary": {
            "live_review_requires": [
                "no-lookahead entry timing",
                "at least 1095 days",
                "at least 8 symbols",
                "positive total R and EV >= 0.05",
                "profit_to_dd >= 1.0",
                "positive_year_fraction >= 0.75",
                "positive_symbol_fraction >= 0.60",
            ],
            "single_symbol_positive_result": "shadow_only_not_live_candidate",
            "legacy_or_unknown_timing": "reject",
        },
        "observations": rows,
    }


def _report_stamp(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S%fZ")


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Micro Research Candidate Ladder",
        "",
        f"- generated_at: {payload.get('generated_at')}",
        f"- authority: {payload.get('authority')}",
        f"- report_count: {payload.get('report_count')}",
        f"- observation_count: {payload.get('observation_count')}",
        f"- decision_counts: {payload.get('decision_counts')}",
        "",
        "## Top Decisions",
    ]
    for row in list(payload.get("observations") or [])[:20]:
        lines.append(
            "- "
            f"{row.get('decision')} {row.get('family')}/{row.get('policy_name')} "
            f"days={row.get('days')} symbols={row.get('symbol_count')} "
            f"trades={row.get('closed')} total_r={row.get('total_r')} ev={row.get('ev_r')} "
            f"win={row.get('win_rate')} p_year={row.get('positive_year_fraction')} "
            f"p_symbol={row.get('positive_symbol_fraction')} reasons={row.get('reasons')} "
            f"source={row.get('source_path')}"
        )
    lines.extend(
        [
            "",
            "Live routing is not changed by this report. Any LIVE_CANDIDATE_REVIEW still requires a separate operator approval step.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    paths = _expand_report_paths(args.report_path, args.report_glob)
    generated_at = datetime.now(UTC)
    payload = build_payload(paths, generated_at=generated_at)
    if args.write_report:
        report_dir = Path(args.report_dir).expanduser()
        if not report_dir.is_absolute():
            report_dir = ROOT_DIR / report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = _report_stamp(generated_at)
        json_path = report_dir / f"micro_research_candidate_ladder_{stamp}.json"
        md_path = report_dir / f"micro_research_candidate_ladder_{stamp}.md"
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
